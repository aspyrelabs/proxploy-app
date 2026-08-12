import { useNavigate } from '@tanstack/react-router'
import type { AppRow, VmRow } from '../api/hooks'
import { fmtBytes, fmtPct } from '../lib/format'
import { LifecycleActions } from './LifecycleActions'
import { StatusPill } from './StatusPill'
import { Button } from './ui/button'
import { CPU_GRADIENT, UsageBar } from './UsageBar'

export type Guest = {
  kind: 'app' | 'vm'
  id: number
  name: string
  /** "CT 104" / "VM 201": the id an operator actually types. */
  label: string
  status: string
  cpu_pct: number | null
  /** Pre-formatted, because only the app side has a total to divide by. */
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
      kind: 'app', id: a.id, name: a.name, label: `CT ${a.ctid}`,
      status: a.status, cpu_pct: a.cpu_pct,
      mem: a.mem_total_bytes
        ? `${fmtBytes(a.mem_bytes)} / ${fmtBytes(a.mem_total_bytes)}`
        : fmtBytes(a.mem_bytes),
      update: a.update_available,
    })),
    ...vms.map((v): Guest => ({
      kind: 'vm', id: v.id, name: v.name, label: `VM ${v.vmid}`,
      status: v.status, cpu_pct: v.cpu_pct,
      // No mem_total_bytes on VmRow. Inventing one to make the two rows match
      // would be making up a number.
      mem: fmtBytes(v.mem_bytes),
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

function GuestRow({ guest: g }: { guest: Guest }) {
  const navigate = useNavigate()
  const detail = g.kind === 'app' ? '/apps/$appId' : '/vms/$vmId'
  const consolePath = g.kind === 'app' ? '/apps/$appId/console' : '/vms/$vmId/console'
  const params = g.kind === 'app'
    ? { appId: String(g.id) }
    : { vmId: String(g.id) }
  return (
    <div role="listitem"
      className="flex flex-wrap items-center gap-x-3 gap-y-2 border-t border-line-soft
                    px-4 py-3 first:border-t-0">
      {/* basis-full below sm puts the name on its own line and lets the id,
          status and usage wrap beneath it; sm:basis-auto resolves the row. */}
      <button type="button"
        className="min-w-0 basis-full text-left font-mono text-[13px] text-text
                   transition hover:text-amber sm:basis-auto"
        onClick={() => navigate({ to: detail as never, params: params as never })}>
        {g.name}
      </button>
      <span className="rounded-full border border-line-soft bg-panel-2 px-2 py-0.5
                       font-mono text-[10px] uppercase text-text-2">
        {g.kind}
      </span>
      <span className="font-mono text-[11px] text-text-3">{g.label}</span>
      {g.update && (
        <span className="rounded bg-amber-dim px-1.5 py-0.5 font-mono text-[9.5px]
                         uppercase text-amber">
          update
        </span>
      )}
      <StatusPill status={g.status} />
      <div className="flex w-28 items-center gap-2">
        <div className="flex-1"><UsageBar pct={g.cpu_pct} gradient={CPU_GRADIENT} /></div>
        <span className="w-9 text-right font-mono text-[11px] text-text-2">{fmtPct(g.cpu_pct)}</span>
      </div>
      <span className="font-mono text-[11px] text-text-2">{g.mem}</span>
      <div className="ml-auto flex items-center gap-2">
        <LifecycleActions target={g.kind} id={g.id} name={g.name} status={g.status} size="sm" />
        <Button variant="ghost" className="px-2 py-1 text-[11px]"
          onClick={() => navigate({ to: consolePath as never, params: params as never })}>
          Console
        </Button>
      </div>
    </div>
  )
}
