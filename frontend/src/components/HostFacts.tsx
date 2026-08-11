import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import type { NodeRow } from '../api/hooks'
import { fmtBytes, fmtUptime } from '../lib/format'
import { KVGrid } from './KVGrid'
import { CPU_GRADIENT, RAM_GRADIENT, STORAGE_GRADIENT, UsageBar } from './UsageBar'

/** GET /hosts/{id}/nodes/{node}/status, normalised by the backend. */
type Status = {
  node: string
  uptime_s: number | null
  pve_version: string | null
  kernel: string | null
  arch: string | null
  boot_mode: string | null
  secure_boot: boolean
  cpu: {
    model: string | null; vendor: string | null; sockets: number | null
    cores: number | null; threads: number | null; mhz: string | null
  }
  load: number[]
  io_delay: number | null
  memory: { total?: number; used?: number }
  swap: { total?: number; used?: number }
  rootfs: { total?: number; used?: number }
}

const pct = (used?: number | null, total?: number | null) =>
  total ? Math.round(((used ?? 0) / total) * 1000) / 10 : 0

/** "pve-manager/9.2.10/43df2e01f27a1a19" is a package string, not a version an
 *  operator reads out loud. */
function shortPve(raw: string | null): string {
  return raw?.split('/')[1] ?? 'unknown'
}

/** Everything the host page knows about this node, in one strip.
 *
 *  Two sources, deliberately merged rather than stacked in two cards: the
 *  poller's snapshot (`snapshot`, always present, and the only source anywhere
 *  for the deduped datastore fill and the guest counts) and the node's own
 *  /status (on demand, and refusable by a narrow token).
 *
 *  The snapshot half ALWAYS renders. Only the status-only rows — processor,
 *  cores, sockets, kernel, architecture, boot mode, load, IO delay, swap,
 *  root filesystem — disappear when the node will not answer. Dropping the
 *  whole strip in that case would cost the page the facts it already had.
 */
export function HostFacts({ hostId, node, snapshot }: {
  hostId: number
  node: string
  snapshot: NodeRow
}) {
  const q = useQuery({
    queryKey: ['hosts', hostId, 'node', node, 'status'],
    queryFn: () => api<Status>(`/hosts/${hostId}/nodes/${node}/status`),
    retry: false,
  })
  const s = q.data ?? null

  // Load normalised by thread count. A raw 14 means nothing until you know
  // the box has 20 threads; the raw triple stays beside it because the
  // normalised number alone hides the 1/5/15 trend.
  const threads = s?.cpu.threads || 1
  const loadPct = s ? Math.round(((s.load[0] ?? 0) / threads) * 1000) / 10 : 0

  // Memory and uptime are in BOTH sources and agree; the snapshot is used so
  // that the row does not move or empty when /status is refused.
  const items: [string, string][] = [
    ['Node', snapshot.node ?? 'unknown'],
    ['PVE version', s ? shortPve(s.pve_version) : snapshot.pve_version ?? 'unknown'],
    ['Uptime', fmtUptime(snapshot.uptime_s)],
  ]
  if (s) {
    items.push(
      ['Kernel', s.kernel ?? 'unknown'],
      ['Architecture', s.arch ?? 'unknown'],
      ['Processor', s.cpu.model ?? 'unknown'],
      ['Cores', `${s.cpu.cores ?? '?'} physical · ${s.cpu.threads ?? '?'} logical`],
      ['Sockets', String(s.cpu.sockets ?? 'unknown')],
      ['Load (1 · 5 · 15)', s.load.map((n) => n.toFixed(2)).join(' · ')],
      ['IO delay', s.io_delay != null ? `${(s.io_delay * 100).toFixed(2)}%` : 'unknown'],
    )
  }
  items.push(
    ['Memory', `${fmtBytes(snapshot.mem_bytes)} / ${fmtBytes(snapshot.mem_total_bytes)}`],
    // The datastore aggregate this node can actually use, shared pools
    // deduped by pollers._disk_pct. NOT the same number as the root
    // filesystem below, and on a real node not even the same order of
    // magnitude, so the two are named apart rather than collapsed.
    ['Storage', `${fmtBytes(snapshot.disk_bytes)} / ${fmtBytes(snapshot.disk_total_bytes)}`],
  )
  if (s) {
    items.push(
      ['Root filesystem', `${fmtBytes(s.rootfs.used ?? 0)} / ${fmtBytes(s.rootfs.total ?? 0)}`],
      ['Swap', `${fmtBytes(s.swap.used ?? 0)} / ${fmtBytes(s.swap.total ?? 0)}`],
      ['Boot', `${s.boot_mode ?? 'unknown'}${s.secure_boot ? ' · secure boot' : ''}`],
    )
  }
  items.push(
    ['Apps', `${snapshot.apps_running}/${snapshot.apps} running`],
    ['VMs', `${snapshot.vms_running}/${snapshot.vms} running`],
  )

  return (
    <div className="space-y-5 rounded-card border border-line-soft bg-panel p-5">
      <KVGrid items={items} />
      <div className="space-y-2">
        {s && <Bar label="Load" pct={loadPct} gradient={CPU_GRADIENT} />}
        <Bar label="RAM" pct={snapshot.mem_pct ?? pct(snapshot.mem_bytes, snapshot.mem_total_bytes)}
          gradient={RAM_GRADIENT} />
        <Bar label="Storage" pct={snapshot.disk_pct ?? pct(snapshot.disk_bytes, snapshot.disk_total_bytes)}
          gradient={STORAGE_GRADIENT} />
        {s && <Bar label="Root" pct={pct(s.rootfs.used, s.rootfs.total)} gradient={STORAGE_GRADIENT} />}
      </div>
    </div>
  )
}

function Bar({ label, pct, gradient }: { label: string; pct: number; gradient: string }) {
  return (
    <div className="flex items-center gap-3">
      <span className="w-16 text-[10.5px] uppercase tracking-wide text-text-3">{label}</span>
      <div className="flex-1"><UsageBar pct={pct} gradient={gradient} /></div>
      <span className="w-14 text-right font-mono text-[11px] text-text-2">{pct}%</span>
    </div>
  )
}
