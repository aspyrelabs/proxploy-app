import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { ApiError } = vi.hoisted(() => ({
  ApiError: class extends Error {
    status: number; body: unknown
    constructor(status: number, body: unknown) { super(`API ${status}`); this.status = status; this.body = body }
  },
}))

const calls: { path: string; body: any }[] = []
// Which capability the fake node rejects, by capability key.
let reject: string | null = null

vi.mock('../api/client', () => ({
  ApiError,
  api: vi.fn((path: string, opts?: RequestInit) => {
    const body = opts?.body ? JSON.parse(String(opts.body)) : null
    calls.push({ path, body })
    if (path === '/hosts') return Promise.resolve({ id: 7, name: body.name })
    if (path.endsWith('/credentials')) {
      if (body.capability === reject) {
        return Promise.reject(new ApiError(502, {
          error: 'token_rejected',
          detail: 'the new token did not work against https://10.0.0.5:8006, '
                + 'the old one is still in place: auth failed',
        }))
      }
      return Promise.resolve({ id: 7, rotated: [`api_token:${body.capability}`] })
    }
    return Promise.resolve({})
  }),
}))

import { HostForm } from '../components/HostForm'

const fill = (label: string, value: string) =>
  fireEvent.change(screen.getByLabelText(label), { target: { value } })

const fillHost = () => {
  fill('Name', 'pve-01')
  fill('Address', 'https://10.0.0.5:8006')
  fill('API token id', 'proxploy@pve!monitoring')
  fill('API token secret', 'mon-secret')
}

const credentialCalls = () => calls.filter(c => c.path.endsWith('/credentials'))

describe('HostForm capability tokens', () => {
  beforeEach(() => { calls.length = 0; reject = null })
  afterEach(() => vi.restoreAllMocks())

  it('offers a token field for each capability still ticked, and none for the unticked', () => {
    render(<HostForm onCreated={() => {}} />)
    expect(screen.getByLabelText('Lifecycle token id')).toBeInTheDocument()
    fireEvent.click(screen.getByLabelText(/^Lifecycle$/))
    expect(screen.queryByLabelText('Lifecycle token id')).not.toBeInTheDocument()
    expect(screen.getByLabelText('Backup token id')).toBeInTheDocument()
  })

  it('creates the host, then stores one capability token per filled pair', async () => {
    const onCreated = vi.fn()
    render(<HostForm onCreated={onCreated} />)
    fillHost()
    fill('Lifecycle token id', 'proxploy@pve!lifecycle')
    fill('Lifecycle token secret', 'lc-secret')
    fireEvent.click(screen.getByRole('button', { name: 'Add host' }))

    await waitFor(() => expect(onCreated).toHaveBeenCalledWith({ id: 7, name: 'pve-01' }))
    expect(calls[0].path).toBe('/hosts')
    expect(credentialCalls()).toEqual([{
      path: '/hosts/7/credentials',
      body: { token_id: 'proxploy@pve!lifecycle', token_secret: 'lc-secret',
              capability: 'lifecycle' },
    }])
  })

  it('skips a capability whose token pair was left blank', async () => {
    const onCreated = vi.fn()
    render(<HostForm onCreated={onCreated} />)
    fillHost()
    fill('Console token id', 'proxploy@pve!console')  // secret left empty
    fireEvent.click(screen.getByRole('button', { name: 'Add host' }))
    await waitFor(() => expect(onCreated).toHaveBeenCalled())
    expect(credentialCalls()).toEqual([])
  })

  it('names the rejected capability, keeps the host, and does not advance', async () => {
    reject = 'console'
    const onCreated = vi.fn()
    render(<HostForm onCreated={onCreated} />)
    fillHost()
    fill('Lifecycle token id', 'proxploy@pve!lifecycle')
    fill('Lifecycle token secret', 'lc-secret')
    fill('Console token id', 'proxploy@pve!console')
    fill('Console token secret', 'bad')
    fireEvent.click(screen.getByRole('button', { name: 'Add host' }))

    // The host exists and works: this is not a failed onboarding.
    expect(await screen.findByText(/pve-01 was added/i)).toBeInTheDocument()
    expect(screen.getByText(/Console: .*did not work/i)).toBeInTheDocument()
    expect(screen.queryByText(/Lifecycle:/)).not.toBeInTheDocument()
    expect(onCreated).not.toHaveBeenCalled()
  })

  it('retries only the rejected capability, without re-creating the host', async () => {
    reject = 'console'
    const onCreated = vi.fn()
    render(<HostForm onCreated={onCreated} />)
    fillHost()
    fill('Lifecycle token id', 'proxploy@pve!lifecycle')
    fill('Lifecycle token secret', 'lc-secret')
    fill('Console token id', 'proxploy@pve!console')
    fill('Console token secret', 'bad')
    fireEvent.click(screen.getByRole('button', { name: 'Add host' }))
    await screen.findByText(/Console: .*did not work/i)

    reject = null
    calls.length = 0
    fill('Console token secret', 'good')
    fireEvent.click(screen.getByRole('button', { name: /retry/i }))

    await waitFor(() => expect(onCreated).toHaveBeenCalledWith({ id: 7, name: 'pve-01' }))
    expect(calls.some(c => c.path === '/hosts')).toBe(false)
    expect(credentialCalls().map(c => c.body.capability)).toEqual(['console'])
  })

  it('lets the operator continue with the capability still missing', async () => {
    reject = 'backup'
    const onCreated = vi.fn()
    render(<HostForm onCreated={onCreated} />)
    fillHost()
    fill('Backup token id', 'proxploy@pve!backup')
    fill('Backup token secret', 'bad')
    fireEvent.click(screen.getByRole('button', { name: 'Add host' }))
    await screen.findByText(/Backup: .*did not work/i)

    fireEvent.click(screen.getByRole('button', { name: /continue without it/i }))
    expect(onCreated).toHaveBeenCalledWith({ id: 7, name: 'pve-01' })
  })

  it('behaves exactly as before when no capability token is filled in', async () => {
    const onCreated = vi.fn()
    render(<HostForm onCreated={onCreated} />)
    fillHost()
    fireEvent.click(screen.getByRole('button', { name: 'Add host' }))
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith({ id: 7, name: 'pve-01' }))
    expect(calls.map(c => c.path)).toEqual(['/hosts'])
  })
})
