import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { RouteError } from '../components/RouteError'

describe('RouteError', () => {
  it('offers a retry for an unreachable backend', () => {
    const reset = vi.fn()
    render(<RouteError error={new TypeError('Failed to fetch')} reset={reset} />)
    fireEvent.click(screen.getByRole('button', { name: /try again/i }))
    expect(reset).toHaveBeenCalled()
  })

  it('distinguishes a broken app from an unreachable backend', () => {
    render(<RouteError error={new Error('Cannot read properties of undefined')} />)
    expect(screen.getByText(/something in Proxploy broke/i)).toBeInTheDocument()
  })

  it('uses theme tokens, never inline colours', () => {
    // The whole reason the built-in fallback is unacceptable.
    const { container } = render(<RouteError error={new Error('x')} />)
    expect(container.innerHTML).not.toMatch(/style="[^"]*(#[0-9a-f]{3,6}|rgb\()/i)
  })
})

// shell.tsx's beforeLoad is the live path into F1: it calls /meta/onboarding
// unguarded (errorComponent is deliberately what renders that failure now)
// and used to redirect /auth/me's *any* failure to /login, which made a
// broken backend indistinguishable from "not signed in". These tests exercise
// that function directly rather than through a full router render.
const mockApi = vi.fn()
vi.mock('../api/client', () => ({
  ApiError: class ApiError extends Error {
    status: number
    body: unknown
    constructor(status: number, body: unknown) {
      super(`API ${status}`)
      this.status = status
      this.body = body
    }
  },
  api: (...args: unknown[]) => mockApi(...args),
}))

describe("shell.tsx's beforeLoad", () => {
  it('does not swallow the redirect thrown for incomplete onboarding', async () => {
    // The onboarding check's redirect must reach the router unchanged — it
    // must not be reinterpreted by the /auth/me catch below it, since that
    // catch never even runs in this path.
    const { isRedirect } = await import('@tanstack/react-router')
    const { shellRoute } = await import('../routes/shell')
    const { ApiError } = await import('../api/client')
    mockApi.mockImplementationOnce(() => Promise.resolve({ complete: false }))

    let thrown: unknown
    try {
      await shellRoute.options.beforeLoad!({} as never)
    } catch (e) {
      thrown = e
    }
    expect(isRedirect(thrown)).toBe(true)
    expect(thrown).not.toBeInstanceOf(ApiError)
  })

  it('redirects to /login on a 401 from /auth/me', async () => {
    const { isRedirect } = await import('@tanstack/react-router')
    const { shellRoute } = await import('../routes/shell')
    const { ApiError } = await import('../api/client')
    mockApi.mockImplementationOnce(() => Promise.resolve({ complete: true }))
    mockApi.mockImplementationOnce(() => Promise.reject(new ApiError(401, {})))

    let thrown: unknown
    try {
      await shellRoute.options.beforeLoad!({} as never)
    } catch (e) {
      thrown = e
    }
    expect(isRedirect(thrown)).toBe(true)
  })

  it('re-throws a non-401 failure from /auth/me instead of bouncing to /login', async () => {
    // A 500 is not "please sign in" — the regression this task closes.
    const { isRedirect } = await import('@tanstack/react-router')
    const { shellRoute } = await import('../routes/shell')
    const { ApiError } = await import('../api/client')
    mockApi.mockImplementationOnce(() => Promise.resolve({ complete: true }))
    mockApi.mockImplementationOnce(() => Promise.reject(new ApiError(500, {})))

    let thrown: unknown
    try {
      await shellRoute.options.beforeLoad!({} as never)
    } catch (e) {
      thrown = e
    }
    expect(isRedirect(thrown)).toBe(false)
    expect(thrown).toBeInstanceOf(ApiError)
    expect((thrown as InstanceType<typeof ApiError>).status).toBe(500)
  })

  it('does not throw when onboarding is complete and auth succeeds', async () => {
    const { shellRoute } = await import('../routes/shell')
    mockApi.mockImplementationOnce(() => Promise.resolve({ complete: true }))
    mockApi.mockImplementationOnce(() => Promise.resolve({ id: 1 }))

    await expect(shellRoute.options.beforeLoad!({} as never)).resolves.toBeUndefined()
  })
})
