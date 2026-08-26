import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'
import type { ApiError } from './client'
import type { JobRow } from './jobs'

/** PVE's own snapshot shape (live from Proxmox). */
export type SnapshotRow = {
  name: string
  description: string | null
  /** Unix seconds. Null on the synthetic `current` row. */
  snaptime: number | null
  /** true = the RAM state was captured alongside the disk (qemu only). */
  vmstate: boolean
  parent: string | null
  // PVE reports no per-snapshot size for every storage plugin (LVM-thin and
  // ZFS internal snapshots have no standalone size), so this is optional.
  size_bytes?: number | null
}

export type SnapshotVars = {
  vmId: number
  op: 'create' | 'rollback' | 'delete'
  name: string
  description?: string
  vmstate?: boolean
  confirm?: string
}

export function useSnapshots(vmId: number) {
  return useQuery({
    queryKey: ['vms', vmId, 'snapshots'],
    queryFn: () => api<SnapshotRow[]>(`/vms/${vmId}/snapshots`),
  })
}

function request(v: SnapshotVars) {
  const base = `/vms/${v.vmId}/snapshots`
  if (v.op === 'create') {
    return api<{ job: JobRow }>(base, {
      method: 'POST',
      body: JSON.stringify({ name: v.name, description: v.description ?? '', vmstate: !!v.vmstate }),
    })
  }
  const one = `${base}/${encodeURIComponent(v.name)}`
  if (v.op === 'rollback') {
    return api<{ job: JobRow }>(`${one}/rollback`, {
      method: 'POST',
      body: JSON.stringify(v.confirm ? { confirm: v.confirm } : {}),
    })
  }
  return api<{ job: JobRow }>(one, { method: 'DELETE' })
}

/**
 * All three operations fire jobs, so invalidate ['jobs'] (useLifecycle's
 * onSettled rule).
 *
 * Also invalidate ['vms', id, 'snapshots'] — a live Proxmox read with no
 * optimistic patch, so a refetch only moves it closer to the truth. Do NOT
 * invalidate ['vms']: that is the poller's 30s cache holding an optimistic
 * `pending` patch a refetch would stomp with stale data. The terminal `job`
 * SSE delta invalidates the ['vms'] prefix (which matches this key too) and is
 * the backstop that shows the finished result.
 */
export function useSnapshotAction() {
  const qc = useQueryClient()
  return useMutation<{ job: JobRow }, ApiError, SnapshotVars>({
    mutationFn: request,
    onSettled: (_data, _err, v) => {
      qc.invalidateQueries({ queryKey: ['jobs'] })
      qc.invalidateQueries({ queryKey: ['vms', v.vmId, 'snapshots'] })
    },
  })
}
