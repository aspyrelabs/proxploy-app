import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const calls: { path: string; body: unknown }[] = []
let selfGuard = false
// null means GET /hosts never resolves during the test (the pending-fetch
// case); otherwise the capabilities row(s) it answers with. Host 5 (the app
// target) and host 9 (the vm target) both default to every capability on,
// so the existing tests below need no change to keep passing.
let hostsResponse: { id: number; capabilities: Record<string, boolean> }[] | null = [
  { id: 5, capabilities: { monitoring: true, lifecycle: true, console: true, backup: true } },
  { id: 9, capabilities: { monitoring: true, lifecycle: true, console: true, backup: true } },
]

vi.mock('../api/client', () => {
  class ApiError extends Error {
    status: number; body: unknown
    constructor(status: number, body: unknown) {
      super(`API ${status}`); this.status = status; this.body = body
    }
  }
  return {
    ApiError,
    api: vi.fn((path: string, opts?: RequestInit) => {
      if (path === '/entitlements') {
        return Promise.resolve({ tier: 'builtin', features: { 'apps.lifecycle': true, 'vms.lifecycle': true }, grace: null, clock_skew: false })
      }
      if (path === '/hosts') {
        return hostsResponse == null ? new Promise(() => {}) : Promise.resolve(hostsResponse)
      }
      const body = opts?.body ? JSON.parse(String(opts.body)) : {}
      calls.push({ path, body })
      if (selfGuard && !body.confirm) {
        return Promise.reject(new ApiError(409, {
          error: 'self_target', confirm_phrase: 'Immich',
          detail: 'Immich is the container Proxploy itself runs in.',
        }))
      }
      return Promise.resolve({ job: { id: 1, kind: 'app.stop', status: 'queued' } })
    }),
  }
})

import { LifecycleActions } from '../components/LifecycleActions'

const wrap = (ui: React.ReactNode, qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })) => {
  return { ...render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>), qc }
}

describe('LifecycleActions', () => {
  beforeEach(() => {
    hostsResponse = [
      { id: 5, capabilities: { monitoring: true, lifecycle: true, console: true, backup: true } },
      { id: 9, capabilities: { monitoring: true, lifecycle: true, console: true, backup: true } },
    ]
  })

  it('offers Stop and Restart for a running target', () => {
    calls.length = 0; selfGuard = false
    wrap(<LifecycleActions target="app" id={5} name="Immich" status="running" hostId={5} />)
    expect(screen.getByRole('button', { name: 'Stop' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Restart' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Start' })).toBeNull()
  })

  it('offers only Start for a stopped target', () => {
    calls.length = 0; selfGuard = false
    wrap(<LifecycleActions target="app" id={5} name="Immich" status="stopped" hostId={5} />)
    expect(screen.getByRole('button', { name: 'Start' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Stop' })).toBeNull()
  })

  it('posts the action to the right path', async () => {
    calls.length = 0; selfGuard = false
    wrap(<LifecycleActions target="vm" id={9} name="win11" status="running" hostId={9} />)
    fireEvent.click(screen.getByRole('button', { name: 'Stop' }))
    await waitFor(() => expect(calls[0].path).toBe('/vms/9/stop'))
  })

  it('shows the typed-confirmation dialog on a self_target 409 and retries with it', async () => {
    calls.length = 0; selfGuard = true
    wrap(<LifecycleActions target="app" id={5} name="Immich" status="running" hostId={5} />)
    fireEvent.click(screen.getByRole('button', { name: 'Stop' }))
    expect(await screen.findByText(/container Proxploy itself runs in/)).toBeInTheDocument()

    const input = screen.getByLabelText(/type/i)
    fireEvent.change(input, { target: { value: 'wrong' } })
    expect(screen.getByRole('button', { name: /confirm/i })).toBeDisabled()

    fireEvent.change(input, { target: { value: 'Immich' } })
    fireEvent.click(screen.getByRole('button', { name: /confirm/i }))
    await waitFor(() => expect(calls.length).toBe(2))
    expect(calls[1].body).toEqual({ confirm: 'Immich' })
  })

  it('shows a single disabled "Working…" affordance instead of guessing an action set while pending', () => {
    calls.length = 0; selfGuard = false
    wrap(<LifecycleActions target="app" id={5} name="Immich" status="pending" hostId={5} />)
    expect(screen.getByRole('button', { name: 'Working…' })).toBeDisabled()
    expect(screen.queryByRole('button', { name: 'Start' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Stop' })).toBeNull()
  })

  it('does not invalidate the resource cache on a successful mutation, so the optimistic patch survives', async () => {
    calls.length = 0; selfGuard = false
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    qc.setQueryData(['apps'], [{ id: 5, name: 'Immich', status: 'running' }])
    const spy = vi.spyOn(qc, 'invalidateQueries')
    wrap(<LifecycleActions target="app" id={5} name="Immich" status="running" hostId={5} />, qc)
    fireEvent.click(screen.getByRole('button', { name: 'Stop' }))
    await waitFor(() => expect(calls.length).toBe(1))
    await waitFor(() => expect(spy).toHaveBeenCalledWith({ queryKey: ['jobs'] }))
    expect(spy).not.toHaveBeenCalledWith({ queryKey: ['apps'] })
    const rows = qc.getQueryData(['apps']) as any[]
    expect(rows[0].status).toBe('pending')
  })

  // Bug: an app's Stop/Restart rendered enabled even though its host answered
  // capabilities.lifecycle: false, and clicking Stop enqueued a job that only
  // then failed with "no lifecycle API token configured".
  it('disables Stop/Restart when the host reports capabilities.lifecycle: false, and says why', async () => {
    hostsResponse = [{ id: 5, capabilities: { monitoring: true, lifecycle: false, console: true, backup: true } }]
    wrap(<LifecycleActions target="app" id={5} name="Immich" status="running" hostId={5} />)
    await waitFor(() => expect(screen.getByRole('button', { name: 'Stop' })).toBeDisabled())
    expect(screen.getByRole('button', { name: 'Restart' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Stop' }))
      .toHaveAttribute('title', expect.stringContaining('lifecycle'))
  })

  // The refreshDenied pattern (routes/store.tsx): capabilities read
  // undefined before GET /hosts resolves, and disabling on that alone would
  // grey out a perfectly capable host for the whole first fetch.
  it('does not disable Stop/Restart while the hosts query is still loading', () => {
    hostsResponse = null
    wrap(<LifecycleActions target="app" id={5} name="Immich" status="running" hostId={5} />)
    expect(screen.getByRole('button', { name: 'Stop' })).toBeEnabled()
    expect(screen.getByRole('button', { name: 'Restart' })).toBeEnabled()
  })
})
