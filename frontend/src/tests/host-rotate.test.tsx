import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { toastError } = vi.hoisted(() => ({ toastError: vi.fn() }))
vi.mock('sonner', () => ({ toast: { error: toastError, success: vi.fn() } }))

const { ApiError } = vi.hoisted(() => ({
  ApiError: class extends Error {
    status: number; body: unknown
    constructor(status: number, body: unknown) { super(`API ${status}`); this.status = status; this.body = body }
  },
}))

const calls: { path: string; method?: string; body: unknown }[] = []
let rotateResult: 'ok' | 'rejected' = 'ok'

vi.mock('../api/client', () => ({
  ApiError,
  api: vi.fn((path: string, opts?: RequestInit) => {
    calls.push({ path, method: opts?.method, body: opts?.body ? JSON.parse(String(opts.body)) : null })
    if (rotateResult === 'rejected') {
      return Promise.reject(new ApiError(502, { error: 'token_rejected', detail: 'nope' }))
    }
    return Promise.resolve({ id: 5, rotated: ['api_token'] })
  }),
}))

import { HostRotateDialog } from '../components/HostRotateDialog'

const wrap = () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={qc}>
    <HostRotateDialog hostId={5} hostName="pve1" onClose={() => {}} />
  </QueryClientProvider>)
}

describe('HostRotateDialog', () => {
  beforeEach(() => { calls.length = 0; toastError.mockClear(); rotateResult = 'ok' })
  afterEach(() => vi.restoreAllMocks())

  it('disables Rotate and never calls the API when only the token id is filled in', () => {
    wrap()
    fireEvent.change(screen.getByLabelText('New API token id'), { target: { value: 'proxploy@pve!x' } })
    const rotateBtn = screen.getByRole('button', { name: 'Rotate' })
    expect(rotateBtn).toBeDisabled()
    fireEvent.click(rotateBtn)
    expect(calls.length).toBe(0)
    expect(screen.getByText(/must both be filled in/i)).toBeInTheDocument()
  })

  it('disables Rotate and never calls the API when only the token secret is filled in', () => {
    wrap()
    fireEvent.change(screen.getByLabelText('New API token secret'), { target: { value: 'shh' } })
    expect(screen.getByRole('button', { name: 'Rotate' })).toBeDisabled()
    expect(calls.length).toBe(0)
  })

  it('disables Rotate when nothing is filled in at all', () => {
    wrap()
    expect(screen.getByRole('button', { name: 'Rotate' })).toBeDisabled()
  })

  it('sends the full pair once both fields are filled in', async () => {
    wrap()
    fireEvent.change(screen.getByLabelText('New API token id'), { target: { value: 'proxploy@pve!x' } })
    fireEvent.change(screen.getByLabelText('New API token secret'), { target: { value: 'shh' } })
    const rotateBtn = screen.getByRole('button', { name: 'Rotate' })
    expect(rotateBtn).not.toBeDisabled()
    fireEvent.click(rotateBtn)
    await waitFor(() => expect(calls.some((c) =>
      c.path === '/hosts/5/credentials' && c.method === 'POST'
      && JSON.stringify(c.body) === JSON.stringify({ token_id: 'proxploy@pve!x', token_secret: 'shh', rotate_ssh: false })
    )).toBe(true))
  })

  it('surfaces a 502 token_rejected as a toast, the old credential stays in place', async () => {
    rotateResult = 'rejected'
    wrap()
    fireEvent.change(screen.getByLabelText('New API token id'), { target: { value: 'proxploy@pve!x' } })
    fireEvent.change(screen.getByLabelText('New API token secret'), { target: { value: 'shh' } })
    fireEvent.click(screen.getByRole('button', { name: 'Rotate' }))
    await waitFor(() => expect(toastError).toHaveBeenCalledWith('nope'))
  })
})
