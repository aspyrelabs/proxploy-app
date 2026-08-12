import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { notifyError } = vi.hoisted(() => ({ notifyError: vi.fn() }))
vi.mock('../lib/notify', () => ({ notify: { error: notifyError, success: vi.fn(), info: vi.fn(), warning: vi.fn() } }))

type Call = { path: string; method?: string; body: unknown }
const calls: Call[] = []
let tokensAllowed = true
let listRows: any[] = []
let createStatus: 201 | 422 = 201
let listError = false

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
      return Promise.resolve({ tier: 'builtin', features: { 'api.tokens': tokensAllowed }, grace: null, clock_skew: false })
    }
    if (path === '/api-keys' && !method) {
      if (listError) return Promise.reject(new ApiError(502, { detail: 'boom' }))
      return Promise.resolve(listRows)
    }
    if (path === '/api-keys' && method === 'POST') {
      const body = opts?.body ? JSON.parse(String(opts.body)) : null
      calls.push({ path, method, body })
      if (createStatus === 422) return Promise.reject(new ApiError(422, { detail: 'unknown scope: \'gizmo:write\'' }))
      return Promise.resolve({
        id: 99, name: body.name, prefix: 'ppk_ab12', scopes: body.scopes,
        expires_at: body.expires_at ?? null, last_used_at: null, revoked_at: null,
        created_at: '2026-08-05T00:00:00', key: 'ppk_ab12cdEXAMPLERAW',
      })
    }
    const revokeMatch = path.match(/^\/api-keys\/(\d+)$/)
    if (revokeMatch && method === 'DELETE') {
      calls.push({ path, method, body: null })
      return Promise.resolve(null)
    }
    calls.push({ path, method, body: opts?.body ? JSON.parse(String(opts.body)) : null })
    return Promise.resolve(null)
  }),
}))

import { ApiKeysCard } from '../components/ApiKeysCard'

const wrap = () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={qc}><ApiKeysCard /></QueryClientProvider>)
}

describe('ApiKeysCard', () => {
  beforeEach(() => {
    calls.length = 0
    notifyError.mockClear()
    tokensAllowed = true
    createStatus = 201
    listError = false
    listRows = [
      { id: 1, name: 'CI runner', prefix: 'ppk_zzzz', scopes: ['read'],
        expires_at: null, last_used_at: '2026-08-01T12:00:00', revoked_at: null,
        created_at: '2026-07-01T00:00:00' },
    ]
  })
  afterEach(() => vi.restoreAllMocks())

  it('gates the whole card behind api.tokens: no fetch, plan message shown', async () => {
    tokensAllowed = false
    wrap()
    expect(await screen.findByText('Not included in your plan.')).toBeInTheDocument()
    expect(calls.some((c) => c.path === '/api-keys')).toBe(false)
    expect(screen.queryByRole('button', { name: 'New key' })).toBeNull()
  })

  it('says the keys could not be read rather than showing "no API keys yet"', async () => {
    listError = true
    wrap()
    expect(await screen.findByText(/API keys not readable/i)).toBeInTheDocument()
    expect(screen.queryByText('No API keys yet.')).not.toBeInTheDocument()
  })

  it('shows the real empty-keys copy when there genuinely are none', async () => {
    listRows = []
    wrap()
    expect(await screen.findByText('No API keys yet.')).toBeInTheDocument()
  })

  it('lists existing keys showing prefix + ellipsis, scopes, and last-used', async () => {
    wrap()
    expect(await screen.findByText('CI runner')).toBeInTheDocument()
    expect(screen.getByText('ppk_zzzz…')).toBeInTheDocument()
    expect(screen.getByText('read')).toBeInTheDocument()
    expect(screen.getByText(new Date('2026-08-01T12:00:00').toLocaleString())).toBeInTheDocument()
  })

  it('shows the read scope plus one <resource>:write checkbox per matrix resource', async () => {
    wrap()
    fireEvent.click(await screen.findByRole('button', { name: 'New key' }))
    expect(screen.getByLabelText('read')).toBeInTheDocument()
    expect(screen.getByLabelText('host:write')).toBeInTheDocument()
    expect(screen.getByLabelText('app:write')).toBeInTheDocument()
    expect(screen.getByLabelText('team:write')).toBeInTheDocument()
  })

  it('posts the name, selected scopes and optional expiry on create', async () => {
    wrap()
    fireEvent.click(await screen.findByRole('button', { name: 'New key' }))
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'CI runner' } })
    fireEvent.click(screen.getByLabelText('app:write'))
    fireEvent.change(screen.getByLabelText('Expires (optional)'), { target: { value: '2027-01-01' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create key' }))
    await waitFor(() => expect(calls.some((c) =>
      c.path === '/api-keys' && c.method === 'POST'
      && JSON.stringify(c.body) === JSON.stringify({ name: 'CI runner', scopes: ['app:write'], expires_at: '2027-01-01' })
    )).toBe(true))
  })

  it('shows the raw key exactly once in a copy-now panel, and dismiss drops it from the DOM', async () => {
    wrap()
    fireEvent.click(await screen.findByRole('button', { name: 'New key' }))
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'new key' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create key' }))
    expect(await screen.findByText('ppk_ab12cdEXAMPLERAW')).toBeInTheDocument()
    expect(screen.getByText(/never be shown again/i)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Dismiss' }))
    expect(screen.queryByText('ppk_ab12cdEXAMPLERAW')).toBeNull()
  })

  it('never writes the raw key to localStorage', async () => {
    const setItemSpy = vi.spyOn(Storage.prototype, 'setItem')
    wrap()
    fireEvent.click(await screen.findByRole('button', { name: 'New key' }))
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'new key' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create key' }))
    await screen.findByText('ppk_ab12cdEXAMPLERAW')
    expect(setItemSpy).not.toHaveBeenCalled()
  })

  it('revoke asks for confirmation, then calls DELETE and refetches the list', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    wrap()
    fireEvent.click(await screen.findByRole('button', { name: 'Revoke' }))
    expect(window.confirm).toHaveBeenCalledWith(
      'Revoke API key "CI runner"? Anything using it stops working immediately.')
    await waitFor(() => expect(calls.some((c) =>
      c.path === '/api-keys/1' && c.method === 'DELETE')).toBe(true))
  })

  it('does not offer Revoke for an already-revoked key', async () => {
    listRows = [{ ...listRows[0], revoked_at: '2026-08-02T00:00:00' }]
    wrap()
    await screen.findByText('CI runner')
    expect(screen.getByText('revoked')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Revoke' })).toBeNull()
  })

  it('surfaces a 422 unknown-scope error from create as a toast', async () => {
    createStatus = 422
    wrap()
    fireEvent.click(await screen.findByRole('button', { name: 'New key' }))
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'x' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create key' }))
    await waitFor(() => expect(notifyError).toHaveBeenCalledWith("unknown scope: 'gizmo:write'"))
  })

  it('links to /api/docs as the full REST API surface', async () => {
    wrap()
    const link = await screen.findByRole('link', { name: 'full REST API' })
    expect(link).toHaveAttribute('href', '/api/docs')
  })
})
