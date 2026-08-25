/**
 * The signup step reports what actually went wrong.
 *
 * It reported everything as "Could not create the admin account (password: 12+
 * characters)". One try wrapped both the create and the sign-in that follows
 * it, and the catch blamed the password unconditionally, so a rejected EMAIL
 * told the operator their password was too short while they looked at a
 * perfectly good one and tried longer and longer ones. Reported from a fresh
 * install, 2026-08-26, against a .local address the validator refuses as a
 * reserved name.
 *
 * profile-password.test.tsx already pinned this for the password panel. The
 * wizard kept its own copy of the bug.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

let failCreate: unknown = null
let failLogin: unknown = null
const calls: string[] = []

// Only `api` is replaced. ApiError and apiErrorDetail stay the REAL ones, so
// this exercises the same instanceof check and the same pydantic-list parsing
// the app runs, rather than a stand-in that could agree with a broken guess.
vi.mock('../api/client', async () => {
  const actual = await vi.importActual<typeof import('../api/client')>('../api/client')
  return {
    ...actual,
    api: vi.fn((path: string) => {
      calls.push(path)
      if (path === '/users' && failCreate) return Promise.reject(failCreate)
      if (path === '/auth/login' && failLogin) return Promise.reject(failLogin)
      return Promise.resolve({})
    }),
  }
})

import { ApiError } from '../api/client'
import { AdminAccountStep } from '../components/AdminAccountStep'

const wrap = (onCreated = () => {}) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      {/* existing=null is the first-run case: no admin yet, which is the
          only state this wizard step is reachable in. */}
      <AdminAccountStep existing={null} onCreated={onCreated} />
    </QueryClientProvider>)
}

const fillAndSubmit = async () => {
  fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'a@test.local' } })
  fireEvent.change(screen.getByLabelText('Display name'), { target: { value: 'A' } })
  fireEvent.change(screen.getByLabelText('Password (12+ chars)'),
                   { target: { value: 'Passw0rd123!' } })
  fireEvent.click(screen.getByRole('button', { name: 'Review' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Create account' }))
}

beforeEach(() => { failCreate = null; failLogin = null; calls.length = 0 })

describe('creating the first admin', () => {
  it('reports a rejected email as an email problem, not a password one', async () => {
    failCreate = new ApiError(422, { detail: [{ type: 'value_error',
      loc: ['body', 'email'],
      msg: 'value is not a valid email address: The part after the @-sign is a '
         + 'special-use or reserved name that cannot be used with email.' }] })
    wrap()
    await fillAndSubmit()

    const shown = await screen.findByText(/not a valid email address/i)
    expect(shown).toBeInTheDocument()
    expect(screen.queryByText(/12\+ characters/i)).toBeNull()
  })

  it('does not call it a failed signup when only the sign-in failed', async () => {
    // The account EXISTS by then. Sending someone back to the form to make it
    // a second time is worse than saying what happened.
    failLogin = new ApiError(500, { detail: 'boom' })
    wrap()
    await fillAndSubmit()

    await waitFor(() => expect(calls).toContain('/auth/login'))
    expect(await screen.findByText(/account was created/i)).toBeInTheDocument()
    expect(screen.queryByText(/12\+ characters/i)).toBeNull()
  })

  it('still accepts a twelve character password, which was never the problem', async () => {
    const onCreated = vi.fn()
    wrap(onCreated)
    await fillAndSubmit()
    await waitFor(() => expect(onCreated).toHaveBeenCalled())
  })
})
