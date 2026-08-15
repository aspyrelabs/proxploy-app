import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'
import type { ApiError } from './client'
import { actionLabel, statusLabel } from '../lib/activityDisplay'

export type JobStatus =
  | 'queued' | 'running' | 'succeeded' | 'failed' | 'canceled' | 'interrupted'

export const TERMINAL: JobStatus[] = ['succeeded', 'failed', 'canceled', 'interrupted']

export type JobRow = {
  id: number; kind: string; status: JobStatus
  target_type: string | null; target_id: number | null
  params: Record<string, unknown> | null
  result: Record<string, unknown> | null
  error: string | null; progress_pct: number | null
  requested_by: number | null; schedule_id: number | null
  started_at: string | null; finished_at: string | null; created_at: string
}

export type JobEventRow = { seq: number; ts: string; stream: string; message: string }

export type ActivityRow = {
  kind: 'job' | 'audit' | 'alert'; id: number; at: string; title: string
  status: string | null; target_type: string | null; target_id: number | null
  actor: string | null; job_id: number | null; progress_pct: number | null
  severity: string | null; message: string | null
}

/** The one line a job toast shows. The raw pair (`app.start succeeded`) was
 *  the last place the product handed a user a stored identifier and a stored
 *  status verbatim. Doc 13 names both: the kind neutrally, so no status word
 *  contradicts it, and the status on its own. */
export function jobLabel(j: { kind: string; status: string }): string {
  return `${actionLabel(j.kind)} ${statusLabel(j.status)}`
}

/** 10s while the bell popover is open, never otherwise (`enabled` gates it). */
export function useJobs(opts: { enabled?: boolean; status?: string } = {}) {
  const { enabled = true, status } = opts
  return useQuery({
    queryKey: ['jobs', { status }],
    enabled,
    refetchInterval: enabled ? 10_000 : false,
    queryFn: () => api<JobRow[]>(status ? `/jobs?status=${status}` : '/jobs'),
  })
}

/**
 * One job by id, kept live off the plumbing that already exists.
 *
 * The global SSE stream carries a `job` delta for every state change AND for
 * every ctx.progress() call (backend/proxploy/jobs/backend.py::JobContext.
 * progress fans out to both the per-job stream and the global bus), and
 * api/live.ts::applyJob patches the ['jobs', id] entry this hook creates,
 * detail shape included (tests/jobs.test.ts covers that patch). So a caller
 * watching a job it just enqueued needs no EventSource of its own:
 * JobLog's per-job stream exists for the transcript, and a second connection
 * for a number already arriving on the shared one would be a duplicate
 * subscription, not a second source of truth.
 *
 * The 2s poll is the fallback LiveProvider documents ("query polling is the
 * fallback if SSE dies"), same cadence as useRunningJobOfKind. It stops
 * itself once the job is terminal, so a finished job costs nothing, and
 * `retry: false` means a job that cannot be read (404, a revoked
 * jobs.history entitlement) fails fast into isError rather than leaving a
 * caller's "still running" state hanging for three retries.
 */
export function useJob(id: number | null) {
  return useQuery({
    queryKey: ['jobs', id],
    enabled: id != null,
    retry: false,
    refetchInterval: (q) =>
      q.state.data && TERMINAL.includes(q.state.data.status) ? false : 2_000,
    queryFn: () => api<JobRow>(`/jobs/${id}`),
  })
}

/** Archived transcript. The live tail is the SSE stream in JobLog. */
export function useJobEvents(id: number | null) {
  return useQuery({
    queryKey: ['jobs', id, 'events'],
    enabled: id != null,
    queryFn: () => api<JobEventRow[]>(`/jobs/${id}/events`),
  })
}

/**
 * The one running job of a given kind, if any (`/jobs` supports `kind` as a
 * server-side filter, see backend/proxploy/api/jobs.py::list_jobs). Built for
 * routes/backups.tsx's stale banner, the one surface in the product that
 * displays `backup.sync` at all: GET /backups enqueues that job fire-and-
 * forget and never returns its id, so this is how the banner finds it.
 *
 * Polled only while `enabled`: a page sitting on fresh data has no reason to
 * run a job query on a timer for a banner it isn't even rendering. 2s rather
 * than this app's usual ~30s cadence, deliberately: services/backupjobs.py's
 * sweep is per-host and often finishes well inside 30s, so that cadence would
 * see at most one sample of the only genuinely granular progress in the
 * product, the same coarse jump the app-install/update steps already show.
 */
export function useRunningJobOfKind(kind: string, enabled: boolean) {
  return useQuery({
    queryKey: ['jobs', 'running', kind],
    enabled,
    refetchInterval: enabled ? 2_000 : false,
    queryFn: () => api<JobRow[]>(`/jobs?status=running&kind=${kind}`),
    select: (rows) => rows[0] ?? null,
  })
}

export function useActivity(limit = 20) {
  return useQuery({
    queryKey: ['cluster', 'activity', limit],
    refetchInterval: 30_000,
    queryFn: () => api<ActivityRow[]>(`/cluster/activity?limit=${limit}`),
  })
}

/** The activity feed row's Cancel control (doc 05 `POST /jobs/{id}/cancel`).
 *  Invalidates both `jobs` and the activity feed's own key so the row
 *  reflects the cancellation without waiting for the 30s poll. */
export function useCancelJob() {
  const qc = useQueryClient()
  return useMutation<{ id: number; status: string }, ApiError, number>({
    mutationFn: (id) =>
      api<{ id: number; status: string }>(`/jobs/${id}/cancel`, { method: 'POST' }),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ['jobs'] })
      qc.invalidateQueries({ queryKey: ['cluster', 'activity'] })
    },
  })
}

export type LifecycleVars = {
  target: 'app' | 'vm'; id: number; action: string; confirm?: string
}

/**
 * Optimistic status patch + SSE reconciliation (plan decision 13): the truth
 * arrives with the job's terminal `resource` delta or the next 30s poll, so
 * there is no rollback cache to keep in sync, only an invalidate on error.
 */
export function useLifecycle() {
  const qc = useQueryClient()
  const key = (t: 'app' | 'vm') => (t === 'app' ? 'apps' : 'vms')
  return useMutation<{ job: JobRow }, ApiError, LifecycleVars>({
    mutationFn: (v) =>
      api<{ job: JobRow }>(`/${key(v.target)}/${v.id}/${v.action}`, {
        method: 'POST',
        body: JSON.stringify(v.confirm ? { confirm: v.confirm } : {}),
      }),
    onMutate: (v) => {
      qc.setQueriesData({ queryKey: [key(v.target)] }, (data: unknown) => {
        if (Array.isArray(data)) {
          return data.map((r: any) => (r.id === v.id ? { ...r, status: 'pending' } : r))
        }
        const row = data as { id?: number } | undefined
        return row && row.id === v.id ? { ...row, status: 'pending' } : data
      })
    },
    // Do NOT invalidate the resource key (apps/vms) here on success: the list's
    // poller-fed cache still reads "running" for up to 30s, so a success-path
    // refetch would stomp the optimistic "pending" patch with stale data and
    // re-arm the destructive action while the job is still queued. Every
    // terminal path already clears it without our help, a successful job
    // publishes `resource`/`change:lifecycle` (applyResource invalidates it),
    // a failed/canceled job publishes the terminal `job` delta (applyJob
    // invalidates it), and the list's own 30s refetchInterval is the backstop.
    onError: (_e, v) => { qc.invalidateQueries({ queryKey: [key(v.target)] }) },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ['jobs'] })
      qc.invalidateQueries({ queryKey: ['cluster', 'activity'] })
    },
  })
}
