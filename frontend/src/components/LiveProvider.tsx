import { useQueryClient } from '@tanstack/react-query'
import { createContext, useContext, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { alertToastSeverity, applyAlert, applyJob, applyMetrics, applyResource, jobToastSeverity } from '../api/live'
import { useEntitlements } from '../api/hooks'
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
  const { has } = useEntitlements()
  const inApp = useRef(true)
  inApp.current = has('notify.inapp')
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
      // Keyed by jobId, not a fresh push: notificationStore.pushJobEvent and
      // notificationMerge.ts are what keep this job from ever rendering
      // twice once GET /jobs carries the same terminal delta.
      pushJobEvent(t.jobId, jobToastSeverity(t.kind), t.text, `job #${t.jobId}`)
    }))
    wire('alert', (d) => applyAlert(qc, d, (t) => {
      if (!inApp.current) return   // notify.inapp gates the surface, not the data
      pushAlertEvent(t.alertId, alertToastSeverity(t.kind, d.severity), t.text, 'alert')
    }))
    return () => es.close()
  }, [qc])
  return <LiveCtx.Provider value={{ lastEventAt }}>{children}</LiveCtx.Provider>
}

/** Prototype `.live` badge: "Live · updated Ns ago" bound to the last SSE event.
 *
 *  CURRENTLY UNRENDERED. It was the Hosts page header's right-hand item and is
 *  no longer mounted anywhere, for two reasons: `HealthFooter` in the sidebar
 *  already carries a live status indicator (dot + "N nodes · N alerts"), and a
 *  visible "last updated" is not wanted at all -- the page should keep itself
 *  current without announcing when it last did so, which the LiveProvider
 *  above does regardless (its SSE subscription invalidates the queries; that
 *  is what actually keeps the page fresh, not this badge).
 *
 *  Kept rather than deleted, following the same rule as the hidden Settings
 *  affordances: hide the surface, keep the code, say why. An unused named
 *  export does not trip noUnusedLocals. */
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
