import { useMutation, useQuery } from '@tanstack/react-query'
import { api } from './client'

export type Onboarding = {
  admin_exists: boolean
  host_added: boolean
  complete: boolean
  oidc: boolean
}

export function fetchOnboarding(): Promise<Onboarding> {
  return api<Onboarding>('/meta/onboarding')
}

// Just the field TotpCard needs from GET /auth/me -- the full Me shape lives
// in api/hooks.ts under its own ['me'] query key; this uses a distinct key
// so the two don't have to agree on a type.
export type TotpStatus = { totp_enabled: boolean }

export type TotpEnrollment = {
  secret: string
  otpauth_uri: string
  recovery_codes: string[]
}

export type SessionRow = {
  id: number
  ip: string | null
  user_agent: string | null
  created_at: string
  last_seen_at: string | null
  current: boolean
}

export function useTotpStatus(enabled: boolean) {
  return useQuery({
    queryKey: ['auth', 'me'],
    queryFn: () => api<TotpStatus>('/auth/me'),
    enabled,
  })
}

export function useSessions() {
  return useQuery({ queryKey: ['auth', 'sessions'], queryFn: () => api<SessionRow[]>('/auth/sessions') })
}

/** A browser that has already proved the second factor and may skip the code
 *  step until `expires_at`. Not a session: it grants nothing on its own, the
 *  password is still required at every login. */
export type TrustedDeviceRow = SessionRow & { expires_at: string }

export function useTrustedDevices(enabled: boolean) {
  return useQuery({
    queryKey: ['auth', 'trusted-devices'],
    queryFn: () => api<TrustedDeviceRow[]>('/auth/trusted-devices'),
    enabled,
  })
}

export type UpdateStatus = {
  current: string
  latest: string | null
  update_available: boolean
  notes_url: string | null
  channel: string | null
  error: string | null
  install_shape: string
  can_self_apply: boolean
  compose_hint: string | null
}

export function useUpdateStatus() {
  return useQuery({ queryKey: ['meta', 'update'], queryFn: () => api<UpdateStatus>('/meta/update') })
}

export function useApplyUpdate() {
  return useMutation({
    mutationFn: (version: string) =>
      api<{ ok: boolean; version: string }>('/meta/update', {
        method: 'POST', body: JSON.stringify({ version }),
      }),
  })
}

export type UpdateLogState = 'none' | 'running' | 'succeeded' | 'failed' | 'rolled_back'

export type UpdateLog = {
  state: UpdateLogState
  version: string | null
  from: string | null
  updated_at: string | null
  reason: string | null
  lines: string[]
}

const UPDATE_LOG_POLL_MS = 3000

export function useUpdateLog(forcePoll = false) {
  return useQuery({
    queryKey: ['meta', 'update-log'],
    queryFn: () => api<UpdateLog>('/meta/update/log'),
    refetchInterval: (query) =>
      forcePoll || query.state.data?.state === 'running' ? UPDATE_LOG_POLL_MS : false,
  })
}
