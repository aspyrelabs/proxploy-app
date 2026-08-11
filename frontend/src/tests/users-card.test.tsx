import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { toastSuccess, toastError } = vi.hoisted(() => ({ toastSuccess: vi.fn(), toastError: vi.fn() }))
vi.mock('sonner', () => ({ toast: { success: toastSuccess, error: toastError } }))

const { ApiError } = vi.hoisted(() => ({
  ApiError: class extends Error {
    status: number; body: unknown
    constructor(status: number, body: unknown) { super(`API ${status}`); this.status = status; this.body = body }
  },
}))

const calls: { path: string; method?: string; body: unknown }[] = []
let userRows: any[] = []
let deactivateFails: 'last_owner' | 'self_deactivate' | null = null

vi.mock('../api/client', () => ({
  ApiError,
  api: vi.fn((path: string, opts?: RequestInit) => {
    const method = opts?.method
    if (path === '/users' && !method) return Promise.resolve(userRows)
    const body = opts?.body ? JSON.parse(String(opts.body)) : null
    calls.push({ path, method, body })
    const patchMatch = path.match(/^\/users\/(\d+)$/)
    if (patchMatch && method === 'PATCH' && body?.is_active === false && deactivateFails) {
      return Promise.reject(new ApiError(409, {
        error: deactivateFails,
        detail: deactivateFails === 'last_owner'
          ? 'this is the last active owner; promote another owner before deactivating this one'
          : 'you cannot deactivate your own account',
      }))
    }
    if (patchMatch && method === 'PATCH') return Promise.resolve({ sessions_revoked: 2 })
    return Promise.resolve(null)
  }),
}))

import { UsersCard } from '../components/UsersCard'

const wrap = () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={qc}><UsersCard /></QueryClientProvider>)
}

describe('UsersCard', () => {
  beforeEach(() => {
    calls.length = 0
    toastSuccess.mockClear(); toastError.mockClear()
    deactivateFails = null
    userRows = [
      { id: 1, email: 'owner@example.com', display_name: 'Owner', is_active: true, teams: [] },
      { id: 2, email: 'op@example.com', display_name: null, is_active: true, teams: [] },
    ]
    vi.spyOn(window, 'confirm').mockReturnValue(true)
  })
  afterEach(() => vi.restoreAllMocks())

  it('lists users with their state', async () => {
    wrap()
    expect(await screen.findByText('owner@example.com')).toBeInTheDocument()
    expect(screen.getAllByText('active').length).toBe(2)
  })

  // SKIPPED WITH THE BUTTON, NOT DELETED. The affordance this drives is
  // commented out in UsersCard.tsx until there is more than one user to manage; the mutation and the
  // endpoint behind it are untouched. Unskip when the button returns.
  it.skip('PATCHes is_active: false on deactivate, after confirmation', async () => {
    wrap()
    const rows = await screen.findAllByRole('button', { name: 'Deactivate' })
    fireEvent.click(rows[0])
    await waitFor(() => expect(calls.some((c) =>
      c.path === '/users/1' && c.method === 'PATCH'
      && JSON.stringify(c.body) === JSON.stringify({ is_active: false }))).toBe(true))
  })

  // SKIPPED WITH THE BUTTON, NOT DELETED. The affordance this drives is
  // commented out in UsersCard.tsx until there is more than one user to manage; the mutation and the
  // endpoint behind it are untouched. Unskip when the button returns.
  it.skip('surfaces the last_owner 409 as an inline message on that row, not a toast', async () => {
    deactivateFails = 'last_owner'
    wrap()
    const rows = await screen.findAllByRole('button', { name: 'Deactivate' })
    fireEvent.click(rows[0])
    expect(await screen.findByText(/last owner/i)).toBeInTheDocument()
    expect(toastError).not.toHaveBeenCalled()
  })

  // SKIPPED WITH THE BUTTON, NOT DELETED. The affordance this drives is
  // commented out in UsersCard.tsx until there is more than one user to manage; the mutation and the
  // endpoint behind it are untouched. Unskip when the button returns.
  it.skip('surfaces the self_deactivate 409 as an inline message', async () => {
    deactivateFails = 'self_deactivate'
    wrap()
    const rows = await screen.findAllByRole('button', { name: 'Deactivate' })
    fireEvent.click(rows[0])
    expect(await screen.findByText(/cannot deactivate your own account/i)).toBeInTheDocument()
    expect(toastError).not.toHaveBeenCalled()
  })
})
