import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'
import type { ApiError } from './client'

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

export function jobLabel(j: { kind: string; status: string }): string {
  return `${j.kind} ${j.status}`
}

/** Archived transcript. The live tail is the SSE stream in JobLog. */
export function useJobEvents(id: number | null) {
  return useQuery({
    queryKey: ['jobs', id, 'events'],
    enabled: id != null,
    queryFn: () => api<JobEventRow[]>(`/jobs/${id}/events`),
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
