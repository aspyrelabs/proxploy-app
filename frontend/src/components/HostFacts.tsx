import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
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

const pct = (used?: number, total?: number) =>
  total ? Math.round(((used ?? 0) / total) * 1000) / 10 : 0

/** "pve-manager/9.2.10/43df2e01f27a1a19" is a package string, not a version an
 *  operator reads out loud. */
function shortPve(raw: string | null): string {
  return raw?.split('/')[1] ?? 'unknown'
}

export function HostFacts({ hostId, node }: { hostId: number; node: string }) {
  const q = useQuery({
    queryKey: ['hosts', hostId, 'node', node, 'status'],
    queryFn: () => api<Status>(`/hosts/${hostId}/nodes/${node}/status`),
    retry: false,
  })
  // A token too narrow to read /nodes/{n}/status costs the STRIP, not the
  // page: everything else here already rendered from the poller's snapshot,
  // and an error banner over a working page would be a lie about the page.
  if (!q.data) return null
  const s = q.data
  // Load normalised by thread count. A raw 14 means nothing until you know
  // the box has 20 threads; the raw triple stays beside it because the
  // normalised number alone hides the 1/5/15 trend.
  const threads = s.cpu.threads || 1
  const loadPct = Math.round(((s.load[0] ?? 0) / threads) * 1000) / 10

  return (
    // Carries its own card so that a node which refuses to be read leaves no
    // empty bordered box behind on the page.
    <div className="space-y-5 rounded-card border border-line-soft bg-panel p-5">
      <KVGrid items={[
        ['Node', s.node],
        ['PVE version', shortPve(s.pve_version)],
        ['Kernel', s.kernel ?? 'unknown'],
        ['Architecture', s.arch ?? 'unknown'],
        ['Uptime', s.uptime_s != null ? fmtUptime(s.uptime_s) : 'unknown'],
        ['Processor', s.cpu.model ?? 'unknown'],
        ['Cores', `${s.cpu.cores ?? '?'} physical · ${s.cpu.threads ?? '?'} logical`],
        ['Sockets', String(s.cpu.sockets ?? 'unknown')],
        ['Load (1 · 5 · 15)', s.load.map((n) => n.toFixed(2)).join(' · ')],
        ['IO delay', s.io_delay != null ? `${(s.io_delay * 100).toFixed(2)}%` : 'unknown'],
        ['Memory', `${fmtBytes(s.memory.used ?? 0)} / ${fmtBytes(s.memory.total ?? 0)}`],
        ['Root filesystem', `${fmtBytes(s.rootfs.used ?? 0)} / ${fmtBytes(s.rootfs.total ?? 0)}`],
        ['Swap', `${fmtBytes(s.swap.used ?? 0)} / ${fmtBytes(s.swap.total ?? 0)}`],
        ['Boot', `${s.boot_mode ?? 'unknown'}${s.secure_boot ? ' · secure boot' : ''}`],
      ]} />

      <div className="space-y-2">
        <Bar label="Load" pct={loadPct} gradient={CPU_GRADIENT} />
        <Bar label="RAM" pct={pct(s.memory.used, s.memory.total)} gradient={RAM_GRADIENT} />
        <Bar label="Root" pct={pct(s.rootfs.used, s.rootfs.total)} gradient={STORAGE_GRADIENT} />
      </div>
    </div>
  )
}

function Bar({ label, pct, gradient }: { label: string; pct: number; gradient: string }) {
  return (
    <div className="flex items-center gap-3">
      <span className="w-12 text-[10.5px] uppercase tracking-wide text-text-3">{label}</span>
      <div className="flex-1"><UsageBar pct={pct} gradient={gradient} /></div>
      <span className="w-14 text-right font-mono text-[11px] text-text-2">{pct}%</span>
    </div>
  )
}
