import { useEffect, useState } from 'react'
import { useJobEvents } from '../api/jobs'
import type { TermLine } from './TerminalPanel'
import { TerminalPanel } from './TerminalPanel'

/**
 * Archived transcript first, then follow live (doc 06 §d). EventSource resumes
 * itself via Last-Event-ID = job_events.seq; on a terminal `status` frame the
 * server closes the stream and the transcript query owns re-opens.
 */
export function JobLog({ jobId }: { jobId: number }) {
  const archived = useJobEvents(jobId)
  const [live, setLive] = useState<TermLine[]>([])

  useEffect(() => {
    setLive([])
    if (typeof EventSource === 'undefined') return // jsdom / stripped proxies
    const es = new EventSource(`/api/v1/jobs/${jobId}/events/stream`)
    const push = (l: TermLine) => setLive((prev) => [...prev, l])
    es.addEventListener('line', (e) => {
      const d = JSON.parse((e as MessageEvent).data)
      push({ stream: d.stream, message: d.message })
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
  // a QueryState consumer for that reason — a failed archived-transcript
  // fetch gets its own line instead of the shared EmptyState card, so it
  // reads distinctly from "No output yet." (a job that legitimately has no
  // output) rather than looking identical to it.
  const lines: TermLine[] = live.length
    ? live
    : archived.isError
      ? [{ stream: 'status', message: "Could not load this job's transcript." }]
      : (archived.data ?? []).map((e) => ({ stream: e.stream, message: e.message }))
  return <TerminalPanel lines={lines} />
}
