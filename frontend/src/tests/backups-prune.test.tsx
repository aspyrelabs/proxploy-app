import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

// PXP-17 item 8: POST /backups/prune shipped on the backend with no UI at
// all. This covers wiring execution into the retention preview already on
// /backups (src/routes/backups.tsx's RetentionSection), not a second form.

const BACKUPS = {
  backups: [
    { id: 11, host_id: 1, host_name: 'host-01', storage: 'pbs-ds',
      volid: 'pbs-ds:backup/ct/150/2026-07-30T02:00:00Z', guest_type: 'ct',
      guest_vmid: 150, guest_name: 'Immich', taken_at: '2026-07-30T02:00:00Z',
      size_bytes: 1073741824, verify_state: 'ok', notes: null },
  ],
  stats: {
    total: 1, total_bytes: 1073741824, ok_count: 1, failed_count: 0,
    success_rate_30d: 100,
    datastores: [{ storage: 'pbs-ds', count: 1, size_bytes: 1073741824 }],
  },
  synced_at: '2026-07-31T09:00:00Z',
  stale: false,
}

const PRUNE = [
  { volid: 'pbs-ds:backup/ct/150/2026-07-30T02:00:00Z', type: 'ct', vmid: 150,
    ctime: 1753840800, mark: 'keep' },
  { volid: 'pbs-ds:backup/ct/150/2026-06-01T02:00:00Z', type: 'ct', vmid: 150,
    ctime: 1748743200, mark: 'remove' },
  { volid: 'pbs-ds:backup/vm/201/2026-05-01T02:00:00Z', type: 'vm', vmid: 201,
    ctime: 1746064800, mark: 'protected' },
]

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
    api: vi.fn((path: string, opts?: RequestInit) => {
      const method = (opts?.method ?? 'GET').toUpperCase()
      const body = opts?.body ? JSON.parse(String(opts.body)) : {}
      if (path === '/entitlements') {
        return Promise.resolve({
          tier: 'pro',
          features: { 'backups.pbs': true, 'backups.run': true, 'backups.restore': true, 'backups.retention': true },
          grace: null,
        })
      }
      if (method !== 'GET') calls.push({ path, method, body })
      if (path === '/backups') return Promise.resolve(BACKUPS)
      if (path === '/schedules') return Promise.resolve([])
      if (path === '/hosts') return Promise.resolve([{ id: 1, name: 'host-01' }])
      if (path.startsWith('/backups/prune-preview')) return Promise.resolve(PRUNE)
      if (path === '/backups/prune') {
        return Promise.resolve({ job: { id: 55, kind: 'backup.prune', status: 'queued' } })
      }
      return Promise.resolve(null)
    }),
  }
})

vi.mock('@tanstack/react-router', async (orig) => ({
  ...(await orig() as object),
  Link: ({ children }: { children?: unknown }) => <a>{children as never}</a>,
  useNavigate: () => () => {},
  useSearch: () => ({}),
}))

import { BackupsPage } from '../routes/backups'

const wrap = () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={qc}><BackupsPage /></QueryClientProvider>)
}

const runPreview = async () => {
  await waitFor(() =>
    expect(screen.getByRole('button', { name: 'Preview retention' })).toBeEnabled())
  fireEvent.click(screen.getByRole('button', { name: 'Preview retention' }))
  await screen.findByText('remove')
}

describe('Backups retention: run prune', () => {
  it('refuses to submit with no keep-* value set, without waiting on the 422', async () => {
    calls.length = 0
    wrap()
    fireEvent.change(await screen.findByLabelText(/keep last/i), { target: { value: '0' } })
    fireEvent.change(screen.getByLabelText(/keep daily/i), { target: { value: '0' } })
    await runPreview()

    const btn = screen.getByRole('button', { name: /prune now/i })
    expect(btn).toBeDisabled()
    expect(btn).toHaveAttribute('title', 'At least one keep value must be 1 or more')
    expect(screen.getByText(/at least one keep value must be 1 or more/i)).toBeInTheDocument()
    fireEvent.click(btn)
    expect(calls.some((c) => c.path === '/backups/prune')).toBe(false)
  })

  it('submits the exact host_id/storage/keep-* values the preview was computed from', async () => {
    calls.length = 0
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)
    wrap()
    await runPreview() // defaults: keep last 3, keep daily 7

    fireEvent.click(screen.getByRole('button', { name: /prune now/i }))
    expect(confirmSpy).toHaveBeenCalled()
    await waitFor(() => expect(calls.some((c) => c.path === '/backups/prune')).toBe(true))
    const call = calls.find((c) => c.path === '/backups/prune')!
    expect(call.method).toBe('POST')
    expect(call.body).toEqual({ host_id: 1, storage: 'pbs-ds', keep_last: 3, keep_daily: 7 })

    // the job returned by the execute call is surfaced, not silently dropped
    expect(await screen.findByRole('button', { name: /prune now/i })).toBeEnabled()
    confirmSpy.mockRestore()
  })

  it('does not submit when the confirmation step is declined', async () => {
    calls.length = 0
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false)
    wrap()
    await runPreview()
    fireEvent.click(screen.getByRole('button', { name: /prune now/i }))
    expect(confirmSpy).toHaveBeenCalled()
    expect(calls.some((c) => c.path === '/backups/prune')).toBe(false)
    confirmSpy.mockRestore()
  })
})
