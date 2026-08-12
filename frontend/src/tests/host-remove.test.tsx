import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { notifySuccess, notifyError } = vi.hoisted(() => ({ notifySuccess: vi.fn(), notifyError: vi.fn() }))
vi.mock('../lib/notify', () => ({ notify: { success: notifySuccess, error: notifyError, info: vi.fn(), warning: vi.fn() } }))

const { ApiError } = vi.hoisted(() => ({
  ApiError: class extends Error {
    status: number; body: unknown
    constructor(status: number, body: unknown) { super(`API ${status}`); this.status = status; this.body = body }
  },
}))

const calls: { path: string; method?: string; body: unknown }[] = []
const CONFLICT_APPS = [{ id: 1, name: 'immich', ctid: 150 }, { id: 2, name: 'plex', ctid: 151 }]

vi.mock('../api/client', () => ({
  ApiError,
  api: vi.fn((path: string, opts?: RequestInit) => {
    const body = opts?.body ? JSON.parse(String(opts.body)) : null
    calls.push({ path, method: opts?.method, body })
    // Mirrors backend/proxploy/api/hosts.py::remove_host: refuses with
    // host_has_apps until forget_apps is explicitly set, regardless of a
    // correct typed confirmation.
    if (!body?.forget_apps) {
      return Promise.reject(new ApiError(409, {
        error: 'host_has_apps', apps: CONFLICT_APPS, detail: 'pve1 still has 2 app(s).',
      }))
    }
    return Promise.resolve({ removed: true, forgot_apps: CONFLICT_APPS.length, was_own_host: false })
  }),
}))

import { HostRemoveDialog } from '../components/HostRemoveDialog'

const wrap = (onRemoved = vi.fn(), onClose = vi.fn()) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  render(<QueryClientProvider client={qc}>
    <HostRemoveDialog hostId={5} hostName="pve1" onClose={onClose} onRemoved={onRemoved} />
  </QueryClientProvider>)
  return onRemoved
}

describe('HostRemoveDialog', () => {
  beforeEach(() => { calls.length = 0; notifySuccess.mockClear(); notifyError.mockClear() })
  afterEach(() => vi.restoreAllMocks())

  it('does not send forget_apps on the first submit', async () => {
    wrap()
    fireEvent.change(screen.getByLabelText(/type pve1 to confirm/i), { target: { value: 'pve1' } })
    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }))
    await waitFor(() => expect(calls.length).toBe(1))
    expect(calls[0].body).toEqual({ confirm: 'pve1', forget_apps: false })
  })

  it('shows the conflicting apps and only retries with forget_apps once the user opts in', async () => {
    const onRemoved = wrap()
    fireEvent.change(screen.getByLabelText(/type pve1 to confirm/i), { target: { value: 'pve1' } })
    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }))

    expect(await screen.findByText('pve1 still has apps')).toBeInTheDocument()
    expect(screen.getByText(/immich \(CT 150\)/)).toBeInTheDocument()
    expect(screen.getByText(/plex \(CT 151\)/)).toBeInTheDocument()

    // Not retried automatically: still exactly the one denied call so far.
    expect(calls.length).toBe(1)

    fireEvent.click(screen.getByRole('button', { name: 'Forget apps and remove' }))
    await waitFor(() => expect(calls.length).toBe(2))
    expect(calls[1].body).toEqual({ confirm: 'pve1', forget_apps: true })
    await waitFor(() => expect(onRemoved).toHaveBeenCalled())
  })

  // The gate is the whole safety mechanism for an irreversible action, and a
  // migration is exactly when something like this gets quietly dropped.
  it('blocks removal until the host name is typed exactly', async () => {
    wrap()
    const confirm = screen.getByRole('button', { name: 'Confirm' })
    expect(confirm).toBeDisabled()

    fireEvent.change(screen.getByLabelText(/type pve1 to confirm/i), { target: { value: 'pve' } })
    expect(confirm).toBeDisabled()
    fireEvent.click(confirm)
    expect(calls.length).toBe(0)

    fireEvent.change(screen.getByLabelText(/type pve1 to confirm/i), { target: { value: 'pve1' } })
    expect(confirm).toBeEnabled()
  })

  it('is a modal alertdialog that Escape closes', async () => {
    const onClose = vi.fn()
    wrap(vi.fn(), onClose)

    const panel = await screen.findByRole('alertdialog')
    expect(panel).toHaveAttribute('aria-modal', 'true')

    fireEvent.keyDown(document.activeElement ?? document.body, { key: 'Escape' })

    await waitFor(() => expect(onClose).toHaveBeenCalled())
    expect(calls.length).toBe(0)
  })

  it('keeps the conflict step in its own alertdialog rather than flattening it', async () => {
    wrap()
    fireEvent.change(screen.getByLabelText(/type pve1 to confirm/i), { target: { value: 'pve1' } })
    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }))

    expect(await screen.findByText('pve1 still has apps')).toBeInTheDocument()
    expect(screen.getByRole('alertdialog')).toHaveAttribute('aria-modal', 'true')
  })
})
