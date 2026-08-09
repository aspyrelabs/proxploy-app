import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { toastError } = vi.hoisted(() => ({ toastError: vi.fn() }))
vi.mock('sonner', () => ({ toast: { error: toastError, success: vi.fn() } }))

type Call = { path: string; method?: string; body: unknown }
const calls: Call[] = []
let totpAllowed = true
let totpEnabled = false
let disableStatus: 200 | 403 = 200
let entitlementsFail = false
let meFail = false

const RECOVERY_CODES = Array.from({ length: 10 }, (_, i) => `recovery-code-${i}`)

const { ApiError } = vi.hoisted(() => ({
  ApiError: class extends Error {
    status: number; body: unknown
    constructor(status: number, body: unknown) { super(`API ${status}`); this.status = status; this.body = body }
  },
}))

vi.mock('../api/client', () => ({
  ApiError,
  api: vi.fn((path: string, opts?: RequestInit) => {
    const method = opts?.method
    if (path === '/entitlements') {
      if (entitlementsFail) return Promise.reject(new Error('boom'))
      return Promise.resolve({ tier: 'builtin', features: { 'auth.totp': totpAllowed }, grace: null, clock_skew: false })
    }
    if (path === '/auth/me' && !method) {
      if (meFail) return Promise.reject(new Error('boom'))
      return Promise.resolve({ id: 1, email: 'admin@example.com', display_name: null,
        role: 'owner', totp_enabled: totpEnabled })
    }
    if (path === '/auth/totp/enroll' && method === 'POST') {
      calls.push({ path, method, body: null })
      return Promise.resolve({
        secret: 'JBSWY3DPEHPK3PXP',
        otpauth_uri: 'otpauth://totp/Proxploy:admin@example.com?secret=JBSWY3DPEHPK3PXP&issuer=Proxploy',
        recovery_codes: RECOVERY_CODES,
      })
    }
    if (path === '/auth/totp/confirm' && method === 'POST') {
      const body = opts?.body ? JSON.parse(String(opts.body)) : null
      calls.push({ path, method, body })
      totpEnabled = true
      return Promise.resolve({ ok: true })
    }
    if (path === '/auth/totp' && method === 'DELETE') {
      const body = opts?.body ? JSON.parse(String(opts.body)) : null
      calls.push({ path, method, body })
      if (disableStatus === 403) return Promise.reject(new ApiError(403, { detail: 're-authentication required' }))
      totpEnabled = false
      return Promise.resolve({ ok: true })
    }
    calls.push({ path, method, body: opts?.body ? JSON.parse(String(opts.body)) : null })
    return Promise.resolve(null)
  }),
}))

import { TotpCard } from '../components/TotpCard'

const wrap = () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={qc}><TotpCard /></QueryClientProvider>)
}

describe('TotpCard', () => {
  beforeEach(() => {
    calls.length = 0
    toastError.mockClear()
    totpAllowed = true
    totpEnabled = false
    disableStatus = 200
    entitlementsFail = false
    meFail = false
  })
  afterEach(() => vi.restoreAllMocks())

  it('gates the whole card behind auth.totp: no /auth/me fetch, plan message shown', async () => {
    totpAllowed = false
    wrap()
    expect(await screen.findByText('Not included in your plan.')).toBeInTheDocument()
    expect(calls.some((c) => c.path === '/auth/me')).toBe(false)
  })

  it('shows "Enable two-factor" when /auth/me says totp_enabled is false', async () => {
    wrap()
    expect(await screen.findByRole('button', { name: 'Enable two-factor' })).toBeInTheDocument()
  })

  it('enrolling renders the secret, otpauth URI, and all ten recovery codes with the once-only warning', async () => {
    wrap()
    fireEvent.click(await screen.findByRole('button', { name: 'Enable two-factor' }))
    expect(await screen.findByText('JBSWY3DPEHPK3PXP')).toBeInTheDocument()
    expect(screen.getByText(/otpauth:\/\/totp\/Proxploy/)).toBeInTheDocument()
    for (const code of RECOVERY_CODES) expect(screen.getByText(code)).toBeInTheDocument()
    expect(screen.getByText(/shown once, store them now/i)).toBeInTheDocument()
  })

  it('confirming the code calls /auth/totp/confirm and flips to enabled state with a Disable flow', async () => {
    wrap()
    fireEvent.click(await screen.findByRole('button', { name: 'Enable two-factor' }))
    await screen.findByText('JBSWY3DPEHPK3PXP')
    fireEvent.change(screen.getByLabelText(/confirm code/i), { target: { value: '123456' } })
    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }))
    await waitFor(() => expect(calls.some((c) =>
      c.path === '/auth/totp/confirm' && c.method === 'POST'
      && JSON.stringify(c.body) === JSON.stringify({ code: '123456' }))).toBe(true))
    expect(await screen.findByRole('button', { name: 'Disable two-factor' })).toBeInTheDocument()
  })

  it('disable flow asks for the password and calls DELETE /auth/totp', async () => {
    totpEnabled = true
    wrap()
    fireEvent.click(await screen.findByRole('button', { name: 'Disable two-factor' }))
    fireEvent.change(screen.getByLabelText(/password/i), { target: { value: 'hunter2' } })
    fireEvent.click(screen.getByRole('button', { name: 'Confirm disable' }))
    await waitFor(() => expect(calls.some((c) =>
      c.path === '/auth/totp' && c.method === 'DELETE'
      && JSON.stringify(c.body) === JSON.stringify({ password: 'hunter2' }))).toBe(true))
  })

  it('says it could not check the plan rather than getting stuck on "Loading…" when entitlements fail', async () => {
    entitlementsFail = true
    wrap()
    expect(await screen.findByText(/could not check your plan/i)).toBeInTheDocument()
    expect(screen.queryByText('Loading…')).not.toBeInTheDocument()
    expect(screen.queryByText('Not included in your plan.')).not.toBeInTheDocument()
  })

  it('does not offer "Enable two-factor" when the status check itself failed', async () => {
    // Security-relevant regression: /auth/me erroring must not fall through
    // to the enroll button, which would invite re-enrolling a user who may
    // already have TOTP on.
    meFail = true
    wrap()
    expect(await screen.findByText(/could not check two-factor status/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Enable two-factor' })).not.toBeInTheDocument()
  })

  it('surfaces a 403 re-auth error from disable as a toast', async () => {
    totpEnabled = true
    disableStatus = 403
    wrap()
    fireEvent.click(await screen.findByRole('button', { name: 'Disable two-factor' }))
    fireEvent.change(screen.getByLabelText(/password/i), { target: { value: 'wrong' } })
    fireEvent.click(screen.getByRole('button', { name: 'Confirm disable' }))
    await waitFor(() => expect(toastError).toHaveBeenCalledWith('re-authentication required'))
  })
})
