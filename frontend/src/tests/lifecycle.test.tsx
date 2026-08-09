import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

const calls: { path: string; body: unknown }[] = []
let selfGuard = false

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
  it('offers Stop and Restart for a running target', () => {
    calls.length = 0; selfGuard = false
    wrap(<LifecycleActions target="app" id={5} name="Immich" status="running" />)
    expect(screen.getByRole('button', { name: 'Stop' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Restart' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Start' })).toBeNull()
  })

  it('offers only Start for a stopped target', () => {
    calls.length = 0; selfGuard = false
    wrap(<LifecycleActions target="app" id={5} name="Immich" status="stopped" />)
    expect(screen.getByRole('button', { name: 'Start' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Stop' })).toBeNull()
  })

  it('posts the action to the right path', async () => {
    calls.length = 0; selfGuard = false
    wrap(<LifecycleActions target="vm" id={9} name="win11" status="running" />)
    fireEvent.click(screen.getByRole('button', { name: 'Stop' }))
    await waitFor(() => expect(calls[0].path).toBe('/vms/9/stop'))
  })

  it('shows the typed-confirmation dialog on a self_target 409 and retries with it', async () => {
    calls.length = 0; selfGuard = true
    wrap(<LifecycleActions target="app" id={5} name="Immich" status="running" />)
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
    wrap(<LifecycleActions target="app" id={5} name="Immich" status="pending" />)
    expect(screen.getByRole('button', { name: 'Working…' })).toBeDisabled()
    expect(screen.queryByRole('button', { name: 'Start' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Stop' })).toBeNull()
  })

  it('does not invalidate the resource cache on a successful mutation, so the optimistic patch survives', async () => {
    calls.length = 0; selfGuard = false
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    qc.setQueryData(['apps'], [{ id: 5, name: 'Immich', status: 'running' }])
    const spy = vi.spyOn(qc, 'invalidateQueries')
    wrap(<LifecycleActions target="app" id={5} name="Immich" status="running" />, qc)
    fireEvent.click(screen.getByRole('button', { name: 'Stop' }))
    await waitFor(() => expect(calls.length).toBe(1))
    await waitFor(() => expect(spy).toHaveBeenCalledWith({ queryKey: ['jobs'] }))
    expect(spy).not.toHaveBeenCalledWith({ queryKey: ['apps'] })
    const rows = qc.getQueryData(['apps']) as any[]
    expect(rows[0].status).toBe('pending')
  })
})
