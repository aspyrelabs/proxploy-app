import { useNavigate } from '@tanstack/react-router'
import type { AppRow, VmRow } from '../api/hooks'
import { fmtBytes, fmtPct } from '../lib/format'
import { openConsoleWindow } from '../lib/console-window'
import { ConsoleButton, LifecycleActions } from './LifecycleActions'
import { StatusPill } from './StatusPill'
import { linkCls } from './ui/button'
import { UpdateDot } from './UpdateDot'
import { Skeleton, SkeletonLine } from './ui/skeleton'
import { CPU_GRADIENT, UsageBar } from './UsageBar'

export type Guest = {
  kind: 'app' | 'vm'
  id: number
  host_id: number
  name: string
  /** "CT 104" / "VM 201": the id an operator actually types. */
  label: string
  status: string
  cpu_pct: number | null
  /** Pre-formatted: both sides now report used and allocated memory, but the
   *  total is still nullable on either, so the "x / y" or bare "x" choice is
   *  made once per guest here rather than in the row. */
  mem: string
  /** AppRow.update_available carried through; null on the VM side, which has
   *  no update concept. */
  update?: string | null
}

/** Apps first, then VMs: the host page lists what Proxploy installed before
 *  what it merely found. Within each kind the server's order is kept. */
export function toGuests(apps: AppRow[], vms: VmRow[]): Guest[] {
  return [
    ...apps.map((a): Guest => ({
      kind: 'app', id: a.id, host_id: a.host_id, name: a.name, label: `CT ${a.ctid}`,
      status: a.status, cpu_pct: a.cpu_pct,
      mem: a.mem_total_bytes
        ? `${fmtBytes(a.mem_bytes)} / ${fmtBytes(a.mem_total_bytes)}`
        : fmtBytes(a.mem_bytes),
      update: a.update_available,
    })),
    ...vms.map((v): Guest => ({
      kind: 'vm', id: v.id, host_id: v.host_id, name: v.name, label: `VM ${v.vmid}`,
      status: v.status, cpu_pct: v.cpu_pct,
      // The same "used / allocated" the app rows above get, and for the first
      // time the same meaning behind it: a VM's mem_bytes used to be the
      // memory ASSIGNED, so this line printed an allocation where the app
      // lines printed a usage and the column read as two different numbers.
      mem: v.mem_total_bytes
        ? `${fmtBytes(v.mem_bytes)} / ${fmtBytes(v.mem_total_bytes)}`
        : fmtBytes(v.mem_bytes),
      // VmRow has no update concept at all: not "no update available", but
      // nothing to report either way.
      update: null,
    })),
  ]
}

/** One row shape for both kinds of guest.
 *
 *  This replaces an AppCard grid beside a bare three-column VM table. The
 *  unification goes upward on purpose: VMs gain the CPU bar, the lifecycle
 *  controls and the console that apps already had, rather than apps being
 *  flattened to name/id/status to match the VMs. */
export function GuestList({ guests }: { guests: Guest[] }) {
  return (
    <div role="list" className="rounded-card border border-line-soft bg-panel">
      {guests.map((g) => <GuestRow key={`${g.kind}-${g.id}`} guest={g} />)}
    </div>
  )
}

/** The same list box with the same row rhythm, for the moment before
 *  /apps?host= and /vms?host= have both answered. Co-located with GuestRow so
 *  the two move together: this mirrors the row's OUTER box (px-4 py-3 between
 *  border-t rules) and the pieces tall enough to set its height, which is what
 *  decides whether the page below shifts when the guests land. */
export function GuestListSkeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div className="rounded-card border border-line-soft bg-panel">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="flex flex-wrap items-center gap-x-3 gap-y-2
                                border-t border-line-soft px-4 py-3 first:border-t-0">
          <SkeletonLine className="w-28 basis-full text-[13px] sm:basis-auto" />
          {/* The kind chip: px-2 py-0.5 around a 10px line box. */}
          <Skeleton className="h-[20.5px] w-11 rounded-full" />
          <SkeletonLine className="w-14 text-[11px]" />
          {/* StatusPill, the same 19px AppCardSkeleton derives. */}
          <Skeleton className="h-[19px] w-20 rounded-full" />
          <div className="flex w-28 items-center gap-2">
            <div className="flex-1"><Skeleton className="h-1.5 w-full rounded-full" /></div>
            <SkeletonLine className="w-9 text-[11px]" />
          </div>
          <SkeletonLine className="w-24 text-[11px]" />
          {/* LifecycleActions at size="sm", then the Console ghost. */}
          <div className="ms-auto flex items-center gap-2">
            <Skeleton className="h-[30px] w-24 rounded-ctl" />
            <Skeleton className="h-6 w-16 rounded-ctl" />
          </div>
        </div>
      ))}
    </div>
  )
}

function GuestRow({ guest: g }: { guest: Guest }) {
  const navigate = useNavigate()
  // Neither kind has a detail page any more: both are a row that expands on
  // its own table, and `open` is which one. Same search param on both sides,
  // different table.
  const open = () => navigate(g.kind === 'app'
    ? { to: '/apps' as never, search: { open: g.id } as never }
    : { to: '/vms' as never, search: { open: g.id } as never })
  return (
    <div role="listitem"
      className="flex flex-wrap items-center gap-x-3 gap-y-2 border-t border-line-soft
                    px-4 py-3 first:border-t-0">
      {/* basis-full below sm puts the name on its own line and lets the id,
          status and usage wrap beneath it; sm:basis-auto resolves the row. */}
      <button type="button"
        className={`min-w-0 basis-full text-left font-mono text-[13px] sm:basis-auto ${linkCls}`}
        onClick={open}>
        {g.name}
      </button>
      <span className="rounded-full border border-line-soft bg-panel-2 px-2 py-0.5
                       font-mono text-[10px] uppercase text-text-2">
        {g.kind}
      </span>
      <span className="font-mono text-[11px] text-text-3">{g.label}</span>
      {g.update && <UpdateDot />}
      <StatusPill status={g.status} />
      <div className="flex w-28 items-center gap-2">
        <div className="flex-1"><UsageBar pct={g.cpu_pct} gradient={CPU_GRADIENT} /></div>
        <span className="w-9 text-right font-mono text-[11px] text-text-2">{fmtPct(g.cpu_pct)}</span>
      </div>
      <span className="font-mono text-[11px] text-text-2">{g.mem}</span>
      <div className="ml-auto flex items-center gap-2">
        <LifecycleActions target={g.kind} id={g.id} name={g.name} status={g.status} hostId={g.host_id} size="sm" />
        {/* A window of its own, never a route: the in-page console tabs are
            gone (lib/console-window.ts). g.kind is already 'app' | 'vm', which
            is exactly the ConsoleKind the opener takes. */}
        <ConsoleButton hostId={g.host_id}
          onClick={() => openConsoleWindow(g.kind, g.id)} />
      </div>
    </div>
  )
}
