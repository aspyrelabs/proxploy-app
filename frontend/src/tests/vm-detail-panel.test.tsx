import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const requested: string[] = []
const ISO_VOLID = 'local:iso/debian-12.7.0-amd64-netinst.iso'
let cdromStatus: { key: string | null; volid: string | null; mounted: boolean } =
  { key: null, volid: null, mounted: false }
const cdromWrites: (string | null)[] = []

vi.mock('../api/client', () => ({
  api: vi.fn((path: string, opts?: RequestInit) => {
    requested.push(path)
    const method = (opts?.method ?? 'GET').toUpperCase()
    if (path.startsWith('/metrics/query')) {
      return Promise.resolve({ target: 'vm:4', metric: 'cpu_pct',
                               resolution: '5m', ts: [1, 2], value: [0.2, 0.3] })
    }
    if (path === '/entitlements') {
      return Promise.resolve({ tier: 'builtin', features: { 'vms.snapshots': true },
                               grace: null, clock_skew: false })
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
    if (path === '/vms/4/cdrom' && method === 'PUT') {
      const body = opts?.body ? JSON.parse(String(opts.body)) : {}
      cdromWrites.push(body.volid ?? null)
      cdromStatus = body.volid
        ? { key: 'ide2', volid: body.volid, mounted: true }
        : { key: 'ide2', volid: null, mounted: false }
      return Promise.resolve(cdromStatus)
    }
    if (path === '/vms/4/cdrom') {
      return Promise.resolve(cdromStatus)
    }
    if (path === '/hosts') {
      return Promise.resolve([{ id: 1, cluster_name: null }])
    }
    if (path === '/storage') {
      return Promise.resolve([{ host_id: 1, node: 'pve1', storage: 'local',
        content: ['iso'], status: 'available', shared: false, cluster_name: null }])
    }
    if (path.startsWith('/storage/1/local/content')) {
      return Promise.resolve([{ volid: ISO_VOLID, size: 700000000 }])
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

import { VmDetailPanel } from '../components/VmDetailPanel'
import type { VmRow } from '../api/hooks'

const VM: VmRow = {
  id: 4, host_id: 1, host_name: 'pve-a', vmid: 201, name: 'win11',
  status: 'running', os_type: 'win11', cpu_cores: 4,
  // Used and allocated, the same meaning AppRow gives these names. The
  // allocated pair is what the Resources box prints; the used pair is what
  // the memory chart's "x of y" line divides.
  cpu_pct: 18, mem_bytes: 3221225472, mem_total_bytes: 8589934592,
  disk_bytes: 34359738368, disk_total_bytes: 68719476736,
  net_in_bps: 125000, net_out_bps: 62500,
  uptime_s: 86400, guest_agent_ok: true, node: 'pve1',
}

const wrap = (vm: VmRow = VM) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}><VmDetailPanel vm={vm} /></QueryClientProvider>)
}

/** The metric a /metrics/query URL asks for, keyed by its target. */
const seriesFor = (target: string) => requested
  .filter((p) => p.includes(`target=${target}`))
  .map((p) => new URL(p, 'http://x').searchParams.get('metric'))

beforeEach(() => {
  requested.length = 0
  cdromWrites.length = 0
  cdromStatus = { key: null, volid: null, mounted: false }
})

describe('VmDetailPanel', () => {
  it('draws CPU and memory as real charts, the same pair the apps panel draws', () => {
    wrap()
    expect(screen.getByRole('group', { name: 'CPU time range' })).toBeInTheDocument()
    expect(screen.getByRole('group', { name: 'Memory time range' })).toBeInTheDocument()
  })

  it('charts THIS vm, never an app or the host it sits on', async () => {
    wrap()
    await waitFor(() => expect(requested.filter((p) => p.startsWith('/metrics/query')).length)
      .toBeGreaterThan(1))
    expect(seriesFor('vm:4').sort()).toEqual(['cpu_pct', 'mem_pct'])
    expect(requested.some((p) => p.includes('target=app:'))).toBe(false)
    expect(requested.some((p) => p.includes('target=host:'))).toBe(false)
  })

  it('says whether the vm is running, and for how long', () => {
    wrap()
    // Exact "Running", not /running/i: the snapshot form's own help text says
    // "the running state", and a loose match picks that up too.
    expect(screen.getByText('Running')).toBeInTheDocument()
    expect(screen.getByText(/^up /)).toBeInTheDocument()
  })

  it('keeps the vCPU, RAM and disk figures the charts cannot give', () => {
    // The ALLOCATION figures, never the usage: this box says how big the VM
    // is. fmtBytes(8589934592) = "8.0 GiB", fmtBytes(68719476736) = "64.0 GiB".
    wrap()
    expect(screen.getByText('4 vCPU')).toBeInTheDocument()
    expect(screen.getByText('8.0 GiB RAM')).toBeInTheDocument()
    expect(screen.getByText('64.0 GiB disk')).toBeInTheDocument()
  })

  it('says what the memory percentage is a percentage of, as the apps panel does', () => {
    // The USED pair, which the Resources box does not carry: 3.0 of 8.0 GiB
    // is 37.5%, and fmtPct rounds to 38%.
    wrap()
    expect(screen.getByText('3.0 GiB of 8.0 GiB (38%)')).toBeInTheDocument()
  })

  // The row that replaced "Last checked". That one said when the poller last
  // stamped the row, which an operator could do nothing about; this one is the
  // reason the Storage column can read unknown, and installing the agent fixes
  // both. The three states have to stay three: see VmRow.guest_agent_ok.
  it('says the guest agent is installed when it answered', () => {
    wrap()
    expect(screen.getByText('Guest agent')).toBeInTheDocument()
    expect(screen.getByText('Installed')).toBeInTheDocument()
  })

  it('says the guest agent is not installed when Proxmox reported none', () => {
    wrap({ ...VM, guest_agent_ok: false })
    expect(screen.getByText('Not installed')).toBeInTheDocument()
    // And says why it matters, in the same words the storage column uses.
    expect(screen.getByRole('button', { name: /storage usage reads unknown/i }))
      .toBeInTheDocument()
  })

  it('says unknown, never "not installed", when nobody has an answer', () => {
    // A stopped VM, one not yet probed, or one whose host is unreachable all
    // land here. "Not installed" would send someone to install an agent that
    // may well already be running.
    wrap({ ...VM, guest_agent_ok: null })
    expect(screen.getByText('unknown')).toBeInTheDocument()
    expect(screen.queryByText('Not installed')).not.toBeInTheDocument()
    expect(screen.queryByText('Installed')).not.toBeInTheDocument()
  })

  it('shows snapshots inline, so an open row needs no second click', async () => {
    wrap()
    expect(screen.getByRole('heading', { name: 'Snapshots' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Take snapshot' })).toBeInTheDocument()
    await waitFor(() => expect(requested).toContain('/vms/4/snapshots'))
  })

  it('shows the CD-ROM drive inline too, same reasoning as snapshots', async () => {
    wrap()
    expect(screen.getByRole('heading', { name: 'CD-ROM' })).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText('Nothing mounted')).toBeInTheDocument())
  })
})

describe('VmCdromPanel', () => {
  it('says nothing is mounted, and offers no Eject button, until something is', async () => {
    wrap()
    await waitFor(() => expect(screen.getByText('Nothing mounted')).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: 'Eject' })).not.toBeInTheDocument()
  })

  it('picks a datastore, picks an ISO, and mounts it', async () => {
    wrap()
    await waitFor(() => expect(screen.getByText('Nothing mounted')).toBeInTheDocument())

    fireEvent.change(screen.getByLabelText('Datastore'), { target: { value: 'local' } })
    await screen.findByRole('option', { name: ISO_VOLID })
    fireEvent.change(screen.getByLabelText('ISO image'), { target: { value: ISO_VOLID } })

    fireEvent.click(screen.getByRole('button', { name: 'Mount' }))
    await waitFor(() => expect(cdromWrites).toEqual([ISO_VOLID]))
    await waitFor(() =>
      expect(screen.getByText('debian-12.7.0-amd64-netinst.iso')).toBeInTheDocument())
  })

  it('ejects a mounted ISO, leaving the drive attached but empty', async () => {
    cdromStatus = { key: 'ide2', volid: ISO_VOLID, mounted: true }
    wrap()
    const eject = await screen.findByRole('button', { name: 'Eject' })
    fireEvent.click(eject)
    await waitFor(() => expect(cdromWrites).toEqual([null]))
    await waitFor(() => expect(screen.getByText('Nothing mounted')).toBeInTheDocument())
  })
})
