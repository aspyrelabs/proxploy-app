import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const { notifyError, notifySuccess } = vi.hoisted(() => ({
  notifyError: vi.fn(), notifySuccess: vi.fn(),
}))
vi.mock('../lib/notify', () => ({
  notify: { error: notifyError, success: notifySuccess, info: vi.fn(), warning: vi.fn() },
}))

// Only `api` is faked: apiErrorDetail and ApiError are the real ones, so what
// the user is told about a refused password is decided by the same code the
// app runs.
vi.mock('../api/client', async () => {
  const actual = await vi.importActual<typeof import('../api/client')>('../api/client')
  return { ...actual, api: vi.fn() }
})

import { ApiError, api } from '../api/client'
import { AccountCard } from '../components/AccountCard'
import { PasswordCard } from '../components/PasswordCard'
import { SessionsCard } from '../components/SessionsCard'

const ME = { id: 1, email: 'admin@example.com', display_name: 'Admin', role: 'owner',
  totp_enabled: false }

const SESSIONS = [
  { id: 1, ip: '10.0.0.1', user_agent: 'Chrome', created_at: '2026-08-01T00:00:00',
    last_seen_at: '2026-08-04T00:00:00', current: true },
  { id: 2, ip: '10.0.0.2', user_agent: 'Firefox', created_at: '2026-08-02T00:00:00',
    last_seen_at: '2026-08-03T00:00:00', current: false },
]

// TotpCard reads the entitlement before it renders anything.
const ENTITLEMENTS = { tier: 'pro', features: { 'auth.totp': true }, grace: null }

let loginFails = false

function mockApi() {
  vi.mocked(api).mockImplementation((path: string, opts?: RequestInit) => {
    const method = opts?.method
    if (path === '/auth/me') return Promise.resolve(ME) as Promise<never>
    if (path === '/entitlements') return Promise.resolve(ENTITLEMENTS) as Promise<never>
    if (path === '/auth/sessions' && !method) return Promise.resolve(SESSIONS) as Promise<never>
    if (path === '/auth/login' && loginFails) {
      return Promise.reject(new ApiError(401, { detail: 'invalid credentials' }))
    }
    return Promise.resolve({ ok: true }) as Promise<never>
  })
}

const wrap = (ui: React.ReactNode) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

/** These were one page, routes/profile.tsx, which is gone: Account and
 *  Password are their own cards in Settings' Profile section now, and Sessions
 *  is a section of its own beside it.
 *
 *  SessionsCard is still mounted next to PasswordCard here, because the claim
 *  under test is that changing a password invalidates ['auth', 'sessions'],
 *  and a query nobody is subscribed to cannot be observed refetching. That the
 *  two now live in different sections is exactly why the invalidation matters:
 *  the card refetches whenever the reader arrives at it. */
function renderPassword() {
  return wrap(<><PasswordCard /><SessionsCard /></>)
}

async function setPassword(pw = 'a-long-enough-password') {
  await waitFor(() => expect(screen.getByLabelText(/new password/i)).toBeInTheDocument())
  fireEvent.change(screen.getByLabelText(/new password/i), { target: { value: pw } })
  fireEvent.click(screen.getByRole('button', { name: /set new password/i }))
}

const sessionReads = () =>
  vi.mocked(api).mock.calls.filter(([path, opts]) =>
    path === '/auth/sessions' && !(opts as RequestInit | undefined)?.method).length

describe('PasswordCard', () => {
  beforeEach(() => {
    vi.mocked(api).mockReset()
    notifyError.mockClear()
    notifySuccess.mockClear()
    loginFails = false
    mockApi()
  })

  it('refreshes the sessions list after the password changes', async () => {
    // The reset revokes every other session server-side. Without an
    // invalidation the Sessions card went on listing sessions that no longer
    // exist, and the success toast said they were signed out while the table
    // disagreed.
    renderPassword()
    await waitFor(() => expect(sessionReads()).toBe(1))
    const before = sessionReads()

    await setPassword()

    await waitFor(() => expect(notifySuccess).toHaveBeenCalled())
    await waitFor(() => expect(sessionReads()).toBeGreaterThan(before))
  })

  it('reports a failed re-login as a changed password, not as a bad password', async () => {
    // One try used to wrap both POSTs, so a re-login that failed after a
    // password that changed perfectly well was reported as
    // "Could not set the password (12+ characters)": it blamed the user's
    // input, and it told them their password had not changed when it had.
    loginFails = true
    renderPassword()
    await setPassword()

    await waitFor(() => expect(notifyError).toHaveBeenCalled())
    const [title, options] = notifyError.mock.calls[0]
    const said = `${title} ${(options as { description?: string } | undefined)?.description ?? ''}`
    expect(said).not.toMatch(/12|characters/i)
    expect(said).toMatch(/password was changed/i)
    expect(said).toMatch(/sign in again/i)
    expect(notifySuccess).not.toHaveBeenCalled()
  })

  it('reports a refused password in the backend\'s own words', async () => {
    vi.mocked(api).mockImplementation((path: string, opts?: RequestInit) => {
      if (path === '/auth/me') return Promise.resolve(ME) as Promise<never>
    if (path === '/entitlements') return Promise.resolve(ENTITLEMENTS) as Promise<never>
      if (path === '/auth/sessions' && !opts?.method) return Promise.resolve(SESSIONS) as Promise<never>
      if (path.endsWith('/password')) {
        return Promise.reject(new ApiError(403, { detail: 'not allowed to set this password' }))
      }
      return Promise.resolve({ ok: true }) as Promise<never>
    })
    renderPassword()
    await setPassword()

    await waitFor(() => expect(notifyError).toHaveBeenCalledWith('not allowed to set this password'))
    // A password that never changed must not claim it did.
    expect(notifyError.mock.calls[0][0]).not.toMatch(/was changed/i)
    // And no login is attempted on top of a password that was refused.
    expect(vi.mocked(api).mock.calls.some(([p]) => p === '/auth/login')).toBe(false)
  })
})

describe('AccountCard loading state', () => {
  beforeEach(() => {
    vi.mocked(api).mockReset()
  })

  it('never nests a div (SkeletonLine) inside a p while /auth/me is pending', async () => {
    // React's own console error, from the real running app: "In HTML, <div>
    // cannot be a descendant of <p>." The Email and Role readouts wrapped
    // their loading SkeletonLine (a div) in a <p>. Moved with the card out of
    // routes/profile.tsx, so the guard moved with it.
    let resolveMe!: (v: typeof ME) => void
    const mePromise = new Promise<typeof ME>((r) => { resolveMe = r })
    vi.mocked(api).mockImplementation((path: string) => {
      if (path === '/auth/me') return mePromise as Promise<never>
      if (path === '/entitlements') return Promise.resolve(ENTITLEMENTS) as Promise<never>
      if (path === '/auth/sessions') return Promise.resolve(SESSIONS) as Promise<never>
      return Promise.resolve({ ok: true }) as Promise<never>
    })
    const { container } = wrap(<AccountCard />)

    // Pending: the skeleton is up, which is the state that used to nest a div in a p.
    await waitFor(() => expect(container.querySelectorAll('.animate-pulse').length).toBeGreaterThan(0))
    for (const p of Array.from(container.querySelectorAll('p'))) {
      expect(p.querySelector('div')).toBeNull()
    }

    resolveMe(ME)
    await waitFor(() => expect(screen.getByText(ME.email)).toBeInTheDocument())
  })
})
