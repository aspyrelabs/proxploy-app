import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

vi.mock('../api/client', () => ({
  api: vi.fn((path: string) => {
    if (path === '/cluster/summary') {
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
    return Promise.resolve(null)
  }),
  ApiError: class extends Error {},
}))

// Router-dependent bits (Link/useNavigate) need a real router in tests; mock them thin.
vi.mock('@tanstack/react-router', async (orig) => ({
  ...(await orig() as object),
  Link: ({ children }: { children?: unknown }) => <a>{children as never}</a>,
  useNavigate: () => () => {},
}))

import { ClusterPage } from '../routes/cluster'

describe('ClusterPage', () => {
  it('renders rings, counts and node cards from the API', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={qc}><ClusterPage /></QueryClientProvider>)
    expect(await screen.findByText('host-01')).toBeInTheDocument()
    expect(screen.getByRole('img', { name: /CPU 42%/ })).toBeInTheDocument()
    expect(screen.getByText(/Activity feed lands in Phase 3/)).toBeInTheDocument()
  })
})
