import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

let nodesResult: 'ok' | 'empty' | 'error' | 'cluster' = 'ok'
let summaryResult: 'ok' | 'error' = 'ok'
let features: Record<string, boolean> = {}

const node = (over: Record<string, unknown> = {}) => ({
  host_id: 1, name: 'host-01', node: 'pve1', status: 'connected',
  cluster: null, is_entry: true, pve_version: '8.4.1', cpu_pct: 42, mem_pct: 41,
  mem_bytes: 137, mem_total_bytes: 338, uptime_s: 864000,
  apps: 1, apps_running: 1, vms: 1, vms_running: 1, last_seen_at: null,
  ...over,
})

vi.mock('../api/client', () => ({
  api: vi.fn((path: string) => {
    if (path === '/cluster/nodes' && (nodesResult === 'empty' || nodesResult === 'error')) {
      if (nodesResult === 'error') return Promise.reject(new Error('boom'))
      return Promise.resolve([])
    }
    if (path === '/entitlements') {
      return Promise.resolve({ tier: 'pro', features, grace: null, clock_skew: false })
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
      if (nodesResult === 'cluster') {
        return Promise.resolve([
          node({ node: 'pve1', cluster: 'prod', is_entry: false }),
          node({ node: 'pve2', cluster: 'prod', is_entry: true }),
          node({ node: 'pve3', cluster: 'prod', is_entry: false, status: 'unreachable' }),
          node({ host_id: 2, name: 'host-02', node: 'lab', cluster: null }),
        ])
      }
      return Promise.resolve([node()])
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

// Router-dependent bits (Link/useNavigate) need a real router in tests; mock them
// thin, but keep `to`/`params`/`search` and the click handler observable: the
// node segment in a NodeCard's link and the card's own destination are exactly
// what several of these tests are about.
const { navigate } = vi.hoisted(() => ({ navigate: vi.fn() }))
vi.mock('@tanstack/react-router', async (orig) => ({
  ...(await orig() as object),
  Link: ({ to, params, search, children, onClick }: {
    to?: unknown; params?: unknown; search?: unknown
    children?: unknown; onClick?: (e: React.MouseEvent) => void
  }) => (
    <a data-to={String(to)} data-params={JSON.stringify(params ?? {})}
      data-search={JSON.stringify(search ?? {})} onClick={onClick}>{children as never}</a>
  ),
  useNavigate: () => navigate,
  useSearch: () => ({}),
}))

import { HostsPage } from '../routes/hosts'

const withQuery = (ui: React.ReactNode) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

describe('HostsPage', () => {
  beforeEach(() => {
    nodesResult = 'ok'; summaryResult = 'ok'; features = {}; navigate.mockClear()
  })

  it('renders rings, counts and node cards from the API', async () => {
    withQuery(<HostsPage />)
    expect(await screen.findByText('host-01')).toBeInTheDocument()
    expect(screen.getByRole('img', { name: /CPU 42%/ })).toBeInTheDocument()
    expect(screen.getByText(/Nothing has happened yet/)).toBeInTheDocument()
  })

  it('says the nodes could not be read rather than showing "no nodes yet"', async () => {
    // The bug this task exists to fix: a failed fetch used to render as a
    // bare, message-less <div>; indistinguishable from a fresh install
    // with zero hosts.
    nodesResult = 'error'
    withQuery(<HostsPage />)
    expect(await screen.findByText(/nodes not readable/i)).toBeInTheDocument()
    expect(screen.queryByText('No nodes yet')).not.toBeInTheDocument()
  })

  it('tells a fresh install there are no nodes yet, not nothing at all', async () => {
    nodesResult = 'empty'
    withQuery(<HostsPage />)
    expect(await screen.findByText('No nodes yet')).toBeInTheDocument()
    expect(screen.queryByText(/nodes not readable/i)).not.toBeInTheDocument()
  })

  it('shows the rings as unknown rather than a calm 0% when the summary fetch fails', async () => {
    // The bug: pct ?? 0 used to draw a real-looking 0%-used gauge on a
    // failed fetch, indistinguishable from an actually idle cluster.
    summaryResult = 'error'
    withQuery(<HostsPage />)
    expect(await screen.findByRole('img', { name: /CPU unknown/i })).toBeInTheDocument()
    expect(screen.getByRole('img', { name: /Memory unknown/i })).toBeInTheDocument()
    expect(screen.getByRole('img', { name: /Storage unknown/i })).toBeInTheDocument()
    expect(screen.queryByRole('img', { name: /CPU 0%/i })).not.toBeInTheDocument()
  })

  it('groups cluster nodes under the cluster name, with its aggregate health', async () => {
    nodesResult = 'cluster'
    withQuery(<HostsPage />)
    expect(await screen.findByRole('heading', { name: 'prod' })).toBeInTheDocument()
    // one card per node, not one per host
    expect(screen.getByText('pve1')).toBeInTheDocument()
    expect(screen.getByText('pve2')).toBeInTheDocument()
    expect(screen.getByText('pve3')).toBeInTheDocument()
    // and the group says how the cluster as a whole is doing
    expect(screen.getByText(/3 nodes · 1 unreachable/i)).toBeInTheDocument()
  })

  it('leaves a standalone host ungrouped, with no cluster heading', async () => {
    nodesResult = 'cluster'
    withQuery(<HostsPage />)
    expect(await screen.findByText('lab')).toBeInTheDocument()
    // 'prod' is the only heading; the standalone host gets none
    expect(screen.queryByRole('heading', { name: 'host-02' })).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: /standalone/i })).not.toBeInTheDocument()
  })

  it('reveals the host form inline when Add host is clicked', async () => {
    features = { 'hosts.multi': true }
    withQuery(<HostsPage />)
    const add = await screen.findByRole('button', { name: 'Add host' })
    expect(screen.queryByLabelText('API token id')).not.toBeInTheDocument()
    fireEvent.click(add)
    expect(await screen.findByLabelText('API token id')).toBeInTheDocument()
  })

  it('explains the multi-host plan instead of dropping an entitlement 403 on the operator', async () => {
    // POST /hosts answers 403 {"error":"entitlement_required","feature":
    // "hosts.multi"} once one host exists. A raw error at the end of a filled
    // in form is the worst place to learn that.
    features = {}
    withQuery(<HostsPage />)
    fireEvent.click(await screen.findByRole('button', { name: 'Add host' }))
    expect(await screen.findByText(/needs the multi-host plan/i)).toBeInTheDocument()
    expect(screen.queryByLabelText('API token id')).not.toBeInTheDocument()
  })
})

describe('NodeCard', () => {
  beforeEach(() => {
    nodesResult = 'ok'; summaryResult = 'ok'; features = {}; navigate.mockClear()
  })

  it('links to the node, not just the host: a host can have many nodes', async () => {
    nodesResult = 'cluster'
    withQuery(<HostsPage />)
    const card = (await screen.findByText('pve3')).closest('[role="link"]')!
    const link = card.querySelector('a')!
    expect(link.getAttribute('data-to')).toBe('/hosts/$hostId/$node')
    expect(JSON.parse(link.getAttribute('data-params')!))
      .toEqual({ hostId: '1', node: 'pve3' })
  })

  it('opens the node when the card body is clicked, like every other card', async () => {
    // It used to navigate to /apps, the only card in the product that opened
    // something other than the thing it depicts.
    withQuery(<HostsPage />)
    const card = (await screen.findByText('host-01')).closest('[role="link"]')!
    fireEvent.click(card)
    expect(navigate).toHaveBeenCalledWith(expect.objectContaining({
      to: '/hosts/$hostId/$node', params: { hostId: '1', node: 'pve1' },
    }))
  })

  it('is reachable from the keyboard', async () => {
    withQuery(<HostsPage />)
    await screen.findByText('host-01')
    fireEvent.keyDown(screen.getByRole('link', { name: /host-01/ }), { key: 'Enter' })
    expect(navigate).toHaveBeenCalledWith(expect.objectContaining({
      to: '/hosts/$hostId/$node',
    }))
  })

  it('keeps the apps filter as its own affordance, and does not open the node with it', async () => {
    withQuery(<HostsPage />)
    const apps = (await screen.findByText('1 Apps')).closest('a')!
    expect(apps.getAttribute('data-to')).toBe('/apps')
    expect(JSON.parse(apps.getAttribute('data-search')!)).toEqual({ host: 1 })
    fireEvent.click(apps)
    expect(navigate).not.toHaveBeenCalled()
  })
})
