import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'

export type AlertRow = {
  id: number; rule_id: number; rule_name: string | null
  severity: 'info' | 'warning' | 'critical'
  target_type: string | null; target_id: number | null
  target_label: string | null
  state: 'firing' | 'resolved'; value: number | null; message: string | null
  fired_at: string | null; resolved_at: string | null
  acked_by: number | null; acked_by_email: string | null; acked_at: string | null
}

export type AlertRuleRow = {
  id: number; name: string; metric: string
  target_type: 'host' | 'app' | 'vm' | 'any'; target_id: number | null
  operator: 'gt' | 'lt'; threshold: number; duration_s: number
  severity: 'info' | 'warning' | 'critical'
  channel_ids: number[]; enabled: boolean
}

/** The metric enum lives on the backend — don't duplicate it. */
export type MetricSpec = { metric: string; targets: string[]; needs_threshold: boolean }

/** Backs BellPopover's tray badge and the Alerts page's live firing list. */
export function useFiringAlerts() {
  return useQuery({
    queryKey: ['alerts', 'firing'],
    queryFn: () => api<AlertRow[]>('/alerts?state=firing'),
    refetchInterval: 60_000,
  })
}

export function useAlertHistory(limit = 50) {
  return useQuery({
    queryKey: ['alerts', 'history', limit],
    queryFn: () => api<AlertRow[]>(`/alerts?limit=${limit}`),
  })
}

export function useAlertRules(enabled = true) {
  return useQuery({
    queryKey: ['alert-rules'],
    queryFn: () => api<AlertRuleRow[]>('/alert-rules'),
    enabled,
  })
}

export function useAlertMetrics(enabled = true) {
  return useQuery({
    queryKey: ['alert-rules', 'metrics'],
    queryFn: () => api<{ metrics: MetricSpec[] }>('/alert-rules/metrics'),
    staleTime: 5 * 60_000,     // an enum, not live data
    enabled,
  })
}

export function useAckAlert() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api<AlertRow>(`/alerts/${id}/ack`, { method: 'POST' }),
    onSettled: () => qc.invalidateQueries({ queryKey: ['alerts'] }),
  })
}
