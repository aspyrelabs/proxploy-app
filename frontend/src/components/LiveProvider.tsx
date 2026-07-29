import { useQueryClient } from '@tanstack/react-query'
import { createContext, useContext, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { applyMetrics, applyResource } from '../api/live'

const LiveCtx = createContext<{ lastEventAt: number | null }>({ lastEventAt: null })

export function useLive() {
  return useContext(LiveCtx)
}

/** One EventSource per tab (doc 06 §d). Query polling is the fallback if SSE dies. */
export function LiveProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient()
  const [lastEventAt, setLastEventAt] = useState<number | null>(null)
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
    return () => es.close()
  }, [qc])
  return <LiveCtx.Provider value={{ lastEventAt }}>{children}</LiveCtx.Provider>
}

/** Prototype `.live` badge: "Live · updated Ns ago" bound to the last SSE event. */
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
