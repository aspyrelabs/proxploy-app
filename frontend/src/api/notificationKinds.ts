import { useQuery } from '@tanstack/react-query'
import { api } from './client'

/** One question the guided picker asks. Mirrors Field in
 *  backend/proxploy/services/notification_catalog.py. */
export type KindField = {
  key: string
  label: string
  required: boolean
  /** Render as a password input. The value is a token, key or password. */
  secret: boolean
  placeholder: string
  default: string
  help: string
}

export type NotificationKind = {
  kind: string
  label: string
  /** Apprise's own page for this service, for the operator who wants detail. */
  setup_url: string
  fields: KindField[]
}

/** The catalog is a build-time constant on the server, not live data: it can
 *  only change when Proxploy itself is updated, so refetching it is waste. */
export function useNotificationKinds(enabled = true) {
  return useQuery({
    queryKey: ['notifications', 'kinds'],
    queryFn: () => api<NotificationKind[]>('/notifications/kinds'),
    staleTime: Infinity,
    enabled,
  })
}
