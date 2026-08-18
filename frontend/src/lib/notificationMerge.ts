import type { JobRow } from '../api/jobs'
import type { NotifySeverity, StoreNotification } from './notificationStore'

/** One row the tray renders, whichever of the two sources it came from. */
export type TrayItem = {
  id: string
  severity: NotifySeverity
  title: string
  description?: string
  footer?: string
  progress?: number
  /** Present only for a job-backed item; lets BellPopover offer "View log"
   *  and lets a future merge dedupe against it again. */
  jobId?: number
  timestamp: number
}

/**
 * GET /jobs and GET /alerts?state=firing (server truth, both survive a reload)
 * merged with the client-side store (notify.tsx's action notifications,
 * LiveProvider's SSE job/alert pushes -- gone on reload). `toJobItem` builds a job's card fields; it is a
 * parameter rather than baked in here so BellPopover's existing
 * severityOf/messageOf/footerOf/progressOf stay exactly where they are.
 *
 * The one rule this exists to enforce: a job's SSE-delivered terminal event
 * lands in the store the instant it arrives, keyed `job:<id>`
 * (notificationStore.pushJobEvent). The next time GET /jobs is polled, the
 * same job shows up there too. Once it does, the /jobs row wins -- it is the
 * server's own record, more current than the copy that arrived earlier over
 * SSE -- and the store's copy is dropped rather than rendered a second time.
 * A store entry whose job has not shown up in /jobs yet (SSE beat the next
 * poll) is kept: dropping it would mean a notification blinks out of
 * existence before the tray was ever opened to see it.
 */
export function mergeNotifications(
  jobs: JobRow[],
  storeItems: StoreNotification[],
  toJobItem: (job: JobRow) => TrayItem,
  alertItems: TrayItem[] = [],
): TrayItem[] {
  const jobIds = new Set(jobs.map((j) => j.id))
  // Same rule as jobs, one source up: LiveProvider pushes a firing alert into
  // the store as `alert:<id>:<ts>:<seq>` the moment its SSE event lands, and
  // GET /alerts?state=firing carries the same alert from then on. Server truth
  // wins and the store copy is dropped, so an alert does not render twice.
  // Without the server source at all, an alert that fired before the tab was
  // opened was in no tray anywhere, and a reload lost the ones that had.
  const alertPrefixes = alertItems
    .filter((a) => a.id.startsWith('alert:'))
    .map((a) => `${a.id.split(':').slice(0, 2).join(':')}:`)
  const fromStore: TrayItem[] = storeItems
    .filter((n) => n.jobId == null || !jobIds.has(n.jobId))
    .filter((n) => !alertPrefixes.some((prefix) => n.id.startsWith(prefix)))
    .map((n) => ({
      id: n.id,
      severity: n.severity,
      title: n.title,
      description: n.description,
      jobId: n.jobId,
      timestamp: n.createdAt,
    }))
  const fromJobs = jobs.map(toJobItem)
  return [...fromStore, ...alertItems, ...fromJobs]
    .sort((a, b) => b.timestamp - a.timestamp)
}
