import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const requested: string[] = []

vi.mock('../api/client', () => ({
  api: vi.fn((path: string) => {
    requested.push(path)
    if (path.startsWith('/metrics/query')) {
      return Promise.resolve({ target: 'vm:4', metric: 'cpu_pct',
                               resolution: '5m', ts: [1, 2], value: [0.2, 0.3] })
    }
    if (path === '/entitlements') {
      return Promise.resolve({ tier: 'builtin', features: { 'vms.snapshots': true },
                               grace: null, clock_skew: false })
    }
    return Promise.resolve([])
  }),
  ApiError: class extends Error {},
}))
vi.mock('@tanstack/react-router', async (orig) => ({
  ...(await orig() as object),
  useNavigate: () => vi.fn(),
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
  uptime_s: 86400, guest_agent_ok: true,
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

beforeEach(() => { requested.length = 0 })

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
})
