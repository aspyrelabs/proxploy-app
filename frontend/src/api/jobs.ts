import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'
import type { ApiError } from './client'
import { actionLabel, jobPhrase, statusLabel } from '../lib/activityDisplay'

export type JobStatus =
  | 'queued' | 'running' | 'succeeded' | 'failed' | 'canceled' | 'interrupted'

export const TERMINAL: JobStatus[] = ['succeeded', 'failed', 'canceled', 'interrupted']

export type JobRow = {
  id: number; kind: string; status: JobStatus
  target_type: string | null; target_id: number | null
  /** Captured when the job was created, so a destroyed guest is still named.
   *  Optional because a job created before that column existed has none. */
  target_name?: string | null
  params: Record<string, unknown> | null
  result: Record<string, unknown> | null
  error: string | null; progress_pct: number | null
  requested_by: number | null; schedule_id: number | null
  started_at: string | null; finished_at: string | null; created_at: string
}

export type JobEventRow = { seq: number; ts: string; stream: string; message: string }

/** The one line a job toast shows: kind and status combined into a readable label. */
export function jobLabel(j: { kind: string; status: string }): string {
  return jobPhrase(j.kind, j.status)
    ?? `${actionLabel(j.kind)} ${statusLabel(j.status)}`
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
 * One job by id, kept live via the global SSE stream (applyJob patches the
 * ['jobs', id] cache entry). The 2s poll is a fallback, stops on terminal
 * status, and retry:false makes a 404 (revoked entitlement) fail fast.
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
 * The one running job of a given kind, if any (`/jobs` supports a `kind`
 * server-side filter). Polled at 2s while enabled because backup sweeps are
 * per-host and finish fast; 30s would miss progress entirely.
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

/** `POST /jobs/{id}/cancel`. Nothing mounts this today; kept for the next cancel control. */
export function useCancelJob() {
  const qc = useQueryClient()
  return useMutation<{ id: number; status: string }, ApiError, number>({
    mutationFn: (id) =>
      api<{ id: number; status: string }>(`/jobs/${id}/cancel`, { method: 'POST' }),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ['jobs'] })
    },
  })
}

export type LifecycleVars = {
  target: 'app' | 'vm'; id: number; action: string; confirm?: string
}

/**
 * Optimistic status patch + SSE reconciliation: the truth arrives with the
 * job's terminal delta or the next 30s poll, so there's no rollback cache —
 * only an invalidate on error.
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
    onMutate: async (v) => {
      // A refetch already in flight when the button was clicked would resolve
      // AFTER this patch and overwrite it with the pre-action status, which is
      // half of why the pill used to flash back to "running" on its way to
      // "stopped". The other half was the server not writing the new status
      // until the next poll, fixed in services/lifecycle.py.
      await qc.cancelQueries({ queryKey: [key(v.target)] })
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
    },
  })
}
