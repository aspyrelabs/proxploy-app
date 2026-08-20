import { useNavigate } from '@tanstack/react-router'
import type { AppRow } from '../api/hooks'
import { fmtBps, fmtBytes, fmtPct } from '../lib/format'
import { openConsoleWindow } from '../lib/console-window'
import { ConsoleButton, LifecycleActions } from './LifecycleActions'
import { StatusPill } from './StatusPill'
import { Skeleton, SkeletonLine } from './ui/skeleton'
import { CPU_GRADIENT, RAM_GRADIENT, STORAGE_GRADIENT, UsageBar } from './UsageBar'

const HEADS = ['App', 'Host', 'Status', 'CPU', 'RAM', 'Storage', 'Network', '']

const th = 'px-4 py-2 text-left text-[10.5px] font-normal uppercase text-text-3'
const td = 'px-4 py-3 align-middle'

/**
 * The Apps section's list view: every app as a row, carrying the same
 * measurements the detailed card shows.
 *
 * NOT an extension of GuestList. That component exists to merge apps and VMs
 * into ONE row shape, and its Guest type is deliberately lossy (memory
 * pre-formatted to a string, no disk, no network) because VMs have no data
 * for those columns. Widening it to fit this view would put permanently empty
 * columns on every VM row.
 */
export function AppTable({ apps }: { apps: AppRow[] }) {
  return (
    <div className="overflow-x-auto rounded-card border border-line-soft bg-panel">
      <table className="w-full border-collapse">
        <thead>
          <tr className="border-b border-line-soft">
            {HEADS.map((h, i) => (
              <th key={h || `actions-${i}`} scope="col" className={th}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {apps.map((a) => <AppTableRow key={a.id} app={a} />)}
        </tbody>
      </table>
    </div>
  )
}

function AppTableRow({ app }: { app: AppRow }) {
  const navigate = useNavigate()
  const memPct = app.mem_bytes != null && app.mem_total_bytes
    ? (app.mem_bytes / app.mem_total_bytes) * 100 : null
  const diskPct = app.disk_bytes != null && app.disk_total_bytes
    ? (app.disk_bytes / app.disk_total_bytes) * 100 : null
  return (
    <tr className="border-b border-line-soft last:border-b-0">
      <td className={td}>
        <button type="button"
          className="text-left font-mono text-[13px] text-text transition hover:text-amber"
          onClick={() => navigate({ to: '/apps/$appId' as never,
                                    params: { appId: String(app.id) } as never })}>
          {app.name}
        </button>
        {app.update_available && (
          <span className="ml-2 rounded bg-amber-dim px-1.5 py-0.5 font-mono
                           text-[9.5px] uppercase text-amber">update</span>
        )}
      </td>
      <td className={`${td} font-mono text-[11px] text-text-3`}>
        {app.host_name} · CT {app.ctid}
      </td>
      <td className={td}><StatusPill status={app.status} /></td>
      <td className={td}><Meter pct={app.cpu_pct} gradient={CPU_GRADIENT} /></td>
      <td className={td}><Meter pct={memPct} gradient={RAM_GRADIENT} /></td>
      <td className={td}>
        <Meter pct={diskPct} gradient={STORAGE_GRADIENT} />
        <div className="font-mono text-[11px] text-text-3">
          {app.disk_total_bytes
            ? `${fmtBytes(app.disk_bytes)} / ${fmtBytes(app.disk_total_bytes)}`
            : fmtBytes(app.disk_bytes)}
        </div>
      </td>
      {/* No bar: a rate has no denominator to draw one against. */}
      <td className={`${td} whitespace-nowrap font-mono text-[11px] text-text-2`}>
        ↓ {fmtBps(app.net_in_bps)} ↑ {fmtBps(app.net_out_bps)}
      </td>
      <td className={td}>
        <div className="flex items-center justify-end gap-2">
          <LifecycleActions target="app" id={app.id} name={app.name}
                            status={app.status} hostId={app.host_id} size="sm" />
          <ConsoleButton hostId={app.host_id}
            onClick={() => openConsoleWindow('app', app.id)} />
        </div>
      </td>
    </tr>
  )
}

function Meter({ pct, gradient }: { pct: number | null; gradient: string }) {
  return (
    <div className="flex w-28 items-center gap-2">
      <div className="flex-1"><UsageBar pct={pct} gradient={gradient} /></div>
      <span className="w-9 text-right font-mono text-[11px] text-text-2">{fmtPct(pct)}</span>
    </div>
  )
}

/** The table's placeholder. Mirrors the row's px-4 py-3 rhythm and the two
 *  pieces tall enough to set its height, so the page below does not shift
 *  when the apps land. Edited with AppTableRow, never separately. */
export function AppTableSkeleton({ rows = 4 }: { rows?: number }) {
  return (
    <div className="overflow-x-auto rounded-card border border-line-soft bg-panel">
      <table className="w-full border-collapse">
        <tbody>
          {Array.from({ length: rows }, (_, i) => (
            <tr key={i} className="border-b border-line-soft last:border-b-0">
              <td className={td}><SkeletonLine className="w-28 text-[13px]" /></td>
              <td className={td}><SkeletonLine className="w-32 text-[11px]" /></td>
              <td className={td}><Skeleton className="h-[19px] w-20 rounded-full" /></td>
              <td className={td}><Skeleton className="h-1.5 w-28 rounded-full" /></td>
              <td className={td}><Skeleton className="h-1.5 w-28 rounded-full" /></td>
              <td className={td}><Skeleton className="h-1.5 w-28 rounded-full" /></td>
              <td className={td}><SkeletonLine className="w-32 text-[11px]" /></td>
              <td className={td}><Skeleton className="ms-auto h-6 w-40 rounded-ctl" /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
