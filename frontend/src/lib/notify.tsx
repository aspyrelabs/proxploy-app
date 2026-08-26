import { pushAction } from './notificationStore'
import type { NotifySeverity } from './notificationStore'

/** The one place every action notification in the app goes through
 *  (notify.success/error/info/warning, plus notify.custom for
 *  LiveProvider's already-known severities). Pushes into
 *  lib/notificationStore.ts, the memory the bell tray (BellPopover) and the
 *  under-the-bell banner (NotificationSurface) both read.
 *
 *  The exported names and signatures are unchanged from before this file
 *  moved off sonner: some callers are mid-migration to this helper and must
 *  keep compiling against it exactly as it already was. */

export type { NotifySeverity as NotificationSeverity } from './notificationStore'

type NotifyOptions = {
  /** The reason, detail, or extra context beneath the title. Never clamped. */
  description?: string
}

function show(severity: NotifySeverity, title: string, options?: NotifyOptions) {
  pushAction(severity, title, options?.description)
}

export const notify = {
  success: (title: string, options?: NotifyOptions) => show('success', title, options),
  // sonner's naming ('error') and the card's severity naming ('destructive')
  // never lined up; callers keep writing notify.error.
  error: (title: string, options?: NotifyOptions) => show('destructive', title, options),
  info: (title: string, options?: NotifyOptions) => show('info', title, options),
  warning: (title: string, options?: NotifyOptions) => show('warning', title, options),
  /** For callers that already have a severity in hand and nothing to dedupe.
   *  Job and alert events push straight into the store with their own id
   *  (notificationStore.pushJobEvent/pushAlertEvent) so they can be deduped
   *  against GET /jobs. */
  custom: (severity: NotifySeverity, title: string, options?: NotifyOptions) =>
    show(severity, title, options),
}
