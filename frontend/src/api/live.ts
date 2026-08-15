import type { QueryClient } from '@tanstack/react-query'
import { TERMINAL, jobLabel } from './jobs'

type MetricTarget = { t: 'host' | 'app' | 'vm'; id: number; cpu_pct: number; mem_pct: number }
type ResourceEvent = { type: string; id?: number; change: string; status?: string }

/** SSE `metrics` event → patch caches (doc 06 §d: patch when the delta is complete). */
export function applyMetrics(qc: QueryClient, data: { targets: MetricTarget[] }) {
  const by = new Map(data.targets.map((t) => [`${t.t}:${t.id}`, t]))
  qc.setQueriesData({ queryKey: ['cluster', 'nodes'] }, (rows: unknown) =>
    Array.isArray(rows)
      ? rows.map((r: any) => {
          const t = by.get(`host:${r.host_id}`)
          return t ? { ...r, cpu_pct: t.cpu_pct, mem_pct: t.mem_pct } : r
        })
      : rows)
  for (const [key, kind] of [['apps', 'app'], ['vms', 'vm']] as const) {
    qc.setQueriesData({ queryKey: [key] }, (v: unknown) =>
      Array.isArray(v)
        ? v.map((r: any) => {
            const t = by.get(`${kind}:${r.id}`)
            return t ? { ...r, cpu_pct: t.cpu_pct } : r
          })
        : v)
  }
  // deltas that need recomputation → invalidate (rings, chart series).
  // ponytail: invalidating ['metrics'] refetches open charts each cycle;
  // doc 06's append-points optimization is the upgrade if it ever matters.
  qc.invalidateQueries({ queryKey: ['cluster', 'summary'] })
  qc.invalidateQueries({ queryKey: ['metrics'] })
}

/**
 * `d.type` (resource events) and `d.target_type` (job events) → the root of the
 * query key that owns that resource. One map, both functions, because they
 * used to disagree: applyResource fell through to 'vms' for anything it did
 * not recognise and applyJob invalidated nothing at all, so Phase 6's storage /
 * backup / network events refreshed the VM list while their own pages went
 * stale. An unlisted type now routes NOWHERE, which is the honest answer; 
 * a guess here is a wrong cache read somewhere else.
 */
const RESOURCE_KEY: Record<string, string> = {
  app: 'apps',
  vm: 'vms',
  storage: 'storage',
  backup: 'backups',
  network: 'network',
}

/** SSE `resource` event → patch status, invalidate everything else (doc 06 §d). */
export function applyResource(qc: QueryClient, d: ResourceEvent) {
  if (d.type === 'host') {
    qc.invalidateQueries({ queryKey: ['cluster'] })
    qc.invalidateQueries({ queryKey: ['hosts'] })
    return
  }
  const key = RESOURCE_KEY[d.type]
  if (!key) return
  // Guests only. A storage/backup/network event's `id` is a HOST id and those
  // caches hold no `id` column, running the row patch there would edit
  // whichever unrelated row happened to collide.
  if (d.change === 'status' && d.id != null && (d.type === 'app' || d.type === 'vm')) {
    qc.setQueriesData({ queryKey: [key] }, (v: unknown) => {
      if (Array.isArray(v)) {
        return v.map((r: any) => (r.id === d.id ? { ...r, status: d.status } : r))
      }
      const row = v as { id?: number } | undefined
      return row && row.id === d.id ? { ...row, status: d.status } : v
    })
    return
  }
  if (d.change === 'discovered') {
    qc.invalidateQueries({ queryKey: ['apps', 'discovered'] })
    return
  }
  qc.invalidateQueries({ queryKey: [key] })
}

/** The severity NotificationCard (components/ui/notification-card.tsx) takes,
 *  which LiveProvider's `job`/`alert` SSE handlers render via `toast.custom`
 *  in place of the plain toast.success/toast.error calls those used to be. */
export type ToastSeverity = 'info' | 'success' | 'warning' | 'destructive'

/** applyJob's toast kind -> card severity: ok is good news, err is bad news,
 *  anything else (queued/running/progress, an intermediate delta that still
 *  reached the toast callback) is informational rather than either. */
export function jobToastSeverity(kind: 'ok' | 'err' | 'info'): ToastSeverity {
  return kind === 'ok' ? 'success' : kind === 'err' ? 'destructive' : 'info'
}

type JobDelta = {
  id: number; kind?: string; status?: string
  progress_pct?: number; target_type?: string | null; error?: string | null
}
type ToastFn = (t: { kind: 'ok' | 'err' | 'info'; text: string; jobId: number; detail?: string }) => void

/** SSE `job` event → patch ['jobs'] (list AND detail shapes), and on a
 *  terminal state invalidate the affected resource + activity feed and raise
 *  a toast (doc 06 §d, doc 05 §Streaming 4; the payload carries target_type). */
export function applyJob(qc: QueryClient, d: JobDelta, toast?: ToastFn) {
  let wasTerminal = false
  const patch = (r: any) => {
    if (r.status && (TERMINAL as string[]).includes(r.status)) wasTerminal = true
    return { ...r, ...d }
  }
  qc.setQueriesData({ queryKey: ['jobs'] }, (data: unknown) => {
    if (Array.isArray(data)) return data.map((r: any) => (r.id === d.id ? patch(r) : r))
    const row = data as { id?: number } | undefined
    return row && row.id === d.id ? patch(row) : data
  })
  if (!d.status || !(TERMINAL as string[]).includes(d.status)) return
  // A duplicate delivery of the same terminal delta (SSE has no replay/dedup
  // today, see the job-log stream's Last-Event-ID for the pattern if that
  // changes) would otherwise re-invalidate and re-toast for nothing.
  if (wasTerminal) return
  qc.invalidateQueries({ queryKey: ['jobs'] })
  qc.invalidateQueries({ queryKey: ['cluster', 'activity'] })
  // ['vms'] is a prefix match, so a vm.snapshot_* job invalidates
  // ['vms', id, 'snapshots'] here for free; Task 16 adds no wiring.
  const resourceKey = d.target_type ? RESOURCE_KEY[d.target_type] : undefined
  if (resourceKey) qc.invalidateQueries({ queryKey: [resourceKey] })
  // catalog.refresh is enqueued with no target_type, because it is not about
  // one resource, so RESOURCE_KEY above can never reach it. It is keyed on
  // kind here instead. Without it the only ['catalog'] invalidation happened
  // when the job was ENQUEUED, and the refetch that followed re-armed the
  // 5-minute staleTime with the pre-refresh rows: the banner flipped to
  // "synced just now" over a grid that stayed unchanged for five minutes.
  if (d.kind === 'catalog.refresh') qc.invalidateQueries({ queryKey: ['catalog'] })
  toast?.({
    kind: d.status === 'succeeded' ? 'ok' : d.status === 'failed' ? 'err' : 'info',
    text: jobLabel({ kind: d.kind ?? 'job', status: d.status }),
    jobId: d.id,
    // The backend's own reason a job failed ("node2 has no lifecycle API
    // token configured...") used to never reach the toast, which showed only
    // the kind and status ("App Stop Failed") with nothing actionable in it.
    // Capped well short of the description's own wrap width: notification-
    // card.tsx has no line-clamp there, so an unusually long error would
    // otherwise stretch the card rather than read as a short reason.
    detail: d.error ? (d.error.length > 200 ? `${d.error.slice(0, 200)}…` : d.error) : undefined,
  })
}

type AlertDelta = {
  id: number; state: 'firing' | 'resolved'
  severity: 'info' | 'warning' | 'critical'; message: string
}
type AlertToastFn = (t: { kind: 'ok' | 'err'; text: string; alertId: number }) => void

/** applyAlert's toast kind, plus the severity the alert *payload* itself
 *  carries -> card severity. A resolution is always good news regardless of
 *  how bad the alert was (applyAlert below toasts 'ok' at any severity); a
 *  firing alert keeps the distinction the payload already draws between
 *  'warning' and 'critical' rather than collapsing both into one colour --
 *  applyAlert never calls this for a firing 'info' alert, since it stays
 *  quiet at that severity (doc 06: warning+). */
export function alertToastSeverity(kind: 'ok' | 'err', payloadSeverity: AlertDelta['severity']): ToastSeverity {
  if (kind === 'ok') return 'success'
  return payloadSeverity === 'critical' ? 'destructive' : 'warning'
}

/** SSE `alert` event → invalidate `['alerts','firing']`; toast for `firing` at
 *  warning+ severity (doc 06 §d, verbatim).
 *
 *  Invalidate rather than patch: the delta carries four fields and the table
 *  renders eleven (rule name, target label, ack state…), so patching would
 *  write a half-row into the cache. Doc 06's rule is "patch when the delta is
 *  complete, invalidate when it isn't".
 *
 *  A `resolved` transition always toasts, at any severity; an info-level
 *  alert that quietly went away is still worth one line of good news, and it
 *  is the only signal that an earlier toast is stale. */
export function applyAlert(qc: QueryClient, d: AlertDelta, toast?: AlertToastFn) {
  qc.invalidateQueries({ queryKey: ['alerts', 'firing'] })
  qc.invalidateQueries({ queryKey: ['cluster', 'activity'] })
  if (d.state === 'resolved') {
    toast?.({ kind: 'ok', text: d.message, alertId: d.id })
    return
  }
  if (d.severity === 'info') return
  toast?.({ kind: 'err', text: d.message, alertId: d.id })
}
