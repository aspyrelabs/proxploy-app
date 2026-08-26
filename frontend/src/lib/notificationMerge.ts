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
 * Merge server sources (GET /jobs, GET /alerts?state=firing — survive reload)
 * with the client-side store (action notifications, SSE pushes — ephemeral).
 * `toJobItem` is a parameter so BellPopover's field helpers stay where they are.
 *
 * Dedup rule: an SSE-delivered job event lands in the store as `job:<id>`
 * before the next /jobs poll returns it. Once the poll catches up, the
 * server-side row wins (it's more current) and the store copy is dropped to
 * avoid double-rendering. A store entry whose job hasn't shown up in /jobs
 * yet is kept — dropping it would blink the notification out of the tray.
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
