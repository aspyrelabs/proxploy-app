import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

// PXP-17 item 8: DELETE /vms/{id} shipped on the backend with no UI at all.
// This covers the destroy control on the VM detail page, the only place it
// is allowed to live (never a list-row action).

const { navigateSpy } = vi.hoisted(() => ({ navigateSpy: vi.fn() }))

let vmStatus: 'running' | 'stopped' = 'stopped'
let deleteOutcome: 'ok' | 'guest_running' | 'self_target' = 'ok'
const calls: { path: string; method: string; body: any }[] = []

vi.mock('../api/client', () => {
  class ApiError extends Error {
    status: number; body: unknown
    constructor(status: number, body: unknown) {
      super(`API ${status}`); this.status = status; this.body = body
    }
  }
  return {
    ApiError,
    apiErrorDetail: (e: unknown, fallback: string) => {
      if (!(e instanceof ApiError)) return fallback
      const detail = (e.body as { detail?: unknown } | null)?.detail
      const text = typeof detail === 'string' ? detail
        : typeof (detail as { detail?: unknown } | null)?.detail === 'string'
          ? (detail as { detail: string }).detail
          : undefined
      if (text == null) return fallback
      if (e.status === 502 && !text.startsWith('Proxmox')) return `Proxmox could not do this: ${text}`
      return text
    },
    api: vi.fn((path: string, opts?: RequestInit) => {
      const method = (opts?.method ?? 'GET').toUpperCase()
      const body = opts?.body ? JSON.parse(String(opts.body)) : {}
      if (path === '/entitlements') {
        return Promise.resolve({
          tier: 'builtin',
          features: { 'vms.create': true, 'vms.lifecycle': true },
          grace: null, clock_skew: false,
        })
      }
      if (method === 'GET' && path === '/vms/9') {
        return Promise.resolve({
          id: 9, host_id: 1, host_name: 'host-01', vmid: 201, name: 'win11',
          status: vmStatus, os_type: null, cpu_cores: 2, cpu_pct: 3,
          mem_bytes: 4294967296, disk_bytes: 107374182400, uptime_s: 86400,
          synced_at: null,
        })
      }
      if (path.startsWith('/jobs/')) return Promise.resolve([])
      if (method === 'DELETE' && path === '/vms/9') {
        calls.push({ path, method, body })
        if (deleteOutcome === 'guest_running') {
          return Promise.reject(new ApiError(409, {
            error: 'guest_running', detail: 'stop win11 before destroying it',
          }))
        }
        if (deleteOutcome === 'self_target') {
          return Promise.reject(new ApiError(409, {
            error: 'self_target', confirm_phrase: 'win11',
            detail: 'win11 is the guest Proxploy itself runs in.',
          }))
        }
        return Promise.resolve({ job: { id: 44, kind: 'vm.delete', status: 'queued' } })
      }
      return Promise.resolve(null)
    }),
  }
})

vi.mock('../lib/notify', () => ({ notify: { error: vi.fn(), success: vi.fn(), info: vi.fn(), warning: vi.fn() } }))
import { notify } from '../lib/notify'

vi.mock('@tanstack/react-router', async (orig) => ({
  ...(await orig() as object),
  Link: ({ children }: { children?: unknown }) => <a>{children as never}</a>,
  Outlet: () => null,
  useNavigate: () => navigateSpy,
  useParams: () => ({ vmId: '9' }),
}))

import { VmDetail } from '../routes/vms'

const wrap = () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={qc}><VmDetail /></QueryClientProvider>)
}

describe('VmDetail destroy', () => {
  beforeEach(() => {
    calls.length = 0
    vmStatus = 'stopped'
    deleteOutcome = 'ok'
    navigateSpy.mockClear()
    vi.mocked(notify.error).mockClear()
  })

  it('sends the typed VM name as confirm, then surfaces the job and navigates back on close', async () => {
    wrap()
    fireEvent.click(await screen.findByRole('button', { name: 'Destroy' }))
    expect(await screen.findByText(/deletes the VM and every disk/i)).toBeInTheDocument()

    const input = screen.getByLabelText(/type/i)
    expect(screen.getByRole('button', { name: /^confirm$/i })).toBeDisabled()
    fireEvent.change(input, { target: { value: 'win11' } })
    fireEvent.click(screen.getByRole('button', { name: /^confirm$/i }))

    await waitFor(() => expect(calls.length).toBe(1))
    expect(calls[0]).toMatchObject({ path: '/vms/9', method: 'DELETE', body: { confirm: 'win11' } })

    // The accessible name now comes from the visible heading rather than a
    // separate aria-label, so it names the actual VM instead of the generic
    // "Destroying VM".
    const progress = await screen.findByRole('dialog', { name: /destroying win11/i })
    expect(progress).toHaveAttribute('aria-modal', 'true')
    fireEvent.click(screen.getByRole('button', { name: 'Close' }))
    expect(navigateSpy).toHaveBeenCalledWith({ to: '/vms' })
  })

  it('cannot destroy a running VM from the UI, the reason is visible on the disabled control', async () => {
    vmStatus = 'running'
    wrap()
    const btn = await screen.findByRole('button', { name: 'Destroy' })
    expect(btn).toBeDisabled()
    expect(btn).toHaveAttribute('title', 'Stop win11 before destroying it')
    fireEvent.click(btn)
    expect(screen.queryByLabelText(/type/i)).toBeNull()
    expect(calls.length).toBe(0)
  })

  it('shows the guest_running 409 detail verbatim rather than a generic failure, if state raced', async () => {
    // The client-side disabled state is the primary guard; this covers the
    // backend's own refusal if the VM went running in the gap between
    // opening the dialog and confirming.
    deleteOutcome = 'guest_running'
    wrap()
    fireEvent.click(await screen.findByRole('button', { name: 'Destroy' }))
    fireEvent.change(screen.getByLabelText(/type/i), { target: { value: 'win11' } })
    fireEvent.click(screen.getByRole('button', { name: /^confirm$/i }))
    await waitFor(() => expect(calls.length).toBe(1))
    expect(notify.error).toHaveBeenCalledWith('stop win11 before destroying it')
  })

  it('states plainly that Proxploy will not destroy the guest it runs inside, on a self_target 409', async () => {
    deleteOutcome = 'self_target'
    wrap()
    fireEvent.click(await screen.findByRole('button', { name: 'Destroy' }))
    fireEvent.change(screen.getByLabelText(/type/i), { target: { value: 'win11' } })
    fireEvent.click(screen.getByRole('button', { name: /^confirm$/i }))
    await waitFor(() => expect(calls.length).toBe(1))
    expect(notify.error).toHaveBeenCalledWith('Proxploy will not destroy the guest it is running inside.')
  })
})
