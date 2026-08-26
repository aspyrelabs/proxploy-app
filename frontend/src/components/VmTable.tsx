import { useEffect, useRef } from 'react'
import type { VmRow } from '../api/hooks'
import { fmtBps, fmtBytes, fmtPct } from '../lib/format'
import { osIconUrl } from '../lib/os-icon'
import { IconTile } from './IconTile'
import { StatusPill } from './StatusPill'
import { linkCls } from './ui/button'
import { VmActionBar } from './VmActionBar'
import { VmDetailPanel } from './VmDetailPanel'
import { Icon } from './ui/icon'
import { InfoHint } from './ui/info-hint'
import { Skeleton, SkeletonLine } from './ui/skeleton'
import { CPU_GRADIENT, RAM_GRADIENT, STORAGE_GRADIENT, UsageBar } from './UsageBar'

const HEADS = ['Name', 'Host', 'Status', 'CPU', 'RAM', 'Storage', 'Network', '']

const th = 'px-4 py-2 text-left text-[10.5px] font-normal uppercase text-text-3'
const td = 'px-4 py-3 align-middle'

/**
 * The Virtual Machines list: every VM as a row that expands in place.
 * AppTable's twin, same columns in the same order (the API now fills every
 * column a VM row reports). There is no VM detail page: a row expands and
 * floats the rows below it down. `open` is the id of the one row showing its
 * detail, owned by whoever renders this table (VmsPage keeps it in the URL).
 */
export function VmTable({ vms, open, onOpen }: {
  vms: VmRow[]
  /** The row to show, or undefined for none. */
  open?: number
  onOpen: (id: number | undefined) => void
}) {
  const box = useRef<HTMLDivElement>(null)

  // Click-away, and the two things it must NOT close on (same listener AppTable
  // carries):
  // 
  // `pointerdown` not `click`, and the ref on the whole table not the panel:
  // React handlers run at the root (inside document), so a row's onClick fires
  // before a bubbling document listener; with the ref on the panel a row switch
  // would open then immediately close again.
  // 
  // Radix menus portal to body, wrapped in `data-radix-popper-content-wrapper`
  // (the marker checked here). Dialogs portal unwrapped, so they carry their own
  // marker; without it a click inside a dialog collapsed the panel behind it.
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
        {/* One tbody per VM, holding the row and its detail panel. The rule
            between VMs lives on the tbody so it stays between VMs instead of
            landing between a row and its own panel. */}
        {vms.map((v) => (
          <tbody key={v.id} className="border-b border-line-soft last:border-b-0">
            <VmTableRow vm={v} open={open === v.id}
                        onToggle={() => onOpen(open === v.id ? undefined : v.id)} />
          </tbody>
        ))}
      </table>
    </div>
  )
}

function VmTableRow({ vm, open, onToggle }: {
  vm: VmRow; open: boolean; onToggle: () => void
}) {
  const memPct = vm.mem_bytes != null && vm.mem_total_bytes
    ? (vm.mem_bytes / vm.mem_total_bytes) * 100 : null
  // Null, not zero, when the VM has no QEMU guest agent: PVE cannot read the
  // filesystem inside the image without one, so disk_bytes arrives null and
  // this stays null all the way to fmtPct, which says "unknown". A `?? 0`
  // anywhere along here would draw an empty bar and claim 0% used, which is a
  // measurement nobody took.
  const diskPct = vm.disk_bytes != null && vm.disk_total_bytes
    ? (vm.disk_bytes / vm.disk_total_bytes) * 100 : null
  return (
    <>
    <tr className="cursor-pointer transition-colors hover:bg-panel-2 motion-reduce:transition-none"
        onClick={onToggle}>
      <td className={td}>
        <div className="flex items-center gap-2.5">
          <Icon name="expand_more" size={16}
                className={`shrink-0 text-text-3 transition-transform motion-reduce:transition-none
                            ${open ? 'rotate-180 text-amber' : ''}`} />
          {/* The same 32px tile the Apps row draws, so the two lists share one
              rhythm and a row is the same height on both. An app wears the logo
              of the Store entry it came from; a VM has no such entry, so it
              wears its OS instead, which is the most an outside observer can
              honestly say about what is inside it.

              osIconUrl returns null for an ostype we do not recognise and for
              a VM whose ostype PVE has not told us yet, and IconTile treats a
              null url as "no artwork" and falls back to the initials tile. So
              an unknown OS looks like an app with no logo rather than like a
              broken image. */}
          <IconTile name={vm.name} iconUrl={osIconUrl(vm.os_type)} size={32} />
          {/* No onClick of its own: the whole row toggles, and a handler here
              would fire once for the button and again as the click bubbled to
              the row, cancelling itself out. It stays a real button so the
              row is reachable and announced from the keyboard. */}
          <button type="button" aria-expanded={open}
            className={`text-left font-mono text-[13px] ${linkCls}`}>
            {vm.name}
          </button>
        </div>
      </td>
      <td className={`${td} font-mono text-[11px] text-text-3`}>
        {vm.host_name} · VM {vm.vmid}
      </td>
      <td className={td}><StatusPill status={vm.status} /></td>
      <td className={td}><Meter pct={vm.cpu_pct} gradient={CPU_GRADIENT} /></td>
      <td className={td}><Meter pct={memPct} gradient={RAM_GRADIENT} /></td>
      {/* Storage is the one column a VM cannot always answer. The hypervisor
          sees a block device, not the filesystem inside it, so used bytes come
          from the guest agent's get-fsinfo and are null on a VM that has none.
          "unknown" alone reads as a bug in Proxploy; the hint says whose
          information it is and how to get it. The ALLOCATED size is known
          either way and is still shown, so the cell is never empty. */}
      <td className={td}>
        {vm.disk_bytes == null ? (
          // No bar and no byte line, just the word and the reason. A track
          // drawn at nought reads as an empty disk, and "unknown / 32.0 GiB"
          // pairs a non-answer with an answer as though they were the same
          // kind of thing. There is no reading here at all, so the cell says
          // exactly that and the hint says why.
          <span className="flex items-center gap-1 font-mono text-[11px] text-text-3">
            unknown <InfoHint text={NO_AGENT} />
          </span>
        ) : (
          <>
            <Meter pct={diskPct} gradient={STORAGE_GRADIENT} />
            <div className="font-mono text-[11px] text-text-3">
              {vm.disk_total_bytes
                ? `${fmtBytes(vm.disk_bytes)} / ${fmtBytes(vm.disk_total_bytes)}`
                : fmtBytes(vm.disk_bytes)}
            </div>
          </>
        )}
      </td>
      {/* No bar: a rate has no denominator to draw one against.
          Stacked rather than side by side: the two rates ran together on one
          line as a single run of digits and arrows, and at four significant
          figures each the cell was the widest thing in the row. Down over up,
          in that order, with a hairline between so the pair reads as two
          readings rather than one number that wrapped. */}
      <td className={`${td} font-mono text-[11px] text-text-2`}>
        <div className="whitespace-nowrap">↓ {fmtBps(vm.net_in_bps)}</div>
        <div className="mt-1 whitespace-nowrap border-t border-line-soft pt-1">
          ↑ {fmtBps(vm.net_out_bps)}
        </div>
      </td>
      {/* The actions are their own targets, never the row's: stopping the
          click here covers every control in the bar at once, including any
          added to it later, rather than trusting each one to stop its own. */}
      <td className={td} onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-end">
          <VmActionBar vm={vm} />
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
        closed VM runs no queries, which matters more here than on the Apps
        table because the panel lists snapshots. */}
    <tr>
      <td colSpan={8} className="p-0">
        <div className={`grid transition-[grid-template-rows] duration-200 ease-out
                         motion-reduce:transition-none ${open ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'}`}>
          <div className="overflow-hidden">
            {open && <div className="px-4 pb-4"><VmDetailPanel vm={vm} /></div>}
          </div>
        </div>
      </td>
    </tr>
    </>
  )
}

/** A bar and its percentage, AppTable's Meter to the pixel. Copied rather than
 *  shared because the two tables' rows are already twins by hand and a third
 *  file to hold six lines would be the only thing either page imported from
 *  it; if a third table ever wants one, lift it then. */
/** Why a VM's storage reads unknown. Written out in full because the reader's
 *  next question is always "so what do I do about it", and "no guest agent" on
 *  its own does not answer it. */
const NO_AGENT = 'Proxmox can only see the size of the disk, not how full it is. '
               + 'Install the QEMU guest agent in this VM to report its real usage.'

/** Identical to AppTable's Meter, deliberately: the two tables draw the same
 *  columns and a divergence here would show up as one row rhythm on Apps and
 *  another on VMs. The "no reading" case does not come through here at all,
 *  see the storage cell above. */
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
 *  when the VMs land. Edited with VmTableRow, never separately. */
export function VmTableSkeleton({ rows = 4 }: { rows?: number }) {
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
              <td className={td}><Skeleton className="ms-auto h-6 w-44 rounded-ctl" /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
