import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

let nodesResult: 'ok' | 'empty' | 'error' = 'ok'
let summaryResult: 'ok' | 'error' = 'ok'

vi.mock('../api/client', () => ({
  api: vi.fn((path: string) => {
    if (path === '/cluster/nodes' && nodesResult !== 'ok') {
      if (nodesResult === 'error') return Promise.reject(new Error('boom'))
      return Promise.resolve([])
    }
    if (path === '/cluster/summary') {
      if (summaryResult === 'error') return Promise.reject(new Error('boom'))
      return Promise.resolve({
        updated_at: '2026-07-29T00:00:00Z',
        cpu: { pct: 42, used_cores: 3.4, total_cores: 8 },
        mem: { pct: 41, used_bytes: 137, total_bytes: 338 },
        storage: { pct: 21, used_bytes: 1, total_bytes: 4 },
        net: { in_bps: 1300000, out_bps: 5000000 },
        counts: { hosts: 1, hosts_online: 1, nodes: 1, apps: 1, apps_running: 1, vms: 1, vms_running: 1 },
      })
    }
    if (path === '/cluster/nodes') {
      return Promise.resolve([{
        host_id: 1, name: 'host-01', node: 'pve1', status: 'connected',
        cluster: null, pve_version: '8.4.1', cpu_pct: 42, mem_pct: 41,
        mem_bytes: 137, mem_total_bytes: 338, uptime_s: 864000,
        apps: 1, apps_running: 1, vms: 1, vms_running: 1, last_seen_at: null,
      }])
    }
    if (path.startsWith('/apps')) return Promise.resolve([])
    if (path.startsWith('/vms')) return Promise.resolve([])
    if (path.startsWith('/hosts')) return Promise.resolve([])
    if (path.startsWith('/metrics/query')) {
      return Promise.resolve({ target: 'host:1', metric: 'net_in_bps', resolution: 'raw', ts: [], value: [] })
    }
    if (path.startsWith('/cluster/activity')) return Promise.resolve([])
    return Promise.resolve(null)
  }),
  ApiError: class extends Error {},
}))

// Router-dependent bits (Link/useNavigate) need a real router in tests; mock them thin.
vi.mock('@tanstack/react-router', async (orig) => ({
  ...(await orig() as object),
  Link: ({ children }: { children?: unknown }) => <a>{children as never}</a>,
  useNavigate: () => () => {},
  useSearch: () => ({}),
}))

import { ClusterPage } from '../routes/cluster'

const withQuery = (ui: React.ReactNode) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

describe('ClusterPage', () => {
  beforeEach(() => { nodesResult = 'ok'; summaryResult = 'ok' })

  it('renders rings, counts and node cards from the API', async () => {
    withQuery(<ClusterPage />)
    expect(await screen.findByText('host-01')).toBeInTheDocument()
    expect(screen.getByRole('img', { name: /CPU 42%/ })).toBeInTheDocument()
    expect(screen.getByText(/Nothing has happened yet/)).toBeInTheDocument()
  })

  it('says the nodes could not be read rather than showing "no nodes yet"', async () => {
    // The bug this task exists to fix: a failed fetch used to render as a
    // bare, message-less <div>; indistinguishable from a fresh install
    // with zero hosts.
    nodesResult = 'error'
    withQuery(<ClusterPage />)
    expect(await screen.findByText(/nodes not readable/i)).toBeInTheDocument()
    expect(screen.queryByText('No nodes yet')).not.toBeInTheDocument()
  })

  it('tells a fresh install there are no nodes yet, not nothing at all', async () => {
    nodesResult = 'empty'
    withQuery(<ClusterPage />)
    expect(await screen.findByText('No nodes yet')).toBeInTheDocument()
    expect(screen.queryByText(/nodes not readable/i)).not.toBeInTheDocument()
  })

  it('shows the rings as unknown rather than a calm 0% when the summary fetch fails', async () => {
    // The bug: pct ?? 0 used to draw a real-looking 0%-used gauge on a
    // failed fetch, indistinguishable from an actually idle cluster.
    summaryResult = 'error'
    withQuery(<ClusterPage />)
    expect(await screen.findByRole('img', { name: /CPU unknown/i })).toBeInTheDocument()
    expect(screen.getByRole('img', { name: /Memory unknown/i })).toBeInTheDocument()
    expect(screen.getByRole('img', { name: /Storage unknown/i })).toBeInTheDocument()
    expect(screen.queryByRole('img', { name: /CPU 0%/i })).not.toBeInTheDocument()
  })
})
