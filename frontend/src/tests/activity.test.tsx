import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const { toastError } = vi.hoisted(() => ({ toastError: vi.fn() }))
vi.mock('sonner', () => ({ toast: { error: toastError, success: vi.fn() } }))

const { ApiError } = vi.hoisted(() => ({
  ApiError: class extends Error {
    status: number; body: unknown
    constructor(status: number, body: unknown) { super(`API ${status}`); this.status = status; this.body = body }
  },
}))

let activityResult: 'ok' | 'empty' | 'error' = 'ok'
let jobEventsError = false
let cancelResult: 'ok' | 'forbidden' | 'conflict' = 'ok'
const cancelCalls: Array<{ path: string; method?: string }> = []

vi.mock('../api/client', () => ({
  ApiError,
  api: vi.fn((path: string, opts?: RequestInit) => {
    const method = opts?.method
    if (path.startsWith('/jobs/') && path.endsWith('/cancel') && method === 'POST') {
      cancelCalls.push({ path, method })
      if (cancelResult === 'forbidden') return Promise.reject(new ApiError(403, { detail: 'forbidden' }))
      if (cancelResult === 'conflict') return Promise.reject(new ApiError(409, { detail: 'job is already succeeded' }))
      return Promise.resolve({ id: 13, status: 'canceled' })
    }
    if (path.startsWith('/jobs/12/events')) {
      if (jobEventsError) return Promise.reject(new Error('boom'))
      return Promise.resolve([
        { seq: 1, ts: '2026-07-29T09:00:00Z', stream: 'stdout', message: 'starting CT 150' },
        { seq: 2, ts: '2026-07-29T09:00:04Z', stream: 'status', message: 'succeeded: ok' },
      ])
    }
    if (path.startsWith('/cluster/activity')) {
      if (activityResult === 'error') return Promise.reject(new Error('boom'))
      if (activityResult === 'empty') return Promise.resolve([])
      return Promise.resolve([
        { kind: 'job', id: 12, at: '2026-07-29T09:00:00Z', title: 'app.start',
          status: 'succeeded', target_type: 'app', target_id: 1,
          actor: 'admin@example.com', job_id: 12, progress_pct: 100 },
        { kind: 'audit', id: 4, at: '2026-07-29T08:59:00Z', title: 'host.create',
          status: 'ok', target_type: 'host', target_id: 1,
          actor: 'admin@example.com', job_id: null, progress_pct: null },
        { kind: 'job', id: 13, at: '2026-07-29T09:01:00Z', title: 'app.stop',
          status: 'running', target_type: 'app', target_id: 2,
          actor: 'ops@example.com', job_id: 13, progress_pct: 40 },
      ])
    }
    if (path === '/entitlements') {
      return Promise.resolve({ tier: 'builtin', features: {}, grace: null, clock_skew: false })
    }
    return Promise.resolve(null)
  }),
}))

import { ActivityFeed } from '../components/ActivityFeed'
import { JobLog } from '../components/JobLog'
import { TerminalPanel } from '../components/TerminalPanel'

const wrap = (ui: React.ReactNode) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

describe('TerminalPanel', () => {
  it('renders each line and tags the stream', () => {
    wrap(<TerminalPanel lines={[
      { stream: 'stdout', message: 'starting CT 150' },
      { stream: 'stderr', message: 'warning: low disk' },
    ]} />)
    expect(screen.getByText('starting CT 150')).toBeInTheDocument()
    expect(screen.getByText('warning: low disk')).toBeInTheDocument()
  })

  it('shows an honest empty state instead of a blank box', () => {
    wrap(<TerminalPanel lines={[]} />)
    expect(screen.getByText(/no output yet/i)).toBeInTheDocument()
  })
})

describe('ActivityFeed', () => {
  beforeEach(() => {
    activityResult = 'ok'
    cancelResult = 'ok'
    cancelCalls.length = 0
    toastError.mockClear()
  })

  it('renders merged job and audit rows with their actor', async () => {
    wrap(<ActivityFeed />)
    expect(await screen.findByText('app.start')).toBeInTheDocument()
    expect(screen.getByText('host.create')).toBeInTheDocument()
    expect(screen.getAllByText(/admin@example.com/).length).toBe(2)
  })

  it('says activity could not be read rather than showing "nothing has happened yet"', async () => {
    activityResult = 'error'
    wrap(<ActivityFeed />)
    expect(await screen.findByText(/activity not readable/i)).toBeInTheDocument()
    expect(screen.queryByText('Nothing has happened yet.')).not.toBeInTheDocument()
  })

  it('shows the real empty-activity copy when there genuinely is none', async () => {
    activityResult = 'empty'
    wrap(<ActivityFeed />)
    expect(await screen.findByText('Nothing has happened yet.')).toBeInTheDocument()
  })

  it('offers Cancel only on the running job row, not the succeeded job or the audit row', async () => {
    wrap(<ActivityFeed />)
    await screen.findByText('app.stop')
    expect(screen.getAllByRole('button', { name: 'Cancel' })).toHaveLength(1)
    const row = screen.getByText('app.stop').closest('div')!
    expect(within(row).getByRole('button', { name: 'Cancel' })).toBeInTheDocument()
  })

  it('pressing Cancel posts to /jobs/{id}/cancel for that row', async () => {
    wrap(<ActivityFeed />)
    fireEvent.click(await screen.findByRole('button', { name: 'Cancel' }))
    await waitFor(() => expect(cancelCalls.some(
      (c) => c.path === '/jobs/13/cancel' && c.method === 'POST')).toBe(true))
  })

  it('a rejected cancel surfaces an error toast rather than failing silently', async () => {
    cancelResult = 'conflict'
    wrap(<ActivityFeed />)
    fireEvent.click(await screen.findByRole('button', { name: 'Cancel' }))
    await waitFor(() => expect(toastError).toHaveBeenCalledWith('job is already succeeded'))
  })
})

describe('JobLog', () => {
  beforeEach(() => { jobEventsError = false })

  it('renders the archived transcript', async () => {
    wrap(<JobLog jobId={12} />)
    expect(await screen.findByText('starting CT 150')).toBeInTheDocument()
  })

  it('says the transcript could not be loaded rather than showing "no output yet"', async () => {
    // TerminalPanel stays dark by design (doc 06 §c) so this isn't a
    // QueryState card, it's a distinct line inside the same terminal box,
    // but it still must not look like a job that legitimately produced
    // nothing.
    jobEventsError = true
    wrap(<JobLog jobId={12} />)
    expect(await screen.findByText(/could not load this job.s transcript/i)).toBeInTheDocument()
    expect(screen.queryByText(/no output yet/i)).not.toBeInTheDocument()
  })
})
