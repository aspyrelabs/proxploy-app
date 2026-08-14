import { useEffect, useRef, useState } from 'react'
import { useJobEvents } from '../api/jobs'
import type { TermLine } from './TerminalPanel'
import { TerminalPanel } from './TerminalPanel'

/**
 * Archived transcript first, then follow live (doc 06 §d). EventSource resumes
 * itself via Last-Event-ID = job_events.seq; on a terminal `status` frame the
 * server closes the stream and the transcript query owns re-opens.
 *
 * `onProgress` is the one way a caller observes the job's `progress` SSE
 * frames (proxploy/jobs/backend.py::JobContext.progress). It rides this same
 * EventSource rather than opening a second one for the same job: the stream
 * resumes via Last-Event-ID, so a duplicate connection would double every
 * line. Kept in a ref so passing an unmemoized inline callback cannot itself
 * cause a reconnect; the effect below still only depends on `jobId`.
 */
export function JobLog({ jobId, onProgress, height }:
  { jobId: number; onProgress?: (pct: number) => void; height?: number | 'fill' }) {
  const archived = useJobEvents(jobId)
  const [live, setLive] = useState<TermLine[]>([])
  const onProgressRef = useRef(onProgress)
  onProgressRef.current = onProgress

  useEffect(() => {
    setLive([])
    if (typeof EventSource === 'undefined') return // jsdom / stripped proxies
    const es = new EventSource(`/api/v1/jobs/${jobId}/events/stream`)
    const push = (l: TermLine) => setLive((prev) => [...prev, l])
    es.addEventListener('line', (e) => {
      const d = JSON.parse((e as MessageEvent).data)
      push({ stream: d.stream, message: d.message })
    })
    es.addEventListener('progress', (e) => {
      const d = JSON.parse((e as MessageEvent).data)
      onProgressRef.current?.(d.pct)
    })
    es.addEventListener('status', (e) => {
      const d = JSON.parse((e as MessageEvent).data)
      push({ stream: 'status', message: d.error ? `${d.status}: ${d.error}` : d.status })
      es.close()
    })
    es.onerror = () => es.close()
    return () => es.close()
  }, [jobId])

  // The stream replays the backlog on connect, so `live` supersedes the query
  // once it has anything; before that the archived rows are what we have.
  //
  // TerminalPanel stays dark in both themes by design (doc 06 §c) and is not
  // a QueryState consumer for that reason, a failed archived-transcript
  // fetch gets its own line instead of the shared EmptyState card, so it
  // reads distinctly from "No output yet." (a job that legitimately has no
  // output) rather than looking identical to it.
  const lines: TermLine[] = live.length
    ? live
    : archived.isError
      ? [{ stream: 'status', message: "Could not load this job's transcript." }]
      : (archived.data ?? []).map((e) => ({ stream: e.stream, message: e.message }))
  // `height` is passed straight through rather than defaulted here, so the one
  // caller that renders inside a content-sized dialog can say 'fill' and every
  // other caller keeps TerminalPanel's own 260.
  return <TerminalPanel lines={lines} height={height} />
}
