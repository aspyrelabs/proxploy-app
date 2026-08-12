import { useEffect, useRef, useState } from 'react'
import {
  getNotifications, isTrayOpen, subscribeNotifications,
} from '../lib/notificationStore'
import type { StoreNotification } from '../lib/notificationStore'
import { NotificationCard } from './ui/notification-card'

/** How long a card sits under the bell before it collapses into the tray on
 *  its own. Errors linger longer: a "Saved." is confirmation you can glance
 *  past, a failure is something to actually read. */
const AUTO_COLLAPSE_MS: Record<StoreNotification['severity'], number> = {
  success: 4000,
  info: 4000,
  warning: 6000,
  destructive: 8000,
}

/**
 * The answer to "how does a new notification get seen without the user
 * clicking the bell": mounted once (AppShell), independent of the
 * `notify.inapp` entitlement that gates the tray itself (BellPopover) --
 * action notifications from notify.tsx fire for every user regardless of
 * that entitlement, same as they did through sonner before this change, so
 * this has to as well.
 *
 * The newest arrivals appear briefly near the bell, then collapse into the
 * tray on their own: nothing is lost, the card just stops floating on top of
 * the page. Three constraints shaped this over the alternative of briefly
 * auto-opening the popover itself:
 *  - It must never sit on top of the popover the user already opened by
 *    hand, which auto-opening cannot promise (this component instead simply
 *    renders nothing while the tray is open -- there is nothing to add, the
 *    user is already looking at the tray).
 *  - It must not steal focus. Auto-opening a Radix Popover does not move
 *    focus by itself, but reads as "the app just did something" in a way a
 *    quiet card under the bell does not; this is ambient information, not an
 *    interruption.
 *  - NotificationCard already renders role="alert" (an assertive live
 *    region) regardless of where it is hosted, so screen readers announce a
 *    new arrival here exactly as they did for the sonner toast this
 *    replaces -- no new ARIA pattern to get wrong.
 *
 * Whatever was already in the store when this mounts is history, not an
 * arrival, so it is seeded into `seen` up front rather than shown.
 */
export function NotificationSurface() {
  const [visible, setVisible] = useState<StoreNotification[]>([])
  const [trayOpen, setTrayOpenState] = useState(isTrayOpen())
  const seen = useRef<Set<string>>(new Set())
  const timers = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map())

  useEffect(() => {
    for (const item of getNotifications()) seen.current.add(item.id)

    return subscribeNotifications(() => {
      setTrayOpenState(isTrayOpen())
      const fresh = getNotifications().filter((i) => !seen.current.has(i.id))
      if (fresh.length === 0) return
      for (const item of fresh) {
        seen.current.add(item.id)
        const timer = setTimeout(() => {
          setVisible((v) => v.filter((x) => x.id !== item.id))
          timers.current.delete(item.id)
        }, AUTO_COLLAPSE_MS[item.severity])
        timers.current.set(item.id, timer)
      }
      setVisible((v) => [...fresh, ...v])
    })
  }, [])

  useEffect(() => {
    const map = timers.current
    return () => { for (const t of map.values()) clearTimeout(t) }
  }, [])

  function dismiss(id: string) {
    const timer = timers.current.get(id)
    if (timer) { clearTimeout(timer); timers.current.delete(id) }
    setVisible((v) => v.filter((x) => x.id !== id))
    // Only hides the transient card here -- the notification itself stays in
    // the store (and therefore the tray) exactly as if it had simply timed
    // out, so dismissing early never loses history the way clearing the
    // tray's own "Clear all" does; see BellPopover.tsx.
  }

  if (visible.length === 0 || trayOpen) return null

  return (
    <div className="pointer-events-none fixed right-4 top-16 z-40 flex flex-col items-end gap-2">
      {visible.map((item) => (
        <div key={item.id}
          className="pointer-events-auto opacity-100 transition-all duration-200 ease-out
                     starting:-translate-y-1 starting:opacity-0
                     motion-reduce:transition-none motion-reduce:duration-0">
          <NotificationCard
            severity={item.severity}
            title={item.title}
            description={item.description}
            onDismiss={() => dismiss(item.id)}
          />
        </div>
      ))}
    </div>
  )
}
