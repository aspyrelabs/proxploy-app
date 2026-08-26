import { useEffect, useRef, useState } from 'react'
import {
  getNotifications, isTrayOpen, subscribeNotifications,
} from '../lib/notificationStore'
import type { StoreNotification } from '../lib/notificationStore'
import { NotificationCard } from './ui/notification-card'

/** Auto-collapse delay under the bell; destructive errors linger longest. */
const AUTO_COLLAPSE_MS: Record<StoreNotification['severity'], number> = {
  success: 4000,
  info: 4000,
  warning: 6000,
  destructive: 8000,
}

/**
 * Surfaces new notifications near the bell without a click. Mounted once
 * (AppShell) and independent of the `notify.inapp` entitlement that gates the
 * tray (BellPopover) — action notifications from notify.tsx fire for every
 * user regardless of entitlement, so this must too.
 *
 * Renders nothing while the tray is open; whatever was already in the store
 * at mount is seeded into `seen`, not shown as an arrival.
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
    // Only hides the transient card; the notification stays in the store
    // (and tray) as if it had timed out, so early dismissal never loses
    // history the way the tray's "Clear all" does (see BellPopover.tsx).
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
