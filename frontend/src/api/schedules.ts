import { useQuery } from '@tanstack/react-query'
import { api } from './client'

export type ScheduleRow = {
  id: number; name: string; job_kind: string; cron: string; timezone: string
  params: Record<string, unknown>; enabled: boolean
  created_by: number | null           // null = a schedule Proxploy seeded itself
  last_run_at: string | null; next_run_at: string | null
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
export const SCHEDULABLE: { kind: string; label: string; needs: 'host' | 'app' | null }[] = [
  // Spelled out rather than "Backup guests on a host": on the Settings page
  // this label is the only description of the job, and "guests" is Proxmox's
  // word, not an operator's.
  { kind: 'backup.run', label: 'Back up every container and VM on a host', needs: 'host' },
  { kind: 'app.update', label: 'Update an app', needs: 'app' },
  { kind: 'catalog.refresh', label: 'Refresh the app catalog', needs: null },
  { kind: 'metrics.maintain', label: 'Roll up and prune metrics', needs: null },
]

export function useSchedules() {
  return useQuery({
    queryKey: ['schedules'],
    queryFn: () => api<ScheduleRow[]>('/schedules'),
  })
}
