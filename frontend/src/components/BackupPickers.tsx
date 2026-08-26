/**
 * The hooks share the query keys the Apps, VMs and Storage pages already use,
 * so a dialog that opens over any of them costs no request at all.
 */
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import type { AppRow, VmRow } from '../api/hooks'
import { useStorage } from '../api/storage'
import type { StorageRow } from '../api/storage'
import { servedTo } from './install/pools'

export type Guest = {
  /** Stable across a re-render and unique across the two kinds. */
  key: string
  /** Proxploy row ids, which is what POST /backups/run's `guests` takes. */
  type: 'app' | 'vm'
  id: number
  /** The PVE id, which is what a scheduled job's `vmids` param takes. */
  vmid: number
  label: string
}

/** Every container and virtual machine on one host, in the shape both callers
 *  need. An app IS a container, so it belongs in this list next to the VMs. */
export function useHostGuests(hostId: number | null) {
  const apps = useQuery({ queryKey: ['apps', {}], queryFn: () => api<AppRow[]>('/apps') })
  const vms = useQuery({ queryKey: ['vms', {}], queryFn: () => api<VmRow[]>('/vms') })
  const guests: Guest[] = hostId == null ? [] : [
    ...(apps.data ?? []).filter((a) => a.host_id === hostId).map((a) => ({
      key: `app:${a.id}`, type: 'app' as const, id: a.id, vmid: a.ctid,
      label: `${a.name} (CT ${a.ctid})`,
    })),
    ...(vms.data ?? []).filter((v) => v.host_id === hostId).map((v) => ({
      key: `vm:${v.id}`, type: 'vm' as const, id: v.id, vmid: v.vmid,
      label: `${v.name} (VM ${v.vmid})`,
    })),
  ]
  // Nothing is concluded while these are in flight: an empty list means "not
  // fetched yet" exactly as readily as "nothing there".
  return { guests, pending: apps.isPending || vms.isPending }
}

/** The datastores on one host that vzdump can actually write to.
 *
 *  `servedTo`, not `s.host_id === hostId`: GET /storage drops host_id from its
 *  dedupe key, so on a cluster every row comes back owned by whichever host
 *  polled first and the others match nothing at all. */
export function useBackupStores(hostId: number | null, clusterName?: string | null) {
  const storage = useStorage()
  const stores: StorageRow[] = hostId == null ? []
    : (storage.data ?? []).filter((s) =>
        servedTo(s, hostId, clusterName ?? null) && s.content.includes('backup'))
  return { stores, pending: storage.isPending }
}

/**
 * The guest tick list. `selected` is null for "everything on this host",
 * which is not the same fact as "every box happens to be ticked": it is what
 * lets the caller keep sending `guests: "all"` so a guest created between the
 * form opening and the job firing is still included.
 */
export function GuestPicker({ guests, selected, onChange, idPrefix }: {
  guests: Guest[]
  selected: Set<string> | null
  onChange: (next: Set<string> | null) => void
  idPrefix: string
}) {
  const ticked = selected ?? new Set(guests.map((g) => g.key))
  const all = ticked.size === guests.length
  return (
    <div>
      <div className="mb-1 flex items-center justify-between">
        <span className="text-[11px] uppercase tracking-wide text-text-3">What to back up</span>
        <button type="button" className="text-[11.5px] text-text-3 underline hover:text-text-2"
                onClick={() => onChange(all ? new Set() : null)}>
          {all ? 'Clear' : 'Select all'}
        </button>
      </div>
      <div className="max-h-40 overflow-y-auto rounded-ctl border border-line bg-panel-2 px-3 py-2">
        {guests.map((g) => (
          <label key={g.key} htmlFor={`${idPrefix}-${g.key}`}
                 className="flex items-center gap-2 py-0.5 text-[13px]">
            <input id={`${idPrefix}-${g.key}`} type="checkbox" checked={ticked.has(g.key)}
                   onChange={() => {
                     const next = new Set(ticked)
                     if (!next.delete(g.key)) next.add(g.key)
                     // Back to null, not a full set: see the doc comment.
                     onChange(next.size === guests.length ? null : next)
                   }} />
            <span>{g.label}</span>
          </label>
        ))}
      </div>
      <span className="mt-1 block text-[11.5px] text-text-3">
        {ticked.size === 0 ? 'Nothing selected, so nothing would be backed up.'
          : all ? `All ${guests.length} on this host, including any added later.`
            : `${ticked.size} of ${guests.length} selected.`}
      </span>
    </div>
  )
}
