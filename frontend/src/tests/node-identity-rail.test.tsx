/** The host page's identity rail: what this machine is, in four groups. */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

let status: unknown = null
let fails = false

vi.mock('../api/client', () => ({
  api: vi.fn(() => (fails ? Promise.reject(new Error('502')) : Promise.resolve(status))),
  ApiError: class extends Error {},
}))

import type { NodeRow } from '../api/hooks'
import { NodeIdentityRail } from '../components/NodeIdentityRail'

/** The poller's snapshot. Deliberately carrying figures that DIFFER from the
 *  status payload's rootfs by orders of magnitude, because on a real node they
 *  do: this is the deduped datastore aggregate, that is one filesystem. */
const snapshot = (over: Partial<NodeRow> = {}): NodeRow => ({
  host_id: 1, name: 'host-01', node: 'pve1', status: 'connected', is_entry: true,
  cluster: null, pve_version: '9.2.10', cpu_pct: 0.14, mem_pct: 6.5,
  mem_bytes: 2161287168, mem_total_bytes: 33306869760,
  disk_pct: 0.3, disk_bytes: 6442450944, disk_total_bytes: 2000398934016,
  uptime_s: 25029, apps: 3, apps_running: 2, vms: 2, vms_running: 1,
  last_seen_at: null, ...over,
})

const wrap = (snap: NodeRow = snapshot()) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <NodeIdentityRail hostId={1} node="pve1" snapshot={snap} />
    </QueryClientProvider>)
}

describe('NodeIdentityRail', () => {
  beforeEach(() => {
    fails = false
    status = {
      node: 'pve1', uptime_s: 25029, pve_version: 'pve-manager/9.2.10/43df2e01f27a1a19',
      kernel: '7.0.14-11-pve', arch: 'x86_64', boot_mode: 'efi', secure_boot: false,
      cpu: { model: '13th Gen Intel(R) Core(TM) i5-13500T', vendor: 'GenuineIntel',
             sockets: 1, cores: 14, threads: 20, mhz: '800.000' },
      load: [2.0, 1.0, 0.5], io_delay: 0.00027,
      memory: { total: 33306869760, used: 2161287168 },
      swap: { total: 8589930496, used: 0 },
      rootfs: { total: 100861726720, used: 6425862144 },
    }
  })

  it('names all four groups when the node answers', async () => {
    wrap()
    expect(await screen.findByText('Processor')).toBeInTheDocument()
    expect(screen.getByText('Identity')).toBeInTheDocument()
    expect(screen.getByText('Memory & storage')).toBeInTheDocument()
    expect(screen.getByText('Boot')).toBeInTheDocument()
  })

  it('separates physical cores from threads', async () => {
    wrap()
    expect(await screen.findByText(/14 physical/i)).toBeInTheDocument()
    expect(screen.getByText(/20 logical/i)).toBeInTheDocument()
  })

  it('shows the processor model and kernel', async () => {
    wrap()
    expect(await screen.findByText(/i5-13500T/)).toBeInTheDocument()
    expect(screen.getByText('7.0.14-11-pve')).toBeInTheDocument()
  })

  it('normalises load by thread count, and still shows the raw triple', async () => {
    wrap()
    // 2.0 over 20 threads is 10% busy, not "200% of one core".
    expect(await screen.findByText(/10%/)).toBeInTheDocument()
    expect(screen.getByText(/2\.00 · 1\.00 · 0\.50/)).toBeInTheDocument()
  })

  it('renders IO delay as a percentage rather than a raw fraction', async () => {
    wrap()
    expect(await screen.findByText(/0\.03%/)).toBeInTheDocument()
  })

  it('shows the PVE version without the manager prefix and build hash', async () => {
    wrap()
    expect(await screen.findByText('9.2.10')).toBeInTheDocument()
  })

  it('keeps the datastore total and the root filesystem apart', async () => {
    // On a real node these differ by orders of magnitude. Collapsing them into
    // one "Storage" row would answer neither question honestly.
    wrap()
    expect(await screen.findByText('Root filesystem')).toBeInTheDocument()
    // 'Storage' names both the fact row and the bar above it, hence getAllBy.
    expect(screen.getAllByText('Storage').length).toBeGreaterThan(0)
    expect(screen.getByText('6.0 GiB / 1.8 TiB')).toBeInTheDocument()      // datastores
    expect(screen.getByText('6.0 GiB / 93.9 GiB')).toBeInTheDocument()     // rootfs
  })

  it('costs the status-only rows, not the rail, when the node refuses to be read', async () => {
    // A token too narrow for /nodes/{n}/status must not cost the page the
    // facts the poller already had.
    fails = true
    wrap()
    expect(await screen.findByText('Identity')).toBeInTheDocument()
    expect(screen.getByText('Node')).toBeInTheDocument()
    expect(screen.getByText('9.2.10')).toBeInTheDocument()
    expect(screen.getByText('6h 57m')).toBeInTheDocument()
    expect(screen.getByText('2.0 GiB / 31.0 GiB')).toBeInTheDocument()
    expect(screen.getByText('6.0 GiB / 1.8 TiB')).toBeInTheDocument()
    // and the rows only the node itself can answer are simply absent
    expect(screen.queryByText('Processor')).not.toBeInTheDocument()
    expect(screen.queryByText('Kernel')).not.toBeInTheDocument()
    expect(screen.queryByText('IO delay')).not.toBeInTheDocument()
    expect(screen.queryByText('Root filesystem')).not.toBeInTheDocument()
  })

  // This is the rule grouping ADDS. Without it, a refused /status leaves a
  // "Processor" heading over nothing and a "Boot" heading over nothing —
  // grouping would have made the degraded case worse than the flat strip.
  it('renders no heading for a group whose rows all vanished', async () => {
    fails = true
    wrap()
    expect(await screen.findByText('Identity')).toBeInTheDocument()
    expect(screen.getByText('Memory & storage')).toBeInTheDocument()
    expect(screen.queryByText('Processor')).not.toBeInTheDocument()
    expect(screen.queryByText('Boot')).not.toBeInTheDocument()
  })

  // The counts moved to the "Guests on this host (n)" heading, which already
  // carried a total. Two places stating the same count is the duplication the
  // 2026-08-11 "one KV strip, not two" commit removed.
  it('does not restate the guest counts the guests heading already carries', async () => {
    wrap()
    expect(await screen.findByText('Identity')).toBeInTheDocument()
    expect(screen.queryByText('2/3 running')).not.toBeInTheDocument()
    expect(screen.queryByText('1/2 running')).not.toBeInTheDocument()
  })

  it('survives a node that reports no cpuinfo at all', async () => {
    status = { node: 'pve1', uptime_s: null, pve_version: null, kernel: null,
               arch: null, boot_mode: null, secure_boot: false,
               cpu: { model: null, vendor: null, sockets: null, cores: null,
                      threads: null, mhz: null },
               load: [0, 0, 0], io_delay: null, memory: {}, swap: {}, rootfs: {} }
    wrap()
    expect(await screen.findByText(/\? physical/)).toBeInTheDocument()
    // and it must not divide by a zero thread count
    expect(screen.getAllByText('0%').length).toBeGreaterThan(0)
  })
})
