import { pushAction } from './notificationStore'
import type { NotifySeverity } from './notificationStore'

/** The one place every action notification in the app goes through
 *  (notify.success/error/info/warning, plus notify.custom for
 *  LiveProvider's already-known severities). It used to render straight
 *  into sonner's toast.custom, the bottom-right corner's one card design;
 *  now it pushes into lib/notificationStore.ts instead, the memory the tray
 *  (BellPopover, top right, anchored to the bell) and the brief
 *  under-the-bell banner (NotificationSurface) both read. See
 *  .superpowers/sdd/one-notification-tray-report.md for why the bottom-right
 *  corner is gone.
 *
 *  The exported names and signatures are unchanged from before this file
 *  moved off sonner: HostPowerDialog.tsx, HostEditDialog.tsx and
 *  routes/hosts.tsx are mid-migration to this helper by a separate change
 *  and must keep compiling against it exactly as it already was. */

export type { NotifySeverity as NotificationSeverity } from './notificationStore'

type NotifyOptions = {
  /** The reason, detail, or extra context beneath the title. Never
   *  clamped: see notification-card.tsx's own comment on the prop for why. */
  description?: string
}

function show(severity: NotifySeverity, title: string, options?: NotifyOptions) {
  pushAction(severity, title, options?.description)
}

export const notify = {
  success: (title: string, options?: NotifyOptions) => show('success', title, options),
  // sonner's naming ('error') and the card's severity naming ('destructive')
  // never lined up; callers keep writing notify.error, same as toast.error
  // before it.
  error: (title: string, options?: NotifyOptions) => show('destructive', title, options),
  info: (title: string, options?: NotifyOptions) => show('info', title, options),
  warning: (title: string, options?: NotifyOptions) => show('warning', title, options),
  /** LiveProvider's SSE handlers already know the card severity up front
   *  (jobToastSeverity/alertToastSeverity in api/live.ts). Job and alert
   *  events push straight into the store with their own id (see
   *  notificationStore.pushJobEvent/pushAlertEvent) so they can be deduped
   *  against GET /jobs; this is for any other caller that already has a
   *  severity in hand and nothing to dedupe. */
  custom: (severity: NotifySeverity, title: string, options?: NotifyOptions) =>
    show(severity, title, options),
}
