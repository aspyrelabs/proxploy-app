import { useQueryClient } from '@tanstack/react-query'
import { createContext, useContext, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { alertToastSeverity, applyAlert, applyJob, applyMetrics, applyResource, jobToastSeverity } from '../api/live'
import { useEntitlements } from '../api/hooks'
import { useNotificationTypes } from '../api/notificationTypes'
import { pushAlertEvent, pushJobEvent } from '../lib/notificationStore'

const LiveCtx = createContext<{ lastEventAt: number | null }>({ lastEventAt: null })

export function useLive() {
  return useContext(LiveCtx)
}

/** One EventSource per tab (doc 06 §d). Query polling is the fallback if SSE dies. */
export function LiveProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient()
  const [lastEventAt, setLastEventAt] = useState<number | null>(null)
  // notify.inapp gates the toast surface, not the data; a ref keeps the
  // effect below from re-subscribing (and dropping the EventSource) every
  // time the entitlements query refetches.
  //
  // `ent.data == null ||`, not a bare has(): has() is fail-closed by design
  // (api/hooks.ts), so on its own it dropped every job and alert that landed
  // while the first /entitlements fetch was in flight, and every one after
  // that if the fetch failed. Those events are not replayed, so the operator
  // was left with no record of whether their install succeeded. Only a plan
  // we have actually read, and that genuinely lacks the feature, silences
  // this. The events are stored, not shown as an unlocked paid feature: the
  // topbar bell follows the same three-state rule.
  const ent = useEntitlements()
  const inApp = useRef(true)
  inApp.current = ent.data == null || ent.has('notify.inapp')
  // The Events matrix' master switches. Read through a ref for the same
  // reason inApp is: the SSE handlers below are wired once in an effect that
  // must not re-subscribe every time a query settles.
  const types = useNotificationTypes()
  const typeEnabled = useRef<Record<string, boolean>>({})
  typeEnabled.current = types.data?.enabled ?? {}
  useEffect(() => {
    if (typeof EventSource === 'undefined') return // jsdom / stripped proxies
    const es = new EventSource('/api/v1/events/stream')
    const wire = (name: string, fn: (d: any) => void) =>
      es.addEventListener(name, (e) => {
        setLastEventAt(Date.now())
        fn(JSON.parse((e as MessageEvent).data))
      })
    wire('metrics', (d) => applyMetrics(qc, d))
    wire('resource', (d) => applyResource(qc, d))
    wire('job', (d) => applyJob(qc, d, (t) => {
      if (!inApp.current) return   // notify.inapp gates the surface, not the data
      // An absent notify_type is a progress delta, not a silenced one: only a
      // terminal outcome carries a type, and reading absent as off would
      // silence every running job.
      if (d.notify_type && typeEnabled.current[d.notify_type] === false) return
      // Keyed by jobId, not a fresh push: notificationStore.pushJobEvent and
      // notificationMerge.ts are what keep this job from ever rendering
      // twice once GET /jobs carries the same terminal delta.
      //
      // `t.detail` is the backend's own reason a failed job failed; falling
      // back to "job #N" is only for the case that carries none (success,
      // or a failure the backend gave no message for).
      pushJobEvent(t.jobId, jobToastSeverity(t.kind), t.text, t.detail ?? `job #${t.jobId}`)
    }))
    wire('alert', (d) => applyAlert(qc, d, (t) => {
      if (!inApp.current) return   // notify.inapp gates the surface, not the data
      const key = d.state === 'resolved' ? 'alert.resolved' : 'alert.fired'
      if (typeEnabled.current[key] === false) return
      pushAlertEvent(t.alertId, alertToastSeverity(t.kind, d.severity), t.text, 'alert')
    }))
    return () => es.close()
  }, [qc])
  return <LiveCtx.Provider value={{ lastEventAt }}>{children}</LiveCtx.Provider>
}

/** Dead "Live · updated Ns ago" badge: no longer mounted anywhere, because a
 *  visible "last updated" is deliberately not wanted. Kept (not deleted) like
 *  the hidden Settings affordances; an unused named export does not trip
 *  noUnusedLocals. */
export function LivePulse() {
  const { lastEventAt } = useLive()
  const [, force] = useState(0)
  useEffect(() => {
    const t = setInterval(() => force((n) => n + 1), 5000)
    return () => clearInterval(t)
  }, [])
  if (!lastEventAt) {
    return <span className="font-mono text-[11px] text-text-3">Polling every 30s</span>
  }
  const secs = Math.max(0, Math.round((Date.now() - lastEventAt) / 1000))
  return (
    <span className="flex items-center gap-2 font-mono text-[11px] text-text-2">
      <span className="h-2 w-2 animate-pulse rounded-full bg-green motion-reduce:animate-none" />
      Live · updated {secs}s ago
    </span>
  )
}
