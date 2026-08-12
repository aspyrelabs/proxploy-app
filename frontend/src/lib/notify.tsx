import { toast } from 'sonner'
import { NotificationCard } from '../components/ui/notification-card'
import type { NotificationSeverity } from '../components/ui/notification-card'

/** The one place every toast in the app goes through. Before this, LiveProvider's
 *  SSE job/alert events rendered NotificationCard via `toast.custom`, while every
 *  other call site used sonner's plain toast.success/toast.error/toast.info
 *  directly, so the bottom-right corner showed two different designs. Now
 *  everything, LiveProvider included, calls through here instead of pasting
 *  `toast.custom(...)` at each site. */

type NotifyOptions = {
  /** The reason, detail, or extra context beneath the title. Passed straight
   *  through to NotificationCard's own `description`, so it is never
   *  clamped: see that prop's comment for why. */
  description?: string
}

function show(severity: NotificationSeverity, title: string, options?: NotifyOptions) {
  return toast.custom((id) => (
    <NotificationCard
      severity={severity}
      title={title}
      description={options?.description}
      onDismiss={() => toast.dismiss(id)}
    />
  ))
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
   *  (jobToastSeverity/alertToastSeverity in api/live.ts), so they call
   *  straight through here instead of mapping that back to one of the four
   *  names above. */
  custom: (severity: NotificationSeverity, title: string, options?: NotifyOptions) =>
    show(severity, title, options),
}
