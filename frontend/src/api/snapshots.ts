import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'
import type { ApiError } from './client'
import type { JobRow } from './jobs'

/** PVE's own snapshot shape (doc 05: "List snapshots (live from Proxmox)"). */
export type SnapshotRow = {
  name: string
  description: string | null
  /** Unix seconds. Null on the synthetic `current` row. */
  snaptime: number | null
  /** true = the RAM state was captured alongside the disk (qemu only). */
  vmstate: boolean
  parent: string | null
  // PVE does not report a per-snapshot size for every storage plugin (LVM-thin
  // and ZFS internal snapshots have no standalone size), so this is optional on
  // purpose: doc 06 row 48's Size column renders "—" rather than a fake number.
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
 * All three snapshot operations fire jobs, so they follow useLifecycle's
 * onSettled rule: invalidate ['jobs'] and ['cluster','activity'].
 *
 * They ALSO invalidate ['vms', id, 'snapshots'], which useLifecycle deliberately
 * does not do for ['vms'] — and the difference is real, not an inconsistency.
 * ['vms'] is the poller's 30s resource cache holding an optimistic `pending`
 * patch that a refetch would stomp with stale data. ['vms', id, 'snapshots'] is
 * a live read straight off Proxmox with no optimistic patch to protect, so a
 * refetch can only move it closer to the truth. It is best-effort at enqueue
 * time (the job has only been accepted); the terminal `job` SSE delta
 * invalidates the ['vms'] prefix — which matches this key too — and is the
 * backstop that actually shows the finished result.
 */
export function useSnapshotAction() {
  const qc = useQueryClient()
  return useMutation<{ job: JobRow }, ApiError, SnapshotVars>({
    mutationFn: request,
    onSettled: (_data, _err, v) => {
      qc.invalidateQueries({ queryKey: ['jobs'] })
      qc.invalidateQueries({ queryKey: ['cluster', 'activity'] })
      qc.invalidateQueries({ queryKey: ['vms', v.vmId, 'snapshots'] })
    },
  })
}
