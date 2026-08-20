import { useEffect, useRef } from 'react'
import type { AppRow } from '../api/hooks'
import { fmtBps, fmtBytes, fmtPct } from '../lib/format'
import { IconTile } from './IconTile'
import { AppActionBar } from './AppActionBar'
import { AppDetailPanel } from './AppDetailPanel'
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
 * NOT an extension of GuestList. That component exists to merge apps and VMs
 * into ONE row shape, and its Guest type is deliberately lossy (memory
 * pre-formatted to a string, no disk, no network) because VMs have no data
 * for those columns. Widening it to fit this view would put permanently empty
 * columns on every VM row.
 *
 * There is no app detail PAGE any more: a row expands in place and floats the
 * rows below it down. `open` is the id of the one row showing its detail, and
 * it is owned by whoever renders this table (AppsPage keeps it in the URL, so
 * /apps?open=3 is still a link you can send someone).
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
  // table rather than on the open panel. Both of those are about ordering.
  // React attaches its handlers at the root container, which is itself inside
  // `document`, so a row's own onClick runs BEFORE a bubbling document click
  // listener sees the same event: with the ref on the panel, clicking a
  // different row would open that row and then this listener, told the click
  // landed outside the (old) panel, would close it again. With the ref on the
  // table, every row-to-row switch is inside the container and the row's own
  // onClick is left to do the switching.
  //
  // Radix menus portal to document.body, so a click on a menu item is outside
  // this container by DOM position while being inside the table by intent.
  // @radix-ui/react-popper wraps that portalled content in an element carrying
  // `data-radix-popper-content-wrapper`, which is the marker checked here.
  //
  // Dialogs portal the same way and are not popper-wrapped, so they need their
  // own marker. Migrate, Reconfigure, Backup and Delete all open one from the
  // row's own menu, and without this a click anywhere inside that dialog
  // collapsed the panel sitting behind it.
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
            own 32px: an app is recognised by its logo before its name, and a
            table that dropped it made every row look alike. */}
        <div className="flex items-center gap-2.5">
          <Icon name="expand_more" size={16}
                className={`shrink-0 text-text-3 transition-transform motion-reduce:transition-none
                            ${open ? 'rotate-180 text-amber' : ''}`} />
          <IconTile name={app.name} iconUrl={app.icon_url} size={32}
                    initials={app.icon_initials} colors={app.icon_colors} />
          {/* No onClick of its own: the whole row toggles, and a handler here
              would fire once for the button and again as the click bubbled to
              the row, cancelling itself out. It stays a real button so the
              row is reachable and announced from the keyboard. */}
          <button type="button" aria-expanded={open}
            className="text-left font-mono text-[13px] text-text transition hover:text-amber">
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
      {/* No bar: a rate has no denominator to draw one against. */}
      <td className={`${td} whitespace-nowrap font-mono text-[11px] text-text-2`}>
        ↓ {fmtBps(app.net_in_bps)} ↑ {fmtBps(app.net_out_bps)}
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
        1fr, and the browser interpolates the fraction. Measuring the panel in
        JS to animate a pixel height would re-measure on every resize and on
        every metric that lands inside it.

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
