import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { notifyError } = vi.hoisted(() => ({ notifyError: vi.fn() }))
vi.mock('../lib/notify', () => ({ notify: { error: notifyError, success: vi.fn(), info: vi.fn(), warning: vi.fn() } }))

// jsdom has no QR decoder, so real qrcode.react output can't be asserted on by
// scanning it back. Stub it with something that records the exact value it was
// asked to encode, so the test can prove the URI reaches the QR component
// (rather than just that some element with that text exists, which is what the
// old copyable-URI assertion checked).
vi.mock('qrcode.react', () => ({
  QRCodeSVG: (props: { value: string; title?: string }) => (
    <svg data-testid="totp-qr" data-value={props.value}><title>{props.title}</title></svg>
  ),
}))

type Call = { path: string; method?: string; body: unknown }
const calls: Call[] = []
let totpAllowed = true
let totpEnabled = false
let disableStatus: 200 | 403 = 200
let regenerateStatus: 200 | 403 | 409 = 200
let entitlementsFail = false
let meFail = false

const RECOVERY_CODES = Array.from({ length: 10 }, (_, i) => `recovery-code-${i}`)
const NEW_RECOVERY_CODES = Array.from({ length: 10 }, (_, i) => `new-recovery-code-${i}`)

vi.mock('../api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/client')>()),
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
    if (path === '/auth/totp/recovery-codes/regenerate' && method === 'POST') {
      const body = opts?.body ? JSON.parse(String(opts.body)) : null
      calls.push({ path, method, body })
      if (regenerateStatus === 403) return Promise.reject(new ApiError(403, { detail: 're-authentication required' }))
      if (regenerateStatus === 409) return Promise.reject(new ApiError(409, { detail: 'enable two-factor first' }))
      return Promise.resolve({ recovery_codes: NEW_RECOVERY_CODES })
    }
    calls.push({ path, method, body: opts?.body ? JSON.parse(String(opts.body)) : null })
    return Promise.resolve(null)
  }),
}))

import { ApiError } from '../api/client'
import { TotpCard } from '../components/TotpCard'

const wrap = () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={qc}><TotpCard /></QueryClientProvider>)
}

describe('TotpCard', () => {
  beforeEach(() => {
    calls.length = 0
    notifyError.mockClear()
    totpAllowed = true
    totpEnabled = false
    disableStatus = 200
    regenerateStatus = 200
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

  it('enrolling renders the secret, a QR code encoding the otpauth URI, and all ten recovery codes with the once-only warning', async () => {
    wrap()
    fireEvent.click(await screen.findByRole('button', { name: 'Enable two-factor' }))
    expect(await screen.findByText('JBSWY3DPEHPK3PXP')).toBeInTheDocument()
    // The QR component is React.lazy-loaded (see TotpCard.tsx), so it only
    // appears after its dynamic import resolves -- findBy*, not getBy*.
    expect(await screen.findByTestId('totp-qr')).toHaveAttribute('data-value',
      'otpauth://totp/Proxploy:admin@example.com?secret=JBSWY3DPEHPK3PXP&issuer=Proxploy')
    for (const code of RECOVERY_CODES) expect(screen.getByText(code)).toBeInTheDocument()
    expect(screen.getByText(/shown once, store them now/i)).toBeInTheDocument()
  })

  it('submitting the code opens an activation confirm dialog rather than activating immediately', async () => {
    wrap()
    fireEvent.click(await screen.findByRole('button', { name: 'Enable two-factor' }))
    await screen.findByText('JBSWY3DPEHPK3PXP')
    fireEvent.change(screen.getByLabelText(/confirm code/i), { target: { value: '123456' } })
    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }))

    expect(await screen.findByText(/activate two-factor authentication/i)).toBeInTheDocument()
    expect(screen.getByText(/will not be shown again/i)).toBeInTheDocument()
    // The codes are shown again inside the dialog, not just referenced.
    for (const code of RECOVERY_CODES) expect(screen.getAllByText(code).length).toBeGreaterThan(0)
    // No request fired yet: opening the dialog is not activating.
    expect(calls.some((c) => c.path === '/auth/totp/confirm')).toBe(false)
  })

  it('the activate button in the dialog stays disabled until the acknowledgement is checked', async () => {
    wrap()
    fireEvent.click(await screen.findByRole('button', { name: 'Enable two-factor' }))
    await screen.findByText('JBSWY3DPEHPK3PXP')
    fireEvent.change(screen.getByLabelText(/confirm code/i), { target: { value: '123456' } })
    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }))
    await screen.findByText(/activate two-factor authentication/i)

    const activate = screen.getByRole('button', { name: 'Activate' })
    expect(activate).toBeDisabled()
    fireEvent.click(screen.getByRole('checkbox', { name: /saved these recovery codes/i }))
    expect(activate).not.toBeDisabled()
  })

  it('cancelling the activation dialog does not activate 2FA', async () => {
    wrap()
    fireEvent.click(await screen.findByRole('button', { name: 'Enable two-factor' }))
    await screen.findByText('JBSWY3DPEHPK3PXP')
    fireEvent.change(screen.getByLabelText(/confirm code/i), { target: { value: '123456' } })
    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }))
    await screen.findByText(/activate two-factor authentication/i)

    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(screen.queryByText(/activate two-factor authentication/i)).not.toBeInTheDocument()
    expect(calls.some((c) => c.path === '/auth/totp/confirm')).toBe(false)
    // Still on the enrollment panel, not bounced back to "Enable two-factor".
    expect(screen.getByLabelText(/confirm code/i)).toBeInTheDocument()
  })

  it('acknowledging and activating calls /auth/totp/confirm and flips to enabled state with a Disable flow', async () => {
    wrap()
    fireEvent.click(await screen.findByRole('button', { name: 'Enable two-factor' }))
    await screen.findByText('JBSWY3DPEHPK3PXP')
    fireEvent.change(screen.getByLabelText(/confirm code/i), { target: { value: '123456' } })
    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }))
    await screen.findByText(/activate two-factor authentication/i)
    fireEvent.click(screen.getByRole('checkbox', { name: /saved these recovery codes/i }))
    fireEvent.click(screen.getByRole('button', { name: 'Activate' }))

    await waitFor(() => expect(calls.some((c) =>
      c.path === '/auth/totp/confirm' && c.method === 'POST'
      && JSON.stringify(c.body) === JSON.stringify({ code: '123456' }))).toBe(true))
    expect(await screen.findByRole('button', { name: 'Disable two-factor' })).toBeInTheDocument()
    expect(screen.queryByText(/activate two-factor authentication/i)).not.toBeInTheDocument()
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
    await waitFor(() => expect(notifyError).toHaveBeenCalledWith('re-authentication required'))
  })

  it('regenerate flow asks for the password, calls the regenerate endpoint, and shows ten new once-only codes', async () => {
    totpEnabled = true
    wrap()
    fireEvent.click(await screen.findByRole('button', { name: 'Regenerate recovery codes' }))
    fireEvent.change(screen.getByLabelText(/password/i), { target: { value: 'hunter2' } })
    fireEvent.click(screen.getByRole('button', { name: 'Confirm regenerate' }))

    await waitFor(() => expect(calls.some((c) =>
      c.path === '/auth/totp/recovery-codes/regenerate' && c.method === 'POST'
      && JSON.stringify(c.body) === JSON.stringify({ password: 'hunter2' }))).toBe(true))

    for (const code of NEW_RECOVERY_CODES) expect(await screen.findByText(code)).toBeInTheDocument()
    expect(screen.getByText(/shown once, store them now/i)).toBeInTheDocument()
    // The old codes are gone from the screen; only the fresh set remains.
    for (const code of RECOVERY_CODES) expect(screen.queryByText(code)).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Done' }))
    expect(await screen.findByRole('button', { name: 'Regenerate recovery codes' })).toBeInTheDocument()
  })

  it('cancelling the regenerate password prompt does not call the endpoint', async () => {
    totpEnabled = true
    wrap()
    fireEvent.click(await screen.findByRole('button', { name: 'Regenerate recovery codes' }))
    fireEvent.change(screen.getByLabelText(/password/i), { target: { value: 'hunter2' } })
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(calls.some((c) => c.path === '/auth/totp/recovery-codes/regenerate')).toBe(false)
    expect(await screen.findByRole('button', { name: 'Regenerate recovery codes' })).toBeInTheDocument()
  })

  it('surfaces a 403 re-auth error from regenerate as a toast', async () => {
    totpEnabled = true
    regenerateStatus = 403
    wrap()
    fireEvent.click(await screen.findByRole('button', { name: 'Regenerate recovery codes' }))
    fireEvent.change(screen.getByLabelText(/password/i), { target: { value: 'wrong' } })
    fireEvent.click(screen.getByRole('button', { name: 'Confirm regenerate' }))
    await waitFor(() => expect(notifyError).toHaveBeenCalledWith('re-authentication required'))
  })
})
