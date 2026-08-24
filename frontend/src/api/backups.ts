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
  /** null when nothing in the window was verified, never a fake 100%. Only
   *  Proxmox Backup Server ever verifies an archive, so this stays null for
   *  the whole life of a PVE-only setup and the three below are what the card
   *  falls back to. */
  success_rate_30d: number | null
  /** `backup.run` jobs in the same 30 days: an archive was written, which is
   *  a weaker claim than "it verified" and is labelled as one. */
  runs_ok_30d: number
  runs_failed_30d: number
  run_rate_30d: number | null
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

/**
 * `storage` is sent, not left out. POST /backups/run defaults it to null and
 * vzdump then writes to whichever backup store PVE picks, so the operator had
 * no way to know where the archive landed: the same class of problem the
 * migration preflight had before it started naming its target pool, and the
 * reason services/backupjobs.py::restore_backup stopped letting PVE guess.
 * The dialog chooses from the stores that actually carry `backup` content and
 * says which one, so "where did it go" is answered before the run.
 */
export type BackupGuest = { type: 'app' | 'vm'; id: number }

/**
 * `guests` defaults to `'all'` (the host-wide run routes/backups.tsx has
 * always fired), so that page's call site needed no change at all. Passing
 * an explicit list is the one-app dialog's job: backend `_resolve_guests`
 * requires every guest in the list to share one host, which a single app
 * always does, so there is nothing this hook needs to check on the caller's
 * behalf.
 */
export function useRunBackup() {
  const qc = useQueryClient()
  return useMutation<{ job: JobRow }, ApiError,
    { hostId: number | null; storage?: string | null; guests?: BackupGuest[] }>({
    mutationFn: (v) =>
      api<{ job: JobRow }>('/backups/run', {
        method: 'POST',
        body: JSON.stringify({
          guests: v.guests ?? 'all',
          ...(v.hostId ? { host_id: v.hostId } : {}),
          ...(v.storage ? { storage: v.storage } : {}),
        }),
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

/**
 * POST /backups/prune. Always fired with the exact PruneParams the preview
 * above was computed from, never a second, independently-typed form. The
 * backend drops a 0/absent keep-* value from the retention spec itself and
 * 422s if that leaves none at all, so the caller (RetentionSection) gates
 * the button on at least one of these being >= 1 before this ever fires.
 */
export function usePrune() {
  const qc = useQueryClient()
  return useMutation<{ job: JobRow }, ApiError, PruneParams>({
    mutationFn: (p) =>
      api<{ job: JobRow }>('/backups/prune', {
        method: 'POST',
        body: JSON.stringify({
          host_id: p.hostId, storage: p.storage,
          keep_last: p.keepLast, keep_daily: p.keepDaily,
        }),
      }),
    onSettled: jobSettled(qc),
  })
}
