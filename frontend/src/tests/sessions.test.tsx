import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { toastError } = vi.hoisted(() => ({ toastError: vi.fn() }))
vi.mock('sonner', () => ({ toast: { error: toastError, success: vi.fn() } }))

type Call = { path: string; method?: string }
const calls: Call[] = []
let sessionRows: Array<{ id: number; ip: string | null; user_agent: string | null
  created_at: string; last_seen_at: string | null; current: boolean }> = []

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
    if (path === '/auth/sessions' && !method) return Promise.resolve(sessionRows)
    const del = path.match(/^\/auth\/sessions\/(\d+)$/)
    if (del && method === 'DELETE') {
      calls.push({ path, method })
      sessionRows = sessionRows.filter((s) => s.id !== Number(del[1]))
      return Promise.resolve({ ok: true })
    }
    calls.push({ path, method })
    return Promise.resolve(null)
  }),
}))

import { SessionsCard } from '../components/SessionsCard'

const wrap = () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={qc}><SessionsCard /></QueryClientProvider>)
}

describe('SessionsCard', () => {
  beforeEach(() => {
    calls.length = 0
    toastError.mockClear()
    sessionRows = [
      { id: 1, ip: '10.0.0.1', user_agent: 'Chrome', created_at: '2026-08-01T00:00:00',
        last_seen_at: '2026-08-04T00:00:00', current: true },
      { id: 2, ip: '10.0.0.2', user_agent: 'Firefox', created_at: '2026-08-02T00:00:00',
        last_seen_at: '2026-08-03T00:00:00', current: false },
      { id: 3, ip: '10.0.0.3', user_agent: 'Safari', created_at: '2026-08-02T00:00:00',
        last_seen_at: '2026-08-03T00:00:00', current: false },
    ]
  })
  afterEach(() => vi.restoreAllMocks())

  it('lists sessions from GET /auth/sessions and marks the current one', async () => {
    wrap()
    expect(await screen.findByText('10.0.0.1')).toBeInTheDocument()
    expect(screen.getByText('10.0.0.2')).toBeInTheDocument()
    expect(screen.getByText('10.0.0.3')).toBeInTheDocument()
    expect(screen.getByText('current')).toBeInTheDocument()
  })

  it('does not offer Sign out on the current row', async () => {
    wrap()
    await screen.findByText('10.0.0.1')
    const row = screen.getByText('10.0.0.1').closest('tr')!
    expect(within(row).queryByRole('button', { name: 'Sign out' })).toBeNull()
  })

  it('Sign out on a row calls DELETE for that session only', async () => {
    wrap()
    await screen.findByText('10.0.0.2')
    const row = screen.getByText('10.0.0.2').closest('tr')!
    fireEvent.click(within(row).getByRole('button', { name: 'Sign out' }))
    await waitFor(() => expect(calls.some((c) =>
      c.path === '/auth/sessions/2' && c.method === 'DELETE')).toBe(true))
    expect(calls.some((c) => c.path === '/auth/sessions/1')).toBe(false)
  })

  it('"Sign out everywhere else" loops every non-current row', async () => {
    wrap()
    fireEvent.click(await screen.findByRole('button', { name: 'Sign out everywhere else' }))
    await waitFor(() => {
      expect(calls.some((c) => c.path === '/auth/sessions/2' && c.method === 'DELETE')).toBe(true)
      expect(calls.some((c) => c.path === '/auth/sessions/3' && c.method === 'DELETE')).toBe(true)
    })
    expect(calls.some((c) => c.path === '/auth/sessions/1' && c.method === 'DELETE')).toBe(false)
  })
})
