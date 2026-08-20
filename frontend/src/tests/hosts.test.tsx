import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

let nodesResult: 'ok' | 'empty' | 'error' | 'cluster' | 'noEntry' | 'twoEndpoints'
  | 'unsorted' = 'ok'
let summaryResult: 'ok' | 'error' = 'ok'
let features: Record<string, boolean> = {}
// null means the node refuses /nodes/{n}/status, the narrow-token case.
let nodeStatus: Record<string, unknown> | null = null
// Controls for `/apps?host=` and `/vms?host=` specifically: NodeOverview's
// own guest queries, distinct from HostsPage's unfiltered `/apps` and `/vms`.
let nodeAppsResult: 'empty' | 'ok' | 'error' = 'empty'
let nodeVmsResult: 'empty' | 'ok' | 'error' = 'empty'
// HostsPage's own unfiltered `/apps` (its Apps section, distinct from the
// nodeAppsResult pair above). Defaults empty so every existing assertion
// about the section's empty state keeps rendering it that way.
let appsResult: 'empty' | 'ok' = 'empty'
// NodeDetailPage/NodeOverview/NodeHardware read their own params; reassigned
// per-test so a single fixture (pve1/pve2/pve3, see the cluster fixture
// below) can stand in for whichever node a test needs to look at.
let params: { hostId: string; node?: string } = { hostId: '1', node: 'pve1' }

const node = (over: Record<string, unknown> = {}) => ({
  host_id: 1, name: 'host-01', node: 'pve1', status: 'connected',
  cluster: null, is_entry: true, pve_version: '8.4.1', cpu_pct: 42, mem_pct: 41,
  mem_bytes: 137, mem_total_bytes: 338, uptime_s: 864000,
  disk_pct: 25, disk_bytes: 2147483648, disk_total_bytes: 34359738368,
  apps: 1, apps_running: 1, vms: 1, vms_running: 1, last_seen_at: null,
  ...over,
})

// Minimal AppRow/VmRow fixtures for the NodeOverview guest-list tests below.
// Full field lists live in guest-list.test.tsx; this file only needs enough
// to prove a row rendered.
const nodeAppFixture = () => ({
  id: 7, name: 'jellyfin', slug: 'jellyfin', host_id: 1, host_name: 'host-01',
  node: 'pve1', ctid: 104, category: null, catalog_slug: null,
  icon_initials: null, icon_colors: null, web_port: null, web_protocol: null,
  web_path: null, status: 'running', ip: null, cpu_pct: 12,
  mem_bytes: 2161287168, mem_total_bytes: 4294967296, uptime_s: 100,
  update_available: null, adopted: false,
})

const nodeVmFixture = () => ({
  id: 3, host_id: 1, host_name: 'host-01', vmid: 201, name: 'win11-lab',
  status: 'running', os_type: 'win11', cpu_cores: 4, cpu_pct: 3,
  mem_bytes: 2161287168, disk_bytes: null, uptime_s: 500, synced_at: null,
})

// A full AppRow, for HostsPage's own Apps section (the appsResult control
// above), distinct from nodeAppFixture which is deliberately minimal.
const appFixture = () => ({
  id: 7, name: 'jellyfin', slug: 'jellyfin', host_id: 1, host_name: 'host-01',
  node: 'pve1', ctid: 104, category: null, catalog_slug: null,
  icon_initials: null, icon_colors: null, icon_url: null,
  web_port: null, web_protocol: null, web_path: null, catalog_port: null,
  status: 'running', ip: null, cpu_pct: 12,
  mem_bytes: 2161287168, mem_total_bytes: 4294967296,
  disk_bytes: 5368709120, disk_total_bytes: 21474836480,
  net_in_bps: 1200, net_out_bps: 800,
  uptime_s: 100, update_available: null, adopted: false,
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
      // No row for this host claims is_entry: the entry node dropped out of
      // /cluster/nodes (or the host was never fully enrolled), so nothing
      // here can be named or linked to.
      if (nodesResult === 'twoEndpoints') {
        // The shape two clustered hosts really produce: a Host is one API
        // ENDPOINT, so each of them reports BOTH nodes and GET /cluster/nodes
        // answers 2x2. host-02's endpoint is down, while the nodes behind it
        // are fine -- the case that makes deduping lossy if nothing carries
        // endpoint health.
        return Promise.resolve([
          node({ host_id: 1, name: 'host-01', node: 'n1', cluster: 'lab-cluster', is_entry: true }),
          node({ host_id: 1, name: 'host-01', node: 'n2', cluster: 'lab-cluster', is_entry: false }),
          node({ host_id: 2, name: 'host-02', node: 'n1', cluster: 'lab-cluster',
                 is_entry: false, status: 'unreachable' }),
          node({ host_id: 2, name: 'host-02', node: 'n2', cluster: 'lab-cluster',
                 is_entry: true, status: 'unreachable' }),
        ])
      }
      // Deliberately reverse-alphabetical in every dimension, and with a
      // nameless row (a host whose first poll has not landed) among the
      // standalone ones, so the ordering test fails without the sort.
      if (nodesResult === 'unsorted') {
        return Promise.resolve([
          node({ host_id: 1, name: 'host-01', node: 'node2', cluster: 'zeta' }),
          node({ host_id: 1, name: 'host-01', node: 'node1', cluster: 'zeta' }),
          node({ host_id: 2, name: 'host-02', node: 'beta2', cluster: 'alpha' }),
          node({ host_id: 2, name: 'host-02', node: 'beta1', cluster: 'alpha' }),
          node({ host_id: 3, name: 'host-03', node: 'lab2', cluster: null }),
          node({ host_id: 4, name: 'host-04', node: null, cluster: null }),
          node({ host_id: 5, name: 'host-05', node: 'lab1', cluster: null }),
        ])
      }
      if (nodesResult === 'noEntry') {
        return Promise.resolve([node({ is_entry: false })])
      }
      return Promise.resolve([node()])
    }
    if (path.startsWith('/apps?host=')) {
      if (nodeAppsResult === 'error') return Promise.reject(new Error('boom'))
      if (nodeAppsResult === 'ok') return Promise.resolve([nodeAppFixture()])
      return Promise.resolve([])
    }
    if (path.startsWith('/vms?host=')) {
      if (nodeVmsResult === 'error') return Promise.reject(new Error('boom'))
      if (nodeVmsResult === 'ok') return Promise.resolve([nodeVmFixture()])
      return Promise.resolve([])
    }
    if (path === '/apps') {
      return Promise.resolve(appsResult === 'ok' ? [appFixture()] : [])
    }
    if (path.startsWith('/apps')) return Promise.resolve([])
    if (path.startsWith('/vms')) return Promise.resolve([])
    if (path.endsWith('/nodes/pve1/status')) {
      return nodeStatus ? Promise.resolve(nodeStatus) : Promise.reject(new Error('502'))
    }
    if (path.endsWith('/nodes/pve1/hardware')) {
      return Promise.resolve({ disks: [{
        devpath: '/dev/nvme0n1', model: 'WD Green SN350 2TB', serial: '22303K800007',
        size: 2000398934016, type: 'nvme', health: 'PASSED', wearout: 99,
        used: 'LVM', osd_id: null,
      }] })
    }
    if (path === '/hosts/1') {
      return Promise.resolve({ id: 1, name: 'host-01', address: 'https://10.0.0.5:8006',
                               node_shell_enabled: false })
    }
    // GET /hosts/capabilities, the catalog HostForm's checkboxes read
    // labels and the "why" explanation from. Without this case it fell
    // through to the generic /hosts handler below and resolved [], an
    // empty catalog that would leave the add-host form with none of the
    // three optional capability checkboxes.
    if (path === '/hosts/capabilities') {
      return Promise.resolve([
        { key: 'monitoring', label: 'Read-only monitoring', required: true,
          why: 'Pollers, dashboard, metrics, and every read view. Always required.' },
        { key: 'lifecycle', label: 'Lifecycle', required: false,
          why: 'Start/stop/restart, resource edits, snapshots, clone, migration, VM create/destroy, '
             + 'and node-level network/storage config (bridges, storage pools, storage content).' },
        { key: 'console', label: 'Console', required: false, why: 'Console tickets for containers and VMs.' },
        { key: 'backup', label: 'Backup', required: false,
          why: 'vzdump/PBS backup and restore jobs, and backup listing.' },
      ])
    }
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
  // The tab body is a routed child; these tests mount the tab components
  // directly rather than standing up a whole router (vms.test.tsx precedent).
  Outlet: () => null,
  // NodeDetailPage reads its own params; HostsPage never calls this.
  useParams: () => params,
}))

import { api } from '../api/client'
import { HostsPage, NodeDetailPage, NodeHardware, NodeOverview } from '../routes/hosts'

const withQuery = (ui: React.ReactNode) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

describe('HostsPage', () => {
  beforeEach(() => {
    nodesResult = 'ok'; summaryResult = 'ok'; features = {}; appsResult = 'empty'
    navigate.mockClear()
    // The view-switch test below writes pp_apps_view; clearing it here, not
    // only in that test's own body, keeps every test in this file (including
    // ones added later) starting from the same unset choice.
    localStorage.clear()
  })

  it('renders rings, counts and node cards from the API', async () => {
    withQuery(<HostsPage />)
    expect(await screen.findByText('pve1')).toBeInTheDocument()
    expect(screen.getByRole('img', { name: /CPU 42%/ })).toBeInTheDocument()
    // The App Store shipped and is a working nav item; the empty Apps
    // section used to point at "Phase 4" instead, which was both jargon and,
    // by the time this was reproduced, false.
    expect(screen.getByText(/Install one from the App Store/)).toBeInTheDocument()
    expect(screen.queryByText(/Phase/)).not.toBeInTheDocument()
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
    expect(await screen.findByRole('heading', { name: /prod/ })).toBeInTheDocument()
    // one card per node, not one per host
    expect(screen.getByText('pve1')).toBeInTheDocument()
    expect(screen.getByText('pve2')).toBeInTheDocument()
    expect(screen.getByText('pve3')).toBeInTheDocument()
    // and the group says how the cluster as a whole is doing
    expect(screen.getByText(/3 nodes · 1 unreachable/i)).toBeInTheDocument()
  })

  it('draws one card per node, not one per endpoint that can see it', async () => {
    nodesResult = 'twoEndpoints'
    withQuery(<HostsPage />)
    // Four rows in, two nodes out. Undeduped this rendered n1 and n2 twice
    // each, with duplicate gauges and a "4 nodes" count for a 2-node cluster.
    expect(await screen.findByText('n1')).toBeInTheDocument()
    expect(screen.getAllByText('n1')).toHaveLength(1)
    expect(screen.getAllByText('n2')).toHaveLength(1)
    expect(screen.getByText(/2 nodes/i)).toBeInTheDocument()
  })

  it('still reports an endpoint that is down after its duplicate card is gone', async () => {
    nodesResult = 'twoEndpoints'
    withQuery(<HostsPage />)
    // n1 survives via host-01, which is connected, so its own StatusPill says
    // nothing is wrong -- but host-02 is enrolled, cannot be reached, and its
    // row collapsed into this card. Saying so is the whole point.
    const card = within((await screen.findByText('n1')).closest('[role="link"]')!)
    expect(card.getByText(/host-02 cannot be reached/i)).toBeInTheDocument()
  })

  it('orders clusters and their cards by name, whatever order the API answered in', async () => {
    // Without the sort the cards sit in poll order, so they reshuffle under
    // the operator on every 30s refetch -- a two-node cluster drew node2 first.
    nodesResult = 'unsorted'
    const { container } = withQuery(<HostsPage />)
    await screen.findByText('node1')
    const at = (s: string) => container.textContent!.indexOf(s)
    expect(at('Cluster alpha')).toBeLessThan(at('Cluster zeta'))
    expect(at('beta1')).toBeLessThan(at('beta2'))
    expect(at('node1')).toBeLessThan(at('node2'))
    expect(at('lab1')).toBeLessThan(at('lab2'))
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
    expect(screen.queryByLabelText('Monitoring token id')).not.toBeInTheDocument()
    fireEvent.click(add)
    expect(await screen.findByLabelText('Monitoring token id')).toBeInTheDocument()
  })

  it('explains the multi-host plan instead of dropping an entitlement 403 on the operator', async () => {
    // POST /hosts answers 403 {"error":"entitlement_required","feature":
    // "hosts.multi"} once one host exists. A raw error at the end of a filled
    // in form is the worst place to learn that.
    features = {}
    withQuery(<HostsPage />)
    fireEvent.click(await screen.findByRole('button', { name: 'Add host' }))
    expect(await screen.findByText(/needs the multi-host plan/i)).toBeInTheDocument()
    expect(screen.queryByLabelText('Monitoring token id')).not.toBeInTheDocument()
  })

  it('shows one icon per app with its status, and no controls of its own', async () => {
    // The Apps section is a glance at what is installed. The view switch and
    // Update all moved to the Apps page, so neither may appear here, and the
    // section renders the icon grid regardless of any stored preference.
    appsResult = 'ok'
    localStorage.setItem('pp_apps_view', 'list')
    withQuery(<HostsPage />)

    // app-icon-<id> is AppIconGrid's own tile; nothing else renders it.
    expect(await screen.findByTestId('app-icon-7')).toBeInTheDocument()
    expect(screen.getByText('Running')).toBeInTheDocument()
    // A stored 'list' must not drag a table onto this page any more.
    expect(screen.queryByRole('table')).toBeNull()
    expect(screen.queryByRole('button', { name: 'List view' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Icon view' })).toBeNull()
    expect(screen.queryByRole('button', { name: /update all/i })).toBeNull()
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
    const card = (await screen.findByText('pve1')).closest('[role="link"]')!
    fireEvent.click(card)
    expect(navigate).toHaveBeenCalledWith(expect.objectContaining({
      to: '/hosts/$hostId/$node', params: { hostId: '1', node: 'pve1' },
    }))
  })

  it('is reachable from the keyboard', async () => {
    withQuery(<HostsPage />)
    await screen.findByText('pve1')
    fireEvent.keyDown(screen.getByRole('link', { name: /pve1/ }), { key: 'Enter' })
    expect(navigate).toHaveBeenCalledWith(expect.objectContaining({
      to: '/hosts/$hostId/$node',
    }))
  })

  it('shows storage next to CPU and RAM: three bars, three labels', async () => {
    withQuery(<HostsPage />)
    // scoped to the card: the summary rings above it are also labelled CPU
    const card = within((await screen.findByText('pve1')).closest('[role="link"]')!)
    expect(card.getByText('CPU')).toBeInTheDocument()
    expect(card.getByText('RAM')).toBeInTheDocument()
    expect(card.getByText('Disk')).toBeInTheDocument()
    // the readout beside the bar, not just the bar itself
    expect(card.getByText('25%')).toBeInTheDocument()
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

describe('NodeDetailPage', () => {
  beforeEach(() => {
    nodesResult = 'ok'; summaryResult = 'ok'; features = {}
    nodeStatus = null; navigate.mockClear()
    params = { hostId: '1', node: 'pve1' }
  })

  it('links out to the Proxmox web UI, safely', async () => {
    withQuery(<NodeDetailPage />)
    const link = await screen.findByRole('link', { name: /proxmox web ui/i })
    expect(link).toHaveAttribute('href', 'https://10.0.0.5:8006')
    expect(link).toHaveAttribute('target', '_blank')
    // Without noopener the opened page can navigate this one via window.opener.
    expect(link.getAttribute('rel')).toContain('noopener')
    expect(link.getAttribute('rel')).toContain('noreferrer')
  })

  it('offers Overview and Hardware tabs, like every other detail page', async () => {
    withQuery(<NodeDetailPage />)
    expect(await screen.findByText('Overview')).toBeInTheDocument()
    expect(screen.getByText('Hardware')).toBeInTheDocument()
  })
})

describe('NodeOverview', () => {
  beforeEach(() => {
    nodesResult = 'ok'; summaryResult = 'ok'; features = {}
    nodeStatus = null; navigate.mockClear()
    params = { hostId: '1', node: 'pve1' }
    nodeAppsResult = 'empty'; nodeVmsResult = 'empty'
  })

  // CRITICAL: GuestList merges apps and VMs under one QueryState keyed to the
  // apps query alone, so `/apps` -> [] used to short-circuit to the empty
  // state before `vms` was ever looked at, hiding a real, running VM. A
  // fresh install with an adopted-app count of zero and real VMs hit this on
  // first load.
  it('renders VMs even when the node has zero apps', async () => {
    nodeAppsResult = 'empty'; nodeVmsResult = 'ok'
    withQuery(<NodeOverview />)
    expect(await screen.findByText('win11-lab')).toBeInTheDocument()
    expect(screen.queryByText('No guests on this node')).not.toBeInTheDocument()
    expect(screen.getByText('Guests on this host (1)')).toBeInTheDocument()
  })

  it('renders apps even when the node has zero VMs', async () => {
    nodeAppsResult = 'ok'; nodeVmsResult = 'empty'
    withQuery(<NodeOverview />)
    expect(await screen.findByText('jellyfin')).toBeInTheDocument()
    expect(screen.queryByText('No guests on this node')).not.toBeInTheDocument()
    expect(screen.getByText('Guests on this host (1)')).toBeInTheDocument()
  })

  it('shows one empty state, not two, when both apps and VMs are empty', async () => {
    nodeAppsResult = 'empty'; nodeVmsResult = 'empty'
    withQuery(<NodeOverview />)
    expect(await screen.findAllByText('No guests on this node')).toHaveLength(1)
  })

  it('still renders VMs when the apps query fails', async () => {
    // QueryState used to gate the whole merged list on the apps query alone:
    // an apps error rendered "Guests not readable" and hid working VMs
    // entirely, regardless of what /vms answered.
    nodeAppsResult = 'error'; nodeVmsResult = 'ok'
    withQuery(<NodeOverview />)
    expect(await screen.findByText('win11-lab')).toBeInTheDocument()
    expect(screen.queryByText('Guests not readable')).not.toBeInTheDocument()
    expect(screen.queryByText('No guests on this node')).not.toBeInTheDocument()
  })

  it('still renders apps when the VMs query fails', async () => {
    // The mirror case: /vms erroring used to be swallowed entirely by
    // `vms ?? []`, with no error surface and a heading that silently
    // undercounted.
    nodeAppsResult = 'ok'; nodeVmsResult = 'error'
    withQuery(<NodeOverview />)
    expect(await screen.findByText('jellyfin')).toBeInTheDocument()
    expect(screen.queryByText('No guests on this node')).not.toBeInTheDocument()
  })

  it('reports storage used / total in the identity rail', async () => {
    withQuery(<NodeOverview />)
    expect(await screen.findByText('2.0 GiB / 32.0 GiB')).toBeInTheDocument()
  })

  it('charts memory as a percentage, so all three charts share one scale', async () => {
    // It used to chart mem_bytes against an axis-free sparkline: a curve of
    // raw byte counts beside two percentage curves, with nothing on screen
    // saying which was which.
    withQuery(<NodeOverview />)
    await screen.findByText('2.0 GiB / 32.0 GiB')
    const asked = vi.mocked(api).mock.calls.map((c) => String(c[0]))
    expect(asked.some((p) => p.includes('metric=mem_pct'))).toBe(true)
    expect(asked.some((p) => p.includes('metric=mem_bytes'))).toBe(false)
  })

  it('says "no data yet" for a metric with no samples rather than drawing an empty box', async () => {
    // disk_pct only began recording on this install recently, so "no samples"
    // is a real, common state and not an error.
    withQuery(<NodeOverview />)
    // waitFor on the COUNT, not findAllByText, which resolves as soon as one
    // match exists. Each chart now shows a placeholder until its own query
    // settles, so the three arrive independently and the first one through
    // would otherwise satisfy the assertion on its own.
    await waitFor(() => expect(screen.getAllByText(/no data yet/i)).toHaveLength(3))
  })

  it('shows the hardware facts when the node will report them', async () => {
    nodeStatus = {
      node: 'pve1', uptime_s: 25029, pve_version: 'pve-manager/9.2.10/43df',
      kernel: '7.0.14-11-pve', arch: 'x86_64', boot_mode: 'efi', secure_boot: false,
      cpu: { model: 'Core i5-13500T', vendor: 'GenuineIntel', sockets: 1,
             cores: 14, threads: 20, mhz: '800.000' },
      load: [2, 1, 0.5], io_delay: 0.00027,
      memory: { total: 33306869760, used: 2161287168 }, swap: {}, rootfs: {},
    }
    withQuery(<NodeOverview />)
    expect(await screen.findByText(/Core i5-13500T/)).toBeInTheDocument()
  })

  it('still renders when the node refuses to report them', async () => {
    // A token too narrow for /nodes/{n}/status must cost the strip, not the page.
    nodeStatus = null
    withQuery(<NodeOverview />)
    // Two waits, and both are load bearing. The first proves the rail rendered
    // at all: this figure comes from the poller snapshot, not from /status.
    // The second waits for /status to SETTLE, because a pending status still
    // shows placeholder rows, so asserting Processor's absence on its own
    // would also pass against a rail that had not rendered yet.
    expect(await screen.findByText('2.0 GiB / 32.0 GiB')).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByText(/Processor/)).not.toBeInTheDocument())
  })

  it('says where the metrics live instead of silently dropping the charts', async () => {
    // pve1 is not the entry node; pve2 is. The host:<id> series is recorded
    // from the node Proxploy connects through, so charting it here would be
    // charting a different machine, but saying nothing reads as a bug.
    nodesResult = 'cluster'
    params = { hostId: '1', node: 'pve1' }
    withQuery(<NodeOverview />)
    expect(await screen.findByText(/recorded on/i)).toBeInTheDocument()
    // Exact match: the entry-node span reads "pve2" alone, while the link's
    // own text is "Open pve2 →": a /pve2/ regex matches both and is
    // ambiguous, so this pins down the plain mention specifically.
    expect(screen.getByText('pve2')).toBeInTheDocument()
    // The mocked <Link> (above) renders a bare <a> with no href, so it has no
    // accessible "link" role in jsdom; assert on the routed destination the
    // way the NodeCard tests in this file already do.
    const openLink = screen.getByText(/open pve2/i).closest('a')!
    expect(openLink.getAttribute('data-to')).toBe('/hosts/$hostId/$node')
    expect(JSON.parse(openLink.getAttribute('data-params')!))
      .toEqual({ hostId: '1', node: 'pve2' })
  })

  it('draws the charts, and no note, on the entry node', async () => {
    nodesResult = 'cluster'
    params = { hostId: '1', node: 'pve2' }
    withQuery(<NodeOverview />)
    expect(await screen.findByText('Identity')).toBeInTheDocument()
    expect(screen.queryByText(/recorded on/i)).not.toBeInTheDocument()
  })

  it('still says the sentence, with no link, when no entry node is known', async () => {
    // No row for this host claims is_entry: true (the fixture above); the
    // note must still name the reason, just without a node to point at.
    nodesResult = 'noEntry'
    params = { hostId: '1', node: 'pve1' }
    withQuery(<NodeOverview />)
    expect(await screen.findByText(/this host.s entry node/i)).toBeInTheDocument()
    expect(screen.queryByText(/^Open /)).not.toBeInTheDocument()
  })
})

describe('NodeHardware', () => {
  beforeEach(() => {
    nodesResult = 'ok'; summaryResult = 'ok'; features = {}
    nodeStatus = null; navigate.mockClear()
    params = { hostId: '1', node: 'pve1' }
  })

  it('lists disks with health and wearout', async () => {
    withQuery(<NodeHardware />)
    expect(await screen.findByText('WD Green SN350 2TB')).toBeInTheDocument()
    expect(screen.getByText('PASSED')).toBeInTheDocument()
    // PVE reports wearout as life REMAINING; "99% used" would invert it.
    expect(screen.getByText(/99% left/)).toBeInTheDocument()
    expect(screen.getByText('/dev/nvme0n1')).toBeInTheDocument()
    expect(screen.getByText('1.8 TiB')).toBeInTheDocument()
  })
})
