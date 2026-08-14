import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { toastSuccess } = vi.hoisted(() => ({ toastSuccess: vi.fn() }))
vi.mock('../lib/notify', () => ({
  notify: { success: toastSuccess, error: vi.fn(), info: vi.fn(), warning: vi.fn() },
}))

const { ApiError } = vi.hoisted(() => ({
  ApiError: class extends Error {
    status: number; body: unknown
    constructor(status: number, body: unknown) { super(`API ${status}`); this.status = status; this.body = body }
  },
}))

let testResult: 'connected' | 'unreachable' = 'connected'
const calls: { path: string; method?: string; body: unknown }[] = []
// Finding #9: left undefined (as it always was before this fix), the mount
// GET HostCapabilityList fires renders an empty list in every test in this
// file, so Task 3's wiring only had accidental coverage. One test below sets
// this to exercise the real thing.
let hostCapabilities: Record<string, boolean> | undefined

vi.mock('../api/client', () => ({
  ApiError,
  api: vi.fn((path: string, opts?: RequestInit) => {
    const body = opts?.body ? JSON.parse(String(opts.body)) : null
    calls.push({ path, method: opts?.method, body })
    if (path.endsWith('/test')) {
      return Promise.resolve({ id: 1, status: testResult, pve_version: '8.4.1' })
    }
    if (path.endsWith('/credentials')) {
      return Promise.resolve({ id: 1, rotated: ['api_token'] })
    }
    if (path === '/hosts/1' && !opts?.method) {
      // HostCapabilityList's own mount GET.
      return Promise.resolve({ id: 1, name: 'pve1', capabilities: hostCapabilities })
    }
    // PATCH /hosts/{id}
    return Promise.resolve({ id: 1, node_shell_enabled: false })
  }),
}))

import { HostEditDialog } from '../components/HostEditDialog'

const host = { name: 'pve1', address: 'https://10.0.0.5:8006' }

const wrap = (onClose = vi.fn()) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <HostEditDialog hostId={1} host={host} onClose={onClose} />
    </QueryClientProvider>)
  return onClose
}

describe('HostEditDialog', () => {
  beforeEach(() => { testResult = 'connected'; calls.length = 0; toastSuccess.mockClear(); hostCapabilities = undefined })
  afterEach(() => vi.restoreAllMocks())

  it('starts pre-filled with the current name and address', () => {
    wrap()
    expect(screen.getByLabelText(/name/i)).toHaveValue('pve1')
    expect(screen.getByLabelText(/^address$/i)).toHaveValue('https://10.0.0.5:8006')
  })

  it('PATCHes only the changed name and address, not the token fields', async () => {
    wrap()
    fireEvent.change(screen.getByLabelText(/name/i), { target: { value: 'pve1-renamed' } })
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }))
    await waitFor(() => expect(calls.some((c) => c.method === 'PATCH')).toBe(true))
    const patch = calls.find((c) => c.method === 'PATCH')!
    expect(patch.path).toBe('/hosts/1')
    expect(patch.body).toEqual({ name: 'pve1-renamed' })
  })

  it('sends address changes the same way', async () => {
    wrap()
    fireEvent.change(screen.getByLabelText(/^address$/i), { target: { value: 'https://10.0.0.9:8006' } })
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }))
    await waitFor(() => expect(calls.some((c) => c.method === 'PATCH')).toBe(true))
    expect(calls.find((c) => c.method === 'PATCH')!.body).toEqual({ address: 'https://10.0.0.9:8006' })
  })

  // The composition this dialog exists for: reuse POST /{id}/credentials
  // (HostRotateDialog's own endpoint) rather than a second credential path.
  it('reuses POST /hosts/{id}/credentials for the token id and secret', async () => {
    wrap()
    fireEvent.change(screen.getByLabelText(/monitoring token id/i), { target: { value: 'proxploy@pve!new' } })
    fireEvent.change(screen.getByLabelText(/monitoring token secret/i), { target: { value: 'newsecret' } })
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }))
    await waitFor(() => expect(calls.some((c) => c.path === '/hosts/1/credentials')).toBe(true))
    const cred = calls.find((c) => c.path === '/hosts/1/credentials')!
    expect(cred.method).toBe('POST')
    expect(cred.body).toEqual({ token_id: 'proxploy@pve!new', token_secret: 'newsecret', rotate_ssh: false })
  })

  it('does not call PATCH at all when only credentials changed', async () => {
    wrap()
    fireEvent.change(screen.getByLabelText(/monitoring token id/i), { target: { value: 'proxploy@pve!new' } })
    fireEvent.change(screen.getByLabelText(/monitoring token secret/i), { target: { value: 'newsecret' } })
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }))
    await waitFor(() => expect(calls.some((c) => c.path === '/hosts/1/credentials')).toBe(true))
    expect(calls.some((c) => c.method === 'PATCH')).toBe(false)
  })

  it('saves the address before rotating credentials, so the new token is checked against the new address', async () => {
    wrap()
    fireEvent.change(screen.getByLabelText(/^address$/i), { target: { value: 'https://10.0.0.9:8006' } })
    fireEvent.change(screen.getByLabelText(/monitoring token id/i), { target: { value: 'proxploy@pve!new' } })
    fireEvent.change(screen.getByLabelText(/monitoring token secret/i), { target: { value: 'newsecret' } })
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }))
    await waitFor(() => expect(calls.some((c) => c.path === '/hosts/1/credentials')).toBe(true))
    const patchIndex = calls.findIndex((c) => c.method === 'PATCH')
    const credIndex = calls.findIndex((c) => c.path === '/hosts/1/credentials')
    expect(patchIndex).toBeGreaterThanOrEqual(0)
    expect(patchIndex).toBeLessThan(credIndex)
  })

  it('refuses a half-filled token pair the same way HostRotateDialog does', async () => {
    wrap()
    fireEvent.change(screen.getByLabelText(/monitoring token id/i), { target: { value: 'proxploy@pve!new' } })
    expect(screen.getByRole('button', { name: /^save$/i })).toBeDisabled()
  })

  it('disables Save when nothing changed', () => {
    wrap()
    expect(screen.getByRole('button', { name: /^save$/i })).toBeDisabled()
  })

  it('lets the operator verify the connection on demand, before saving anything', async () => {
    wrap()
    fireEvent.click(screen.getByRole('button', { name: /test connection/i }))
    await waitFor(() => expect(calls.some((c) => c.path === '/hosts/1/test')).toBe(true))
    expect(await screen.findByText(/connected, pve 8\.4\.1/i)).toBeInTheDocument()
    // Nothing was changed, so nothing was saved or rotated. (The dialog's own
    // HostCapabilityList does a harmless GET /hosts/1 of its own on mount to
    // show capability state -- that read is not a save and is not what this
    // assertion is about.)
    expect(calls.some((c) => c.method === 'PATCH' || c.path === '/hosts/1/credentials')).toBe(false)
  })

  it('verifies again after a successful save, and closes once that connects', async () => {
    const onClose = wrap()
    fireEvent.change(screen.getByLabelText(/name/i), { target: { value: 'pve1-renamed' } })
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }))
    await waitFor(() => expect(calls.some((c) => c.path === '/hosts/1/test')).toBe(true))
    await waitFor(() => expect(onClose).toHaveBeenCalled())
    expect(toastSuccess).toHaveBeenCalled()
  })

  // The requirement this test is here for: a failed verify must be seen, not
  // silently treated as a clean save.
  it('surfaces a failed verify after saving instead of silently closing', async () => {
    testResult = 'unreachable'
    const onClose = wrap()
    fireEvent.change(screen.getByLabelText(/^address$/i), { target: { value: 'https://10.0.0.9:8006' } })
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }))
    await waitFor(() => expect(calls.some((c) => c.path === '/hosts/1/test')).toBe(true))
    expect(await screen.findByText(/could not connect/i)).toBeInTheDocument()
    // The save itself is not undone or hidden -- the dialog just does not
    // pretend everything is fine and close on top of the failure.
    expect(onClose).not.toHaveBeenCalled()
  })

  it('surfaces a PATCH failure without attempting the credentials call', async () => {
    wrap()
    // Finding #8: reject by path+method instead of "the next call after the
    // mount GET resolves" -- that depended on call ordering and on there
    // being exactly one mount GET, neither of which this test needs to know.
    const { api } = await import('../api/client')
    const original = vi.mocked(api).getMockImplementation()!
    vi.mocked(api).mockImplementation((path: string, opts?: RequestInit) => {
      if (path === '/hosts/1' && opts?.method === 'PATCH') {
        return Promise.reject(new ApiError(409, { detail: 'a host with that name already exists' }))
      }
      return original(path, opts)
    })
    fireEvent.change(screen.getByLabelText(/name/i), { target: { value: 'taken-name' } })
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }))
    expect(await screen.findByText(/a host with that name already exists/i)).toBeInTheDocument()
    vi.mocked(api).mockImplementation(original)
  })

  // Finding #9: exercise HostCapabilityList's real wiring inside this dialog
  // instead of relying on it always rendering empty here.
  it('renders a capability row when the host reports capabilities', async () => {
    hostCapabilities = { monitoring: true, lifecycle: false, console: false, backup: false }
    wrap()
    expect(await screen.findByText('Lifecycle')).toBeInTheDocument()
  })
})
