import { useEffect, useRef } from 'react'
import type { AppRow } from '../api/hooks'
import { fmtBps, fmtBytes, fmtPct } from '../lib/format'
import { IconTile } from './IconTile'
import { AppActionBar } from './AppActionBar'
import { AppDetailPanel } from './AppDetailPanel'
import { linkCls } from './ui/button'
import { StatusPill } from './StatusPill'
import { UpdateDot } from './UpdateDot'
import { Icon } from './ui/icon'
import { Skeleton, SkeletonLine } from './ui/skeleton'
import { CPU_GRADIENT, RAM_GRADIENT, STORAGE_GRADIENT, UsageBar } from './UsageBar'

const HEADS = ['App', 'Host', 'Status', 'CPU', 'RAM', 'Storage', 'Network', '']

const th = 'px-4 py-2 text-left text-[10.5px] font-normal uppercase text-text-3'
const td = 'px-4 py-3 align-middle'

/**
 * The Apps section's list view: every app as a row, carrying the same
 * measurements the detailed card shows.
 *
 * NOT an extension of GuestList. That component merges apps and VMs into ONE
 * row shape, and its Guest type is deliberately lossy (memory pre-formatted
 * to a string, no disk, no network) because VMs have no data for those
 * columns. Widening it would put permanently empty columns on every VM row.
 *
 * There is no app detail PAGE: a row expands in place. `open` is the id of
 * the one row showing its detail, owned by whoever renders this table
 * (AppsPage keeps it in the URL, so /apps?open=3 is still shareable).
 */
export function AppTable({ apps, open, onOpen }: {
  apps: AppRow[]
  open?: number
  /** The row to show, or undefined for none. */
  onOpen: (id: number | undefined) => void
}) {
  const box = useRef<HTMLDivElement>(null)

  // Click-away, and the two things it must NOT close on.
  //
  // The listener is on `pointerdown`, not `click`, and the ref is on the whole
  // table rather than the open panel — both are about ordering. React attaches
  // handlers at the root container, so a row's own onClick runs BEFORE a
  // bubbling document listener sees the same event: with the ref on the panel,
  // clicking a different row would open it and then this listener (seeing the
  // click land outside the old panel) would close it again. Ref on the table
  // leaves every row-to-row switch inside the container.
  //
  // Radix menus portal to document.body, so a click on a menu item is outside
  // this container by DOM position while being inside the table by intent;
  // `data-radix-popper-content-wrapper` is the marker checked here. Dialogs
  // portal the same way and are not popper-wrapped, so they get their own
  // `[role="dialog"]` marker.
  useEffect(() => {
    if (open == null) return
    const away = (e: PointerEvent): void => {
      const t = e.target instanceof Element ? e.target : null
      if (!t) return
      if (box.current?.contains(t)) return
      if (t.closest('[data-radix-popper-content-wrapper]')) return
      if (t.closest('[role="dialog"],[role="alertdialog"]')) return
      onOpen(undefined)
    }
    document.addEventListener('pointerdown', away)
    return () => document.removeEventListener('pointerdown', away)
  }, [open, onOpen])

  return (
    <div ref={box} className="overflow-x-auto rounded-card border border-line-soft bg-panel">
      <table className="w-full border-collapse">
        <thead>
          <tr className="border-b border-line-soft">
            {HEADS.map((h, i) => (
              <th key={h || `actions-${i}`} scope="col" className={th}>{h}</th>
            ))}
          </tr>
        </thead>
        {/* One tbody per app, holding the row and its detail panel. The rule
            between apps lives on the tbody so it stays between apps instead of
            landing between a row and its own panel. */}
        {apps.map((a) => (
          <tbody key={a.id} className="border-b border-line-soft last:border-b-0">
            <AppTableRow app={a} open={open === a.id}
                         onToggle={() => onOpen(open === a.id ? undefined : a.id)} />
          </tbody>
        ))}
      </table>
    </div>
  )
}

function AppTableRow({ app, open, onToggle }: {
  app: AppRow; open: boolean; onToggle: () => void
}) {
  const memPct = app.mem_bytes != null && app.mem_total_bytes
    ? (app.mem_bytes / app.mem_total_bytes) * 100 : null
  const diskPct = app.disk_bytes != null && app.disk_total_bytes
    ? (app.disk_bytes / app.disk_total_bytes) * 100 : null
  return (
    <>
    <tr className="cursor-pointer transition-colors hover:bg-panel-2 motion-reduce:transition-none"
        onClick={onToggle}>
      <td className={td}>
        {/* The same tile the icon grid and the app card draw, at the grid's
            own 32px: an app is recognised by its logo before its name. */}
        <div className="flex items-center gap-2.5">
          <Icon name="expand_more" size={16}
                className={`shrink-0 text-text-3 transition-transform motion-reduce:transition-none
                            ${open ? 'rotate-180 text-amber' : ''}`} />
          <IconTile name={app.name} iconUrl={app.icon_url} size={32}
                    initials={app.icon_initials} colors={app.icon_colors} />
          {/* No onClick of its own: the whole row toggles, and a handler here
              would fire once for the button and again as the click bubbled to
              the row, cancelling itself out. It stays a real button so the row
              is reachable and announced from the keyboard. */}
          <button type="button" aria-expanded={open}
            className={`text-left font-mono text-[13px] ${linkCls}`}>
            {app.name}
          </button>
          {app.update_available && <UpdateDot />}
        </div>
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
      {/* No bar: a rate has no denominator to draw one against. Stacked
          rather than side by side so the two rates don't run together as one
          run of digits — down over up, hairline between, reads as two
          readings. */}
      <td className={`${td} font-mono text-[11px] text-text-2`}>
        <div className="whitespace-nowrap">↓ {fmtBps(app.net_in_bps)}</div>
        <div className="mt-1 whitespace-nowrap border-t border-line-soft pt-1">
          ↑ {fmtBps(app.net_out_bps)}
        </div>
      </td>
      {/* The actions are their own targets, never the row's: stopping the
          click here covers every control in the bar at once, including any
          added to it later, rather than trusting each one to stop its own. */}
      <td className={td} onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-end">
          <AppActionBar app={app} />
        </div>
      </td>
    </tr>
    {/* The expander. `grid-template-rows: 0fr -> 1fr` on a wrapper whose child
        is `overflow-hidden` is the one way to animate to a height nobody has
        measured: the grid track resolves to the content's natural height at
        1fr, and the browser interpolates the fraction (measuring in JS would
        re-measure on every resize and metric).

        The row is always in the DOM, empty and zero-height while closed,
        because a transition cannot run on an element that was not there for
        the previous frame; only the panel's CONTENT is conditional, so a
        closed app runs no queries. */}
    <tr>
      <td colSpan={8} className="p-0">
        <div className={`grid transition-[grid-template-rows] duration-200 ease-out
                         motion-reduce:transition-none ${open ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'}`}>
          <div className="overflow-hidden">
            {open && <div className="px-4 pb-4"><AppDetailPanel app={app} /></div>}
          </div>
        </div>
      </td>
    </tr>
    </>
  )
}

function Meter({ pct, gradient }: { pct: number | null; gradient: string }) {
  // gap-[3px], not gap-2: 8px of air between a bar and the number that reads
  // it left the pair looking like two separate things. Whole pixels because a
  // fraction lands on a device-pixel boundary and blurs.
  return (
    <div className="flex w-28 items-center gap-[3px]">
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
              <td className={td}>
                <div className="flex items-center gap-2.5">
                  <Skeleton className="h-8 w-8 shrink-0 rounded-tile" />
                  <SkeletonLine className="w-28 text-[13px]" />
                </div>
              </td>
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
