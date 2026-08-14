import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { ApiError } = vi.hoisted(() => ({
  ApiError: class extends Error {
    status: number; body: unknown
    constructor(status: number, body: unknown) { super(`API ${status}`); this.status = status; this.body = body }
  },
}))

const calls: { path: string; body: any }[] = []
let capabilities: Record<string, boolean> = {
  monitoring: true, lifecycle: false, console: false, backup: false,
}
let reject = false

vi.mock('../api/client', () => ({
  ApiError,
  api: vi.fn((path: string, opts?: RequestInit) => {
    const body = opts?.body ? JSON.parse(String(opts.body)) : null
    calls.push({ path, body })
    if (path.endsWith('/credentials')) {
      if (reject) {
        return Promise.reject(new ApiError(502, {
          error: 'token_rejected',
          detail: 'the new token did not work against https://10.0.0.9:8006, '
                + 'the old one is still in place: auth failed',
        }))
      }
      return Promise.resolve({ id: 3, rotated: [`api_token:${body.capability}`] })
    }
    return Promise.resolve({ id: 3, name: 'pve-01', capabilities })
  }),
}))

import { HostCapabilityList } from '../components/HostCapabilityList'

const wrap = () => {
  const qc = new QueryClient({ defaultOptions: {
    queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={qc}>
    <HostCapabilityList hostId={3} />
  </QueryClientProvider>)
}

describe('HostCapabilityList', () => {
  beforeEach(() => {
    calls.length = 0; reject = false
    capabilities = { monitoring: true, lifecycle: false, console: false, backup: false }
  })
  afterEach(() => vi.restoreAllMocks())

  it('lists every capability, stored and missing alike', async () => {
    wrap()
    expect(await screen.findByText('Monitoring')).toBeInTheDocument()
    for (const label of ['Lifecycle', 'Console', 'Backup']) {
      expect(screen.getByText(label)).toBeInTheDocument()
    }
  })

  it('renders a capability the backend added without a second list here', async () => {
    capabilities = { ...capabilities, teleportation: false }
    wrap()
    expect(await screen.findByText('Teleportation')).toBeInTheDocument()
  })

  it('offers monitoring as rotate-only, never missing or removable', async () => {
    wrap()
    await screen.findByText('Monitoring')
    expect(screen.getByRole('button', { name: 'Rotate Monitoring token' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /remove monitoring/i })).not.toBeInTheDocument()
    // Its fields are behind the rotate control, not open as an unfilled gap.
    expect(screen.queryByLabelText('Monitoring token id')).not.toBeInTheDocument()
  })

  it('shows a missing capability as an open field, and stores it with its own key', async () => {
    wrap()
    await screen.findByText('Lifecycle')
    fireEvent.change(screen.getByLabelText('Lifecycle token id'),
                     { target: { value: 'proxploy@pve!lifecycle' } })
    fireEvent.change(screen.getByLabelText('Lifecycle token secret'),
                     { target: { value: 'lc' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add Lifecycle token' }))

    await waitFor(() => expect(calls.at(-1)).toEqual({
      path: '/hosts/3/credentials',
      body: { token_id: 'proxploy@pve!lifecycle', token_secret: 'lc',
              capability: 'lifecycle' },
    }))
  })

  it('names the capability when the node rejects its token', async () => {
    reject = true
    wrap()
    await screen.findByText('Backup')
    fireEvent.change(screen.getByLabelText('Backup token id'), { target: { value: 'x' } })
    fireEvent.change(screen.getByLabelText('Backup token secret'), { target: { value: 'y' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add Backup token' }))
    expect(await screen.findByText(/Backup: .*did not work/i)).toBeInTheDocument()
  })

  it('never submits half a token pair', async () => {
    wrap()
    await screen.findByText('Console')
    fireEvent.change(screen.getByLabelText('Console token id'), { target: { value: 'only-id' } })
    const btn = screen.getByRole('button', { name: 'Add Console token' })
    expect(btn).toBeDisabled()
    fireEvent.click(btn)
    expect(calls.filter(c => c.path.endsWith('/credentials'))).toHaveLength(0)
  })
})
