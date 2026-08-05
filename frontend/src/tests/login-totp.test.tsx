import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const { ApiError } = vi.hoisted(() => ({
  ApiError: class extends Error {
    status: number; body: unknown
    constructor(status: number, body: unknown) { super(`API ${status}`); this.status = status; this.body = body }
  },
}))

let oidcEnabled = false
let totpRequired = false
let totpCodeFails = false
const posted: { path: string; body: any }[] = []

vi.mock('../api/client', () => ({
  ApiError,
  api: vi.fn((path: string, opts?: RequestInit) => {
    if (path === '/meta/onboarding') {
      posted.push({ path, body: null })
      return Promise.resolve({ admin_exists: true, host_added: true, complete: true, oidc: oidcEnabled })
    }
    if (path === '/auth/login') {
      posted.push({ path, body: opts?.body ? JSON.parse(String(opts.body)) : null })
      if (totpRequired) return Promise.resolve({ totp_required: true, pending: 'PEND-TOKEN' })
      return Promise.resolve({ ok: true, user: { id: 1, email: 'a@b.com', display_name: null, role: 'owner' } })
    }
    if (path === '/auth/totp') {
      posted.push({ path, body: opts?.body ? JSON.parse(String(opts.body)) : null })
      if (totpCodeFails) return Promise.reject(new ApiError(401, { error: 'invalid or expired code' }))
      return Promise.resolve({ ok: true, user: { id: 1, email: 'a@b.com', display_name: null, role: 'owner' } })
    }
    return Promise.resolve(null)
  }),
}))

import { LoginForm } from '../components/LoginForm'

async function loginWithPassword(onSuccess: () => void = () => {}) {
  render(<LoginForm onSuccess={onSuccess} />)
  fireEvent.change(screen.getByLabelText(/email/i), { target: { value: 'a@b.com' } })
  fireEvent.change(screen.getByLabelText(/password/i), { target: { value: 'hunter2hunter2' } })
  fireEvent.click(screen.getByRole('button', { name: /sign in/i }))
  await waitFor(() => expect(posted.some(p => p.path === '/auth/login')).toBe(true))
}

describe('LoginForm — TOTP step', () => {
  beforeEach(() => {
    oidcEnabled = false
    totpRequired = false
    totpCodeFails = false
    posted.length = 0
  })

  it('swaps the password form for a single code input when totp_required comes back', async () => {
    totpRequired = true
    await loginWithPassword()
    expect(await screen.findByLabelText(/authentication code/i)).toBeInTheDocument()
    expect(screen.queryByLabelText(/^email$/i)).toBeNull()
    expect(screen.queryByLabelText(/^password$/i)).toBeNull()
    expect(screen.getByText(/recovery code/i)).toBeInTheDocument()
  })

  it('posts {pending, code} to /auth/totp and navigates on success', async () => {
    totpRequired = true
    const onSuccess = vi.fn()
    await loginWithPassword(onSuccess)
    const codeInput = await screen.findByLabelText(/authentication code/i)
    fireEvent.change(codeInput, { target: { value: '123456' } })
    fireEvent.click(screen.getByRole('button', { name: /verify/i }))
    await waitFor(() => expect(posted.some(p =>
      p.path === '/auth/totp'
      && JSON.stringify(p.body) === JSON.stringify({ pending: 'PEND-TOKEN', code: '123456' }),
    )).toBe(true))
    await waitFor(() => expect(onSuccess).toHaveBeenCalled())
  })

  it('shows a retry message on a rejected code and keeps the pending token', async () => {
    totpRequired = true
    totpCodeFails = true
    await loginWithPassword()
    const codeInput = await screen.findByLabelText(/authentication code/i)
    fireEvent.change(codeInput, { target: { value: '000000' } })
    fireEvent.click(screen.getByRole('button', { name: /verify/i }))
    expect(await screen.findByText(/code was not accepted.*recovery code/i)).toBeInTheDocument()
    // still on the code screen — the pending token was not discarded, no re-login required
    expect(screen.getByLabelText(/authentication code/i)).toBeInTheDocument()
  })

  it('does not render an SSO link when onboarding reports oidc: false', async () => {
    render(<LoginForm onSuccess={() => {}} />)
    await waitFor(() => expect(posted.some(p => p.path === '/meta/onboarding')).toBe(true))
    expect(screen.queryByRole('link', { name: /sso/i })).toBeNull()
  })

  it('renders <a href="/api/v1/auth/oidc/login"> when onboarding reports oidc: true', async () => {
    oidcEnabled = true
    render(<LoginForm onSuccess={() => {}} />)
    const link = await screen.findByRole('link', { name: /sso/i })
    expect(link).toHaveAttribute('href', '/api/v1/auth/oidc/login')
  })
})
