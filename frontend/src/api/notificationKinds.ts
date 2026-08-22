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
  /** The rule the value must match, as a string the RegExp constructor takes.
   *  It is the SAME string services/notification_catalog.py gates on, handed
   *  over so the two cannot drift into disagreeing about what is acceptable.
   *  Empty means no rule. */
  pattern: string
  /** What to show when the rule refuses. Never the pattern itself. */
  hint: string
}

/** Does this value satisfy its field? An empty value is not a rule failure,
 *  it is the required check's business, and a pattern the browser cannot
 *  compile must never make a field permanently unfillable. */
export function fieldError(field: KindField, value: string): string | null {
  if (!value || !field.pattern) return null
  try {
    if (new RegExp(field.pattern).test(value)) return null
  } catch {
    return null
  }
  return field.hint || `${field.label} is not right.`
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
