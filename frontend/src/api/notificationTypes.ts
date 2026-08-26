import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'

/** Mirrors NotificationType in backend/proxploy/services/notification_types.py. */
export type TypeRow = {
  key: string
  /** What the operator reads. Backend spelling never reaches the screen. */
  label: string
  group: string
  enabled: boolean
}

export type TypeState = {
  rows: TypeRow[]
  /** The same thing keyed for lookup. Derived once here rather than in each
   *  consumer, so the matrix and LiveProvider cannot disagree about whether a
   *  type is on. */
  enabled: Record<string, boolean>
}

export function useNotificationTypes() {
  return useQuery({
    queryKey: ['notifications', 'types'],
    queryFn: () => api<{ types: TypeRow[] }>('/notifications/types'),
    select: (d): TypeState => ({
      rows: d.types,
      enabled: Object.fromEntries(d.types.map((t) => [t.key, t.enabled])),
    }),
  })
}

export function useSetNotificationTypes() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (enabled: Record<string, boolean>) =>
      api<{ types: TypeRow[] }>('/notifications/types', {
        method: 'PATCH', body: JSON.stringify({ enabled }),
      }),
    onSettled: () => qc.invalidateQueries({ queryKey: ['notifications', 'types'] }),
  })
}
