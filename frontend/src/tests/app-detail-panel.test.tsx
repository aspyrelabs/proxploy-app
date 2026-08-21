import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const requested: string[] = []

vi.mock('../api/client', () => ({
  api: vi.fn((path: string) => {
    requested.push(path)
    if (path.startsWith('/metrics/query')) {
      return Promise.resolve({ target: 'app:7', metric: 'cpu_pct',
                               resolution: '5m', ts: [1, 2], value: [0.1, 0.14] })
    }
    // GuestFirewallLine reads these; the panel does not exercise them beyond
    // rendering, so a firewall that is off with no rules keeps this file's
    // assertions about the rest of the panel unaffected.
    if (path.endsWith('/firewall/options')) {
      return Promise.resolve({ scope: 'guest', digest: null, options: { enable: 0 }, defaults: {} })
    }
    if (path.endsWith('/firewall/rules')) {
      return Promise.resolve({ scope: 'guest', digest: null, rules: [] })
    }
    return Promise.resolve([])
  }),
  ApiError: class extends Error {},
}))
vi.mock('@tanstack/react-router', async (orig) => ({
  ...(await orig() as object),
  useNavigate: () => vi.fn(),
  // GuestFirewallLine renders a real Link, which needs a <RouterProvider>
  // this file never stands up; every other test mocks it thin for the same
  // reason.
  Link: ({ children }: { children?: unknown }) => <a>{children as never}</a>,
}))

import { AppDetailPanel } from '../components/AppDetailPanel'
import type { AppRow } from '../api/hooks'

const APP: AppRow = {
  id: 7, name: 'Immich', slug: 'immich', host_id: 1, host_name: 'pve-a',
  node: 'pve-a', ctid: 150, category: null, catalog_slug: 'immich',
  icon_initials: 'IM', icon_colors: null, icon_url: null,
  web_port: null, web_protocol: 'http', web_path: '/', installed_url: null,
  catalog_port: 8096,
  status: 'running', ip: '10.0.0.5', cpu_pct: 12,
  mem_bytes: 2147483648, mem_total_bytes: 4294967296, uptime_s: 86400,
  update_available: null, adopted: false,
  disk_bytes: 5368709120, disk_total_bytes: 17179869184,
  net_in_bps: 1200000, net_out_bps: 88000,
}

const wrap = (app: AppRow = APP) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}><AppDetailPanel app={app} /></QueryClientProvider>)
}

/** The metric a /metrics/query URL asks for, keyed by its target. */
const seriesFor = (target: string) => requested
  .filter((p) => p.includes(`target=${target}`))
  .map((p) => new URL(p, 'http://x').searchParams.get('metric'))

beforeEach(() => { requested.length = 0 })

describe('AppDetailPanel', () => {
  it('draws CPU and memory as real charts, the same pair the node page draws', () => {
    // Not a Sparkline: an axis-less spark cannot tell 3% from 100%, which is
    // the whole reason the host page moved off one.
    wrap()
    expect(screen.getByRole('group', { name: 'CPU time range' })).toBeInTheDocument()
    expect(screen.getByRole('group', { name: 'Memory time range' })).toBeInTheDocument()
  })

  it('charts THIS app, not the host it sits on', async () => {
    wrap()
    await waitFor(() => expect(requested.filter((p) => p.startsWith('/metrics/query')).length)
      .toBeGreaterThan(1))
    expect(seriesFor('app:7').sort()).toEqual(['cpu_pct', 'mem_pct'])
    expect(requested.some((p) => p.includes('target=host:'))).toBe(false)
  })

  it('still says whether the app is running, and for how long', () => {
    wrap()
    expect(screen.getByText(/running/i)).toBeInTheDocument()
    expect(screen.getByText(/^up /)).toBeInTheDocument()
  })

  it('keeps the absolute memory figure the percentage chart cannot give', () => {
    // fmtBytes(2147483648) = "2.0 GiB", fmtBytes(4294967296) = "4.0 GiB".
    wrap()
    expect(screen.getByText(/2\.0 GiB of 4\.0 GiB/)).toBeInTheDocument()
  })
})
