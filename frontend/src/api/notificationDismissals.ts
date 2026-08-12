import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'
import type { ApiError } from './client'

/**
 * Server truth for "what has this user already cleared from the bell
 * tray," GET /notifications/dismissed (backend/proxploy/api/
 * notification_dismissals.py). Only job-backed tray items need this: the
 * tray's other source, lib/notificationStore.ts, is already gone on reload
 * and has nothing here to persist. See BellPopover.tsx.
 *
 * `cleared_through_job_id` is a watermark -- every job id at or below it
 * counts as cleared -- not a growing list, so a busy cluster's "clear all"
 * history stays one integer instead of one row per job ever cleared.
 * `dismissed_job_ids` covers only what the watermark cannot: an item
 * dismissed on its own whose job id is above the watermark. A later
 * "clear all" prunes it back out server-side once the watermark passes it.
 */
export type DismissedState = {
  cleared_through_job_id: number | null
  dismissed_job_ids: number[]
}

const KEY = ['notifications', 'dismissed']

/** Always enabled, like useJobs: the badge counts what the tray holds, and
 *  it cannot know that without this loaded, whether or not the tray is
 *  open yet. */
export function useDismissedState() {
  return useQuery({
    queryKey: KEY,
    queryFn: () => api<DismissedState>('/notifications/dismissed'),
  })
}

/** The response is the new state, straight from the write -- writing it into
 *  the cache directly is one round trip sooner than waiting on a refetch,
 *  and correct even if a concurrent invalidate is in flight. */
export function useClearAllDismissed() {
  const qc = useQueryClient()
  return useMutation<DismissedState, ApiError, void>({
    mutationFn: () =>
      api<DismissedState>('/notifications/dismissed/clear-all', { method: 'POST' }),
    onSuccess: (data) => qc.setQueryData(KEY, data),
  })
}

export function useDismissJob() {
  const qc = useQueryClient()
  return useMutation<DismissedState, ApiError, number>({
    mutationFn: (jobId) =>
      api<DismissedState>(`/notifications/dismissed/${jobId}`, { method: 'POST' }),
    onSuccess: (data) => qc.setQueryData(KEY, data),
  })
}
