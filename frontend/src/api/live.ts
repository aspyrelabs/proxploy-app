import type { QueryClient } from '@tanstack/react-query'
import { TERMINAL, jobLabel } from './jobs'
import type { JobRow } from './jobs'

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

/** SSE `resource` event → patch status, invalidate everything else (doc 06 §d). */
export function applyResource(qc: QueryClient, d: ResourceEvent) {
  if (d.type === 'host') {
    qc.invalidateQueries({ queryKey: ['cluster'] })
    qc.invalidateQueries({ queryKey: ['hosts'] })
    return
  }
  const key = d.type === 'app' ? 'apps' : 'vms'
  if (d.change === 'status' && d.id != null) {
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

type JobDelta = {
  id: number; kind?: string; status?: string
  progress_pct?: number; target_type?: string | null
}
type ToastFn = (t: { kind: 'ok' | 'err' | 'info'; text: string; jobId: number }) => void

/** SSE `job` event → patch ['jobs'], and on a terminal state invalidate the
 *  affected resource + activity feed and raise a toast (doc 06 §d). */
export function applyJob(qc: QueryClient, d: JobDelta, toast?: ToastFn) {
  qc.setQueriesData({ queryKey: ['jobs'] }, (data: unknown) =>
    Array.isArray(data)
      ? data.map((r: any) => (r.id === d.id ? { ...r, ...d } : r))
      : data)
  if (!d.status || !TERMINAL.includes(d.status as never)) return
  qc.invalidateQueries({ queryKey: ['jobs'] })
  qc.invalidateQueries({ queryKey: ['cluster', 'activity'] })
  // The backend's SSE `job` payload never includes `target_type` (see
  // JobBackend._publish in backend/proxploy/jobs/backend.py — every call site
  // passes only id/status/kind/progress_pct). Fall back to the job row
  // useLifecycle seeds into ['jobs', id] on mutation success, so the terminal
  // event still invalidates the right resource list in the real app.
  const targetType = d.target_type ??
    qc.getQueryData<JobRow>(['jobs', d.id])?.target_type
  if (targetType === 'app') qc.invalidateQueries({ queryKey: ['apps'] })
  if (targetType === 'vm') qc.invalidateQueries({ queryKey: ['vms'] })
  toast?.({
    kind: d.status === 'succeeded' ? 'ok' : d.status === 'failed' ? 'err' : 'info',
    text: jobLabel({ kind: d.kind ?? 'job', status: d.status }),
    jobId: d.id,
  })
}
