import { useQuery } from '@tanstack/react-query'
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

// --- Task 18: TOTP enrollment + session management --------------------------
//
// Mirrors backend/proxploy/api/auth.py's response shapes exactly (see
// backend/tests/test_totp.py, test_auth_totp_login.py, test_sessions_api.py).

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
