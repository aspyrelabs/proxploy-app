/** The activity drawer was deleted in favour of toasts, but that also deleted
 *  the only UI path to an arbitrary job's log and its error text. This is
 *  the replacement: a popover anchored to the topbar bell, reading /jobs
 *  (not /cluster/activity, whose ActivityRow has no `error` field). */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { JobRow } from '../api/jobs'

const { toastError } = vi.hoisted(() => ({ toastError: vi.fn() }))
vi.mock('sonner', () => ({ toast: { error: toastError, success: vi.fn() } }))

const { ApiError } = vi.hoisted(() => ({
  ApiError: class extends Error {
    status: number; body: unknown
    constructor(status: number, body: unknown) { super(`API ${status}`); this.status = status; this.body = body }
  },
}))

const JOBS: JobRow[] = [
  {
    id: 10, kind: 'app.start', status: 'running', target_type: 'app', target_id: 1,
    params: null, result: null, error: null, progress_pct: 40,
    requested_by: null, schedule_id: null, started_at: '2026-08-12T08:59:00Z',
    finished_at: null, created_at: '2026-08-12T08:59:00Z',
  },
  {
    id: 11, kind: 'app.stop', status: 'succeeded', target_type: 'app', target_id: 2,
    params: null, result: null, error: null, progress_pct: 100,
    requested_by: null, schedule_id: null, started_at: '2026-08-12T08:00:00Z',
    finished_at: '2026-08-12T08:01:00Z', created_at: '2026-08-12T08:00:00Z',
  },
  {
    id: 12, kind: 'vm.backup', status: 'failed', target_type: 'vm', target_id: 3,
    params: null, result: null, error: 'disk full: retry failed', progress_pct: null,
    requested_by: null, schedule_id: null, started_at: '2026-08-12T07:00:00Z',
    finished_at: '2026-08-12T07:05:00Z', created_at: '2026-08-12T07:00:00Z',
  },
]

let jobsResult: 'ok' | 'empty' | 'error' = 'ok'
let cancelResult: 'ok' | 'forbidden' | 'conflict' = 'ok'
let jobEventsError = false
const cancelCalls: Array<{ path: string; method?: string }> = []

vi.mock('../api/client', () => ({
  ApiError,
  api: vi.fn((path: string, opts?: RequestInit) => {
    const method = opts?.method
    if (path.startsWith('/jobs/') && path.endsWith('/cancel') && method === 'POST') {
      cancelCalls.push({ path, method })
      if (cancelResult === 'forbidden') return Promise.reject(new ApiError(403, { detail: 'forbidden' }))
      if (cancelResult === 'conflict') return Promise.reject(new ApiError(409, { detail: 'job is already succeeded' }))
      return Promise.resolve({ id: 10, status: 'canceled' })
    }
    if (path === '/jobs/12/events') {
      if (jobEventsError) return Promise.reject(new Error('boom'))
      return Promise.resolve([{ seq: 1, ts: '2026-08-12T07:00:01Z', stream: 'stderr', message: 'reading superblock' }])
    }
    if (path === '/jobs/10/events') {
      return Promise.resolve([{ seq: 1, ts: '2026-08-12T08:59:01Z', stream: 'stdout', message: 'copying rootfs' }])
    }
    if (path === '/jobs?status=running') {
      return Promise.resolve(JOBS.filter((j) => j.status === 'running'))
    }
    if (path === '/jobs') {
      if (jobsResult === 'error') return Promise.reject(new Error('boom'))
      if (jobsResult === 'empty') return Promise.resolve([])
      return Promise.resolve(JOBS)
    }
    return Promise.resolve(null)
  }),
}))

import { BellPopover } from '../components/BellPopover'

const wrap = () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}><BellPopover /></QueryClientProvider>)
}

const openBell = async () => {
  const trigger = await screen.findByRole('button', { name: 'Activity' })
  fireEvent.click(trigger)
  return trigger
}

describe('BellPopover', () => {
  beforeEach(() => {
    jobsResult = 'ok'
    cancelResult = 'ok'
    jobEventsError = false
    cancelCalls.length = 0
    toastError.mockClear()
  })

  it('still shows the running-job count badge on the bell', async () => {
    wrap()
    expect(await screen.findByText('1')).toBeInTheDocument()
  })

  it('opens from the bell and lists recent jobs', async () => {
    wrap()
    await openBell()
    expect(await screen.findByText(/app\.start/)).toBeInTheDocument()
    expect(screen.getByText(/app\.stop/)).toBeInTheDocument()
    expect(screen.getByText(/vm\.backup/)).toBeInTheDocument()
  })

  it('says jobs could not be read rather than showing an empty list', async () => {
    jobsResult = 'error'
    wrap()
    await openBell()
    expect(await screen.findByText(/activity not readable/i)).toBeInTheDocument()
  })

  it('shows the real empty copy when there genuinely are no jobs', async () => {
    jobsResult = 'empty'
    wrap()
    await openBell()
    expect(await screen.findByText(/no jobs yet/i)).toBeInTheDocument()
  })

  it('offers Cancel on the running job but not on the succeeded one', async () => {
    wrap()
    await openBell()
    await screen.findByText(/app\.start/)
    expect(screen.getAllByRole('button', { name: 'Cancel' })).toHaveLength(1)
    const runningRow = screen.getByText(/app\.start/).closest('[data-testid="bell-job"]')!
    expect(within(runningRow as HTMLElement).getByRole('button', { name: 'Cancel' })).toBeInTheDocument()
  })

  it('pressing Cancel posts to /jobs/{id}/cancel for that row', async () => {
    wrap()
    await openBell()
    fireEvent.click(await screen.findByRole('button', { name: 'Cancel' }))
    await waitFor(() => expect(cancelCalls.some(
      (c) => c.path === '/jobs/10/cancel' && c.method === 'POST')).toBe(true))
  })

  it('a rejected cancel surfaces an error toast with the API detail', async () => {
    cancelResult = 'conflict'
    wrap()
    await openBell()
    fireEvent.click(await screen.findByRole('button', { name: 'Cancel' }))
    await waitFor(() => expect(toastError).toHaveBeenCalledWith('job is already succeeded'))
  })

  it("shows a failed job's error text in place", async () => {
    wrap()
    await openBell()
    expect(await screen.findByText('disk full: retry failed')).toBeInTheDocument()
  })

  it('expanding a row mounts the log for that job id, and only one row expands at a time', async () => {
    wrap()
    await openBell()
    const failedRow = (await screen.findByText(/vm\.backup/)).closest('[data-testid="bell-job"]')!
    fireEvent.click(within(failedRow as HTMLElement).getByText(/vm\.backup/))
    expect(await screen.findByText('reading superblock')).toBeInTheDocument()

    const runningRow = screen.getByText(/app\.start/).closest('[data-testid="bell-job"]')!
    fireEvent.click(within(runningRow as HTMLElement).getByText(/app\.start/))
    expect(await screen.findByText('copying rootfs')).toBeInTheDocument()
    expect(screen.queryByText('reading superblock')).not.toBeInTheDocument()
  })

  it('closes on Escape', async () => {
    wrap()
    await openBell()
    await screen.findByText(/app\.start/)
    fireEvent.keyDown(document, { key: 'Escape' })
    await waitFor(() => expect(screen.queryByText(/app\.start/)).not.toBeInTheDocument())
  })

  it('closes on an outside click', async () => {
    wrap()
    await openBell()
    await screen.findByText(/app\.start/)
    // Radix's DismissableLayer defers a left-button pointerdown outside until
    // the matching click fires (so a drag-selection that starts outside and
    // ends inside doesn't dismiss the layer) — both events are needed here.
    fireEvent.pointerDown(document.body, { button: 0 })
    fireEvent.click(document.body)
    await waitFor(() => expect(screen.queryByText(/app\.start/)).not.toBeInTheDocument())
  })
})
