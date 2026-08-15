import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const { notifyError } = vi.hoisted(() => ({ notifyError: vi.fn() }))
vi.mock('../lib/notify', () => ({ notify: { error: notifyError, success: vi.fn(), info: vi.fn(), warning: vi.fn() } }))

const { ApiError } = vi.hoisted(() => ({
  ApiError: class extends Error {
    status: number; body: unknown
    constructor(status: number, body: unknown) { super(`API ${status}`); this.status = status; this.body = body }
  },
}))

let activityResult: 'ok' | 'empty' | 'error' | 'refused' = 'ok'
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
      // Two rows that did NOT happen: a migration the backend refused
      // (write_audit result 'denied') and a delete job that blew up.
      if (activityResult === 'refused') return Promise.resolve([
        { kind: 'audit', id: 7, at: '2026-07-29T09:00:00Z', title: 'app.migrate',
          status: 'denied', target_type: 'app', target_id: 1,
          actor: 'admin@example.com', job_id: null, progress_pct: null },
        { kind: 'job', id: 14, at: '2026-07-29T08:58:00Z', title: 'vm.delete',
          status: 'failed', target_type: 'vm', target_id: 3,
          actor: 'admin@example.com', job_id: 14, progress_pct: null },
      ])
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
import { FakeEventSource, installFakeEventSource } from './fakeEventSource'

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
    notifyError.mockClear()
  })

  it('renders merged job and audit rows with their actor', async () => {
    wrap(<ActivityFeed />)
    expect(await screen.findByText('App Start')).toBeInTheDocument()
    expect(screen.getByText('Host Add')).toBeInTheDocument()
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

  // The feed prints the result underneath, but the title is what gets read,
  // and the first word of a refused row has to be the refusal, not the name of
  // the destructive thing that did not happen.
  it('does not title a refused action or a failed job as though it went through', async () => {
    activityResult = 'refused'
    wrap(<ActivityFeed />)
    // app.migrate carries the neutral "App Migrate", not doc 13's "Migration
    // Refused": that identifier is written for real migrations too, so the
    // doc's label made a success read "Migration Refused Requested" and this
    // refusal read "Blocked Migration Refused", colliding with the prefix its
    // own rule 6 forbids colliding with. The prefix carries the refusal.
    expect(await screen.findByText('Blocked App Migrate')).toBeInTheDocument()
    expect(screen.getByText('VM Delete Failed')).toBeInTheDocument()
    expect(screen.queryByText('App Migrated')).not.toBeInTheDocument()
    expect(screen.queryByText('VM Deleted')).not.toBeInTheDocument()
  })

  it('offers Cancel only on the running job row, not the succeeded job or the audit row', async () => {
    wrap(<ActivityFeed />)
    await screen.findByText('App Stop')
    expect(screen.getAllByRole('button', { name: 'Cancel' })).toHaveLength(1)
    const row = screen.getByText('App Stop').closest('div')!
    expect(within(row).getByRole('button', { name: 'Cancel' })).toBeInTheDocument()
  })

  // app.stop is 'running' with progress_pct: 40, the one row in this fixture
  // a determinate ring may honestly appear on.
  it('shows a progress ring on the running job row', async () => {
    wrap(<ActivityFeed />)
    await screen.findByText('App Stop')
    const row = screen.getByText('App Stop').closest('div')!
    expect(within(row).getByRole('status')).toHaveAttribute(
      'aria-label', expect.stringContaining('40 percent'))
  })

  // host.create is an audit row: progress_pct is null. No ring, and no zero
  // standing in for "no figure" either.
  it('shows no ring on a row with no progress figure', async () => {
    wrap(<ActivityFeed />)
    await screen.findByText('Host Add')
    const row = screen.getByText('Host Add').closest('div')!
    expect(within(row).queryByRole('status')).toBeNull()
  })

  // app.start already finished (status: succeeded) even though it carries
  // progress_pct: 100. A determinate ring is for a job still running.
  it('shows no ring on a finished job even though it carries a progress figure', async () => {
    wrap(<ActivityFeed />)
    await screen.findByText('App Start')
    const row = screen.getByText('App Start').closest('div')!
    expect(within(row).queryByRole('status')).toBeNull()
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
    await waitFor(() => expect(notifyError).toHaveBeenCalledWith('job is already succeeded'))
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

  // The enabling half of the determinate ring: JobLog owns the one
  // EventSource for a job, so a caller that wants live progress has to get
  // it through JobLog rather than opening a second connection.
  it('calls onProgress when the stream emits a progress frame', async () => {
    const restore = installFakeEventSource()
    const onProgress = vi.fn()
    wrap(<JobLog jobId={12} onProgress={onProgress} />)
    await screen.findByText('starting CT 150')

    FakeEventSource.last.emit('progress', { pct: 55 })

    expect(onProgress).toHaveBeenCalledWith(55)
    restore()
  })

  it('does not call onProgress for a line or status frame', async () => {
    const restore = installFakeEventSource()
    const onProgress = vi.fn()
    wrap(<JobLog jobId={12} onProgress={onProgress} />)
    await screen.findByText('starting CT 150')

    FakeEventSource.last.emit('line', { stream: 'stdout', message: 'hi' })
    FakeEventSource.last.emit('status', { status: 'succeeded' })

    expect(onProgress).not.toHaveBeenCalled()
    restore()
  })
})
