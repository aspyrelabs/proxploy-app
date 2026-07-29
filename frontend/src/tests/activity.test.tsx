import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

vi.mock('../api/client', () => ({
  api: vi.fn((path: string) => {
    if (path.startsWith('/jobs/12/events')) {
      return Promise.resolve([
        { seq: 1, ts: '2026-07-29T09:00:00Z', stream: 'stdout', message: 'starting CT 150' },
        { seq: 2, ts: '2026-07-29T09:00:04Z', stream: 'status', message: 'succeeded: ok' },
      ])
    }
    if (path.startsWith('/jobs')) {
      return Promise.resolve([
        { id: 12, kind: 'app.start', status: 'succeeded', target_type: 'app',
          target_id: 1, progress_pct: 100, error: null, created_at: '2026-07-29T09:00:00Z' },
        { id: 13, kind: 'vm.stop', status: 'running', target_type: 'vm',
          target_id: 2, progress_pct: 40, error: null, created_at: '2026-07-29T09:01:00Z' },
      ])
    }
    if (path.startsWith('/cluster/activity')) {
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
  it('lists jobs newest-first with their status', async () => {
    wrap(<ActivityDrawer />)
    expect(await screen.findByText('vm.stop')).toBeInTheDocument()
    expect(screen.getByText('app.start')).toBeInTheDocument()
    const rows = screen.getAllByTestId('drawer-job')
    expect(rows[0]).toHaveTextContent('vm.stop')
  })
})

describe('ActivityFeed', () => {
  it('renders merged job and audit rows with their actor', async () => {
    wrap(<ActivityFeed />)
    expect(await screen.findByText('app.start')).toBeInTheDocument()
    expect(screen.getByText('host.create')).toBeInTheDocument()
    expect(screen.getAllByText(/admin@example.com/).length).toBe(2)
  })
})
