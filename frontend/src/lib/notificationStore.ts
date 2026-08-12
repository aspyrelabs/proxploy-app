/**
 * The client-side memory both notification sources feed. notify.tsx pushes
 * an entry for every action notification (a mutation's "Saved."/"Could not
 * X" feedback); LiveProvider pushes one for every SSE `job` (terminal only)
 * and `alert` event it is entitled to show (its own `notify.inapp` gate
 * stays exactly where it was -- this store never sees a job/alert event that
 * gate would have suppressed).
 *
 * BellPopover reads this merged with GET /jobs (see notificationMerge.ts) so
 * server-side job history still appears after a reload; everything that only
 * lives here -- action notifications, and a job/alert event that hasn't been
 * confirmed by a /jobs poll yet -- is gone on reload, by design (see
 * one-notification-tray-report.md).
 *
 * A plain module-level store with a subscribe/getSnapshot pair rather than
 * React state: notify.*() and LiveProvider's SSE handlers both push from
 * outside any component's render, sometimes before BellPopover has ever
 * mounted, so there is no component instance to own this as state. React
 * reads it via useSyncExternalStore (see BellPopover.tsx / NotificationSurface.tsx).
 */

export type NotifySeverity = 'info' | 'success' | 'warning' | 'destructive'

export type StoreNotification = {
  id: string
  severity: NotifySeverity
  title: string
  description?: string
  /** Present only for a job-sourced entry (LiveProvider's `job` handler).
   *  This is what notificationMerge.ts dedupes on against GET /jobs, and
   *  what lets BellPopover offer "View log" once the /jobs row lands. */
  jobId?: number
  createdAt: number
}

type Listener = () => void

let items: StoreNotification[] = []
let trayOpen = false
// Module-load time, not epoch 0: a fresh page load has an empty badge (there
// is nothing "new" about a job that already existed before you opened the
// tab), not one inflated by every job in the cluster's history.
let lastSeenAt = Date.now()
let seq = 0
const listeners = new Set<Listener>()

function emit() {
  for (const l of listeners) l()
}

function nextId(prefix: string): string {
  seq += 1
  return `${prefix}:${Date.now()}:${seq}`
}

export function subscribeNotifications(listener: Listener): () => void {
  listeners.add(listener)
  return () => { listeners.delete(listener) }
}

export function getNotifications(): StoreNotification[] {
  return items
}

/** notify.*(): a mutation's own feedback. Never deduped against anything
 *  (there is no server record to dedupe against), never merged with /jobs. */
export function pushAction(severity: NotifySeverity, title: string, description?: string): void {
  items = [{ id: nextId('action'), severity, title, description, createdAt: Date.now() }, ...items]
  emit()
}

/** LiveProvider's `job` SSE handler, terminal deltas only (applyJob only
 *  calls its toast callback once a job reaches a terminal state). Keyed on
 *  the job id rather than a fresh id every time: SSE has no replay/dedup
 *  (see applyJob's own comment), so a duplicate delivery of the same
 *  terminal delta updates this entry in place instead of adding a second
 *  one -- the first half of "a job appears once"; notificationMerge.ts is
 *  the other half, against GET /jobs. */
export function pushJobEvent(
  jobId: number, severity: NotifySeverity, title: string, description?: string,
): void {
  const id = `job:${jobId}`
  const entry: StoreNotification = { id, severity, title, description, jobId, createdAt: Date.now() }
  items = [entry, ...items.filter((i) => i.id !== id)]
  emit()
}

/** LiveProvider's `alert` SSE handler. A firing alert and its later
 *  resolution are two different facts and stay two different notifications
 *  (mirrors applyAlert's own behaviour: a resolution always toasts,
 *  whatever the severity that was firing). */
export function pushAlertEvent(
  alertId: number, severity: NotifySeverity, title: string, description?: string,
): void {
  items = [{ id: nextId(`alert:${alertId}`), severity, title, description, createdAt: Date.now() }, ...items]
  emit()
}

export function removeNotification(id: string): void {
  items = items.filter((i) => i.id !== id)
  emit()
}

export function clearNotifications(): void {
  items = []
  emit()
}

/** BellPopover calls this from the popover's own onOpenChange. Opening marks
 *  "now" as seen (the badge's unread count is everything newer than this);
 *  closing just records the state so NotificationSurface knows not to render
 *  on top of an open tray. */
export function setTrayOpen(open: boolean): void {
  trayOpen = open
  if (open) lastSeenAt = Date.now()
  emit()
}

export function isTrayOpen(): boolean {
  return trayOpen
}

export function getLastSeenAt(): number {
  return lastSeenAt
}

/** Test-only: every test file that touches this module-level store resets it
 *  in beforeEach, since vitest keeps the same module instance across tests
 *  in one file. */
export function resetNotificationStore(): void {
  items = []
  trayOpen = false
  lastSeenAt = Date.now()
  seq = 0
}
