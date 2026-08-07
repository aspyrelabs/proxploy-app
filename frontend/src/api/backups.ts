// api/backups.ts, Backups page server state (doc 05 §Backups, doc 06 §a row 45).
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, ApiError } from './client'
import type { JobRow } from './jobs'

export type BackupRow = {
  id: number
  host_id: number
  host_name: string | null
  storage: string | null
  volid: string
  guest_type: string | null
  guest_vmid: number | null
  guest_name: string | null
  taken_at: string | null
  size_bytes: number | null
  verify_state: string | null
  notes: string | null
}

export type Datastore = { storage: string; count: number; size_bytes: number }

export type BackupStats = {
  total: number
  total_bytes: number
  ok_count: number
  failed_count: number
  /** null when nothing in the window was verified, never a fake 100%. */
  success_rate_30d: number | null
  datastores: Datastore[]
}

export type BackupsResponse = {
  backups: BackupRow[]
  stats: BackupStats
  synced_at: string | null
  stale: boolean
}

export type PruneRow = {
  volid: string
  type: string | null
  vmid: number | null
  ctime: number | null
  mark: 'keep' | 'remove' | 'protected'
}

/**
 * The list is served from the `backups` cache table; GET /backups enqueues its
 * own `backup.sync` when that cache is stale, so this hook never has to.
 */
export function useBackups() {
  return useQuery({
    queryKey: ['backups'],
    queryFn: () => api<BackupsResponse>('/backups'),
    refetchInterval: 30_000,
  })
}

// Every mutation below fires a job. Per api/jobs.ts::useLifecycle's documented
// rule they invalidate ['jobs'] and ['cluster','activity'] only, never
// ['backups'] on success. The handler's own `_resync` + the `resource`
// {type:'backup'} SSE delta are what refresh the list, once the archive
// actually exists upstream rather than while the job is still queued.
const jobSettled = (qc: ReturnType<typeof useQueryClient>) => () => {
  qc.invalidateQueries({ queryKey: ['jobs'] })
  qc.invalidateQueries({ queryKey: ['cluster', 'activity'] })
}

export function useRunBackup() {
  const qc = useQueryClient()
  return useMutation<{ job: JobRow }, ApiError, { hostId: number | null }>({
    mutationFn: (v) =>
      api<{ job: JobRow }>('/backups/run', {
        method: 'POST',
        body: JSON.stringify({ guests: 'all', ...(v.hostId ? { host_id: v.hostId } : {}) }),
      }),
    onSettled: jobSettled(qc),
  })
}

export type RestoreVars = { id: number; mode: 'new' | 'in_place'; confirm?: string }

export function useRestoreBackup() {
  const qc = useQueryClient()
  return useMutation<{ job: JobRow }, ApiError, RestoreVars>({
    mutationFn: (v) =>
      api<{ job: JobRow }>(`/backups/${v.id}/restore`, {
        method: 'POST',
        body: JSON.stringify(v.confirm ? { mode: v.mode, confirm: v.confirm } : { mode: v.mode }),
      }),
    onSettled: jobSettled(qc),
  })
}

export function useDeleteBackup() {
  const qc = useQueryClient()
  return useMutation<{ job: JobRow }, ApiError, number>({
    mutationFn: (id) => api<{ job: JobRow }>(`/backups/${id}`, { method: 'DELETE' }),
    onSettled: jobSettled(qc),
  })
}

export type PruneParams = {
  hostId: number
  storage: string
  keepLast: number
  keepDaily: number
}

/** Dry run. GET only, the destructive verb lives on POST /backups/prune. */
export function usePrunePreview(p: PruneParams | null) {
  return useQuery({
    queryKey: ['backups', 'prune-preview', p],
    enabled: p != null,
    retry: false,
    staleTime: 0,
    queryFn: () =>
      api<PruneRow[]>(`/backups/prune-preview?host_id=${p!.hostId}` +
        `&storage=${encodeURIComponent(p!.storage)}` +
        `&keep_last=${p!.keepLast}&keep_daily=${p!.keepDaily}`),
  })
}
