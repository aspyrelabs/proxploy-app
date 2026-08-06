import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

let jobsResult: 'ok' | 'empty' | 'error' = 'ok'
let activityResult: 'ok' | 'empty' | 'error' = 'ok'
let jobEventsError = false

vi.mock('../api/client', () => ({
  api: vi.fn((path: string) => {
    if (path.startsWith('/jobs/12/events')) {
      if (jobEventsError) return Promise.reject(new Error('boom'))
      return Promise.resolve([
        { seq: 1, ts: '2026-07-29T09:00:00Z', stream: 'stdout', message: 'starting CT 150' },
        { seq: 2, ts: '2026-07-29T09:00:04Z', stream: 'status', message: 'succeeded: ok' },
      ])
    }
    if (path.startsWith('/jobs')) {
      if (jobsResult === 'error') return Promise.reject(new Error('boom'))
      if (jobsResult === 'empty') return Promise.resolve([])
      // Realistic GET /jobs order: newest-first, exactly as the server
      // returns it — the drawer must not need to re-sort this itself.
      return Promise.resolve([
        { id: 13, kind: 'vm.stop', status: 'running', target_type: 'vm',
          target_id: 2, progress_pct: 40, error: null, created_at: '2026-07-29T09:01:00Z' },
        { id: 12, kind: 'app.start', status: 'succeeded', target_type: 'app',
          target_id: 1, progress_pct: 100, error: null, created_at: '2026-07-29T09:00:00Z' },
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
      ])
    }
    if (path === '/entitlements') {
      return Promise.resolve({ tier: 'builtin', features: {}, grace: null })
    }
    return Promise.resolve(null)
  }),
  ApiError: class extends Error {},
}))

const search = { drawer: 'activity' as const, job: undefined }
vi.mock('@tanstack/react-router', async (orig) => ({
  ...(await orig() as object),
  useSearch: () => search,
  useNavigate: () => () => {},
  Link: ({ children }: { children?: unknown }) => <a>{children as never}</a>,
}))

import { ActivityDrawer } from '../components/ActivityDrawer'
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

describe('ActivityDrawer', () => {
  beforeEach(() => { jobsResult = 'ok' })

  it('lists jobs newest-first with their status', async () => {
    wrap(<ActivityDrawer />)
    expect(await screen.findByText('vm.stop')).toBeInTheDocument()
    expect(screen.getByText('app.start')).toBeInTheDocument()
    const rows = screen.getAllByTestId('drawer-job')
    expect(rows[0]).toHaveTextContent('vm.stop')
  })

  it('says activity could not be read rather than showing "no jobs yet"', async () => {
    jobsResult = 'error'
    wrap(<ActivityDrawer />)
    expect(await screen.findByText(/activity not readable/i)).toBeInTheDocument()
    expect(screen.queryByText('No jobs yet.')).not.toBeInTheDocument()
  })

  it('shows the real empty-jobs copy when there genuinely are none', async () => {
    jobsResult = 'empty'
    wrap(<ActivityDrawer />)
    expect(await screen.findByText('No jobs yet.')).toBeInTheDocument()
  })
})

describe('ActivityFeed', () => {
  beforeEach(() => { activityResult = 'ok' })

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
})

describe('JobLog', () => {
  beforeEach(() => { jobEventsError = false })

  it('renders the archived transcript', async () => {
    wrap(<JobLog jobId={12} />)
    expect(await screen.findByText('starting CT 150')).toBeInTheDocument()
  })

  it('says the transcript could not be loaded rather than showing "no output yet"', async () => {
    // TerminalPanel stays dark by design (doc 06 §c) so this isn't a
    // QueryState card — it's a distinct line inside the same terminal box,
    // but it still must not look like a job that legitimately produced
    // nothing.
    jobEventsError = true
    wrap(<JobLog jobId={12} />)
    expect(await screen.findByText(/could not load this job.s transcript/i)).toBeInTheDocument()
    expect(screen.queryByText(/no output yet/i)).not.toBeInTheDocument()
  })
})
