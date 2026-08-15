import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { notifyError } = vi.hoisted(() => ({ notifyError: vi.fn() }))
vi.mock('../lib/notify', () => ({ notify: { error: notifyError, success: vi.fn(), info: vi.fn(), warning: vi.fn() } }))

const calls: { path: string; method?: string; body: unknown }[] = []
let rotateResult: 'ok' | 'rejected' = 'ok'

vi.mock('../api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/client')>()),
  api: vi.fn((path: string, opts?: RequestInit) => {
    calls.push({ path, method: opts?.method, body: opts?.body ? JSON.parse(String(opts.body)) : null })
    if (rotateResult === 'rejected') {
      return Promise.reject(new ApiError(502, { error: 'token_rejected', detail: 'nope' }))
    }
    return Promise.resolve({ id: 5, rotated: ['api_token'] })
  }),
}))

import { ApiError } from '../api/client'
import { HostRotateDialog } from '../components/HostRotateDialog'

const wrap = () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={qc}>
    <HostRotateDialog hostId={5} hostName="pve1" onClose={() => {}} />
  </QueryClientProvider>)
}

describe('HostRotateDialog', () => {
  beforeEach(() => { calls.length = 0; notifyError.mockClear(); rotateResult = 'ok' })
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
    // A 502 means Proxploy could not complete the call to Proxmox itself, so
    // the toast says whose side failed rather than passing the text through
    // bare (see apiErrorDetail in api/client.ts).
    await waitFor(() => expect(notifyError).toHaveBeenCalledWith('Proxmox could not do this: nope'))
  })
})
