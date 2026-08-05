import { api } from './client'

// Task 18 extends this file with TOTP enrollment + session-management types
// and hooks — kept minimal here, just what the login page (Task 17) needs.

export type Onboarding = {
  admin_exists: boolean
  host_added: boolean
  complete: boolean
  oidc: boolean
}

export function fetchOnboarding(): Promise<Onboarding> {
  return api<Onboarding>('/meta/onboarding')
}
