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
  /** A realistic value for the (i) beside the label. Falls back to the
   *  placeholder server-side, so never empty. Matters most on secret fields,
   *  where a password box shows no placeholder. */
  example: string
}

/** No guided field takes a whole URL: each one is a single component the
 *  server assembles into one. Worth catching by name, because a Slack webhook
 *  pasted into WhatsApp's access token satisfies that field's own rule ("at
 *  least 20 characters, no spaces") perfectly well. Kept identical to
 *  services/notification_catalog.py's _URLISH so the two agree. */
const URLISH = /[A-Za-z][A-Za-z0-9+.-]*:\/\//

/** Does this value satisfy its field? An empty value is not a rule failure,
 *  it is the required check's business, and a pattern the browser cannot
 *  compile must never make a field permanently unfillable. */
export function fieldError(field: KindField, value: string): string | null {
  if (!value) return null
  if (URLISH.test(value)) {
    return `${field.label} takes a single value, not a whole URL. `
      + 'If that is a URL for another service, add that service instead.'
  }
  if (!field.pattern) return null
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

/** What a saved channel can tell an edit form about itself.
 *
 *  Secret VALUES are never in here, by design: `secrets_set` names the keys
 *  that have one so the form can say "leave blank to keep" rather than showing
 *  dots it could not honour. `known` is false for a channel added by pasting a
 *  URL and for any row written before the values were kept.
 */
export type ChannelFields = {
  kind: string
  known: boolean
  fields: Record<string, string>
  secrets_set: string[]
}

export function useChannelFields(id: number) {
  return useQuery({
    queryKey: ['notifications', 'channels', id, 'fields'],
    queryFn: () => api<ChannelFields>(`/notifications/channels/${id}/fields`),
  })
}
