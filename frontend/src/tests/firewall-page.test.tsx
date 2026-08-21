import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

// Rows shaped like NodeRow (api/hooks.ts), not the Host shape the original
// brief assumed: the real source for /firewall is GET /cluster/nodes, and
// grouping is by `cluster`, mirroring routes/hosts.tsx's groupByCluster.
const NODES = [
  { host_id: 1, name: 'host-01', node: 'pve1', status: 'connected', is_entry: true,
    cluster: 'lab', pve_version: '9.2.11', cpu_pct: null, mem_pct: null,
    mem_bytes: null, mem_total_bytes: null, disk_pct: null, disk_bytes: null,
    disk_total_bytes: null, uptime_s: null, apps: 0, apps_running: 0, vms: 0,
    vms_running: 0, last_seen_at: null },
  // Same cluster, second Host's node: the page must show one cluster
  // firewall, not two.
  { host_id: 2, name: 'host-02', node: 'pve2', status: 'connected', is_entry: true,
    cluster: 'lab', pve_version: '9.2.11', cpu_pct: null, mem_pct: null,
    mem_bytes: null, mem_total_bytes: null, disk_pct: null, disk_bytes: null,
    disk_total_bytes: null, uptime_s: null, apps: 0, apps_running: 0, vms: 0,
    vms_running: 0, last_seen_at: null },
]

let ME: any = { id: 1, email: 'a@b.c', display_name: null, role: 'admin' }

vi.mock('../api/client', () => ({
  ApiError: class extends Error {},
  api: vi.fn((path: string) => {
    if (path === '/auth/me') return Promise.resolve(ME)
    if (path === '/entitlements') {
      return Promise.resolve({
        tier: 'builtin', grace: null, clock_skew: false,
        features: { 'firewall.view': true, 'firewall.rules': true,
                    'firewall.options': true, 'firewall.objects': true,
                    'firewall.log': true },
      })
    }
    if (path === '/cluster/nodes') return Promise.resolve(NODES)
    if (path.endsWith('/options')) {
      return Promise.resolve({ scope: 'cluster', digest: null, options: {},
                               defaults: { policy_in: 'DROP' } })
    }
    return Promise.resolve({ rules: [], aliases: [], ipsets: [], groups: [],
                             refs: [], macros: [], members: [], lines: [],
                             digest: null })
  }),
}))

import { FirewallClusterPage, canEditFirewall } from '../routes/firewall'

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

describe('canEditFirewall', () => {
  it('needs admin for cluster, node and group scope', () => {
    expect(canEditFirewall('admin', 'cluster')).toBe(true)
    expect(canEditFirewall('operator', 'cluster')).toBe(false)
    expect(canEditFirewall('operator', 'node')).toBe(false)
    expect(canEditFirewall('operator', 'group')).toBe(false)
  })

  it('lets an operator edit a guest firewall, matching guest networking', () => {
    expect(canEditFirewall('operator', 'guest')).toBe(true)
    expect(canEditFirewall('viewer', 'guest')).toBe(false)
  })
})

describe('FirewallClusterPage', () => {
  it('offers the five cluster tabs', async () => {
    wrap(<FirewallClusterPage />)
    await screen.findByRole('tab', { name: 'Rules' })
    for (const t of ['Rules', 'Security groups', 'Aliases', 'IP sets', 'Options']) {
      expect(screen.getByRole('tab', { name: t })).toBeTruthy()
    }
  })

  it('shows one entry per cluster, not one per enrolled host', async () => {
    // Two NodeRow rows share cluster "lab". They are the same firewall, and
    // listing it twice would offer two editors for one config file.
    wrap(<FirewallClusterPage />)
    await screen.findByRole('tab', { name: 'Rules' })
    expect(screen.getAllByText('lab')).toHaveLength(1)
  })

  it('switches tabs', async () => {
    wrap(<FirewallClusterPage />)
    await screen.findByRole('tab', { name: 'Aliases' })
    // Radix's Tabs.Trigger activates on mousedown, not click (see
    // storage.test.tsx for the same note), so a synthetic click alone does
    // not switch it.
    fireEvent.mouseDown(screen.getByRole('tab', { name: 'Aliases' }), { button: 0, ctrlKey: false })
    expect(screen.getByRole('button', { name: /add alias/i })).toBeTruthy()
  })
})
