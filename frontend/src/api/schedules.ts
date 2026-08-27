import { useQuery } from '@tanstack/react-query'
import { api } from './client'
import type { JobRow } from './jobs'

export type ScheduleLastRun = {
  job_id: number; status: string; error: string | null
  started_at: string | null; finished_at: string | null; created_at: string
}

export type ScheduleRow = {
  id: number; name: string; job_kind: string; cron: string; timezone: string
  params: Record<string, unknown>; enabled: boolean
  created_by: number | null           // null = a schedule Proxploy seeded itself
  last_run_at: string | null; next_run_at: string | null
  last_run: ScheduleLastRun | null
}

/** Job kinds worth offering in the UI. Deliberately not every registered
 *  handler: `vm.delete` on a cron is not a feature, it is a foot-gun. The
 *  backend accepts any registered kind, so this list is the curated surface,
 *  not the security boundary.
 *
 *  ponytail: `backup.prune` is left out on purpose, its handler
 *  (backupjobs.py) hard-requires `params.storage`/`params.spec`, which this
 *  form has no fields for, so scheduling it would create cleanly and then
 *  KeyError at every fire. Add it once the form grows a datastore + keep-rule
 *  picker (the retention-preview UI on the Backups page is the model). */
export const BACKUP_KINDS = ['backup.run', 'backup.verify']

export const SCHEDULABLE: { kind: string; label: string; needs: 'host' | 'app' | null }[] = [
  // Spelled out rather than "Backup guests on a host": on the Settings page
  // this label is the only description of the job, and "guests" is Proxmox's
  // word, not an operator's.
  { kind: 'backup.run', label: 'Back up every container and VM on a host', needs: 'host' },
  // Spelled as what the schedule does, not as the job kind: on the Settings
  // page this label is the whole description of the schedule.
  { kind: 'backup.verify', label: "Verify a host's backups are readable", needs: 'host' },
  { kind: 'app.update', label: 'Update an app', needs: 'app' },
  { kind: 'catalog.refresh', label: 'Refresh the app catalog', needs: null },
  { kind: 'metrics.maintain', label: 'Roll up and prune metrics', needs: null },
  { kind: 'sessions.cleanup', label: 'Remove expired sign-ins and console tickets', needs: null },
  { kind: 'jobs.prune', label: 'Delete job history older than the keep window', needs: null },
  { kind: 'db.compact', label: 'Reclaim unused database space', needs: null },
  { kind: 'update.check', label: 'Check for a new Proxploy release', needs: null },
]

export function useSchedules() {
  return useQuery({
    queryKey: ['schedules'],
    queryFn: () => api<ScheduleRow[]>('/schedules'),
  })
}

export function useScheduleRuns(scheduleId: number | null) {
  return useQuery({
    queryKey: ['schedule-runs', scheduleId],
    enabled: scheduleId != null,
    queryFn: () => api<JobRow[]>('/schedules/' + scheduleId + '/runs'),
  })
}
