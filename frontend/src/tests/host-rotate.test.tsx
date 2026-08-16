import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

// Retargeted from the now-deleted HostRotateDialog, which HostEditDialog
// absorbed. Only the SSH-key-regeneration coverage survives here: the token
// id/secret rotation this file used to cover no longer exists as a standalone
// control, that capability already lives in HostCapabilityList's monitoring
// row (see host-edit-dialog.test.tsx's "no standalone monitoring token
// fields" regression test), and duplicating it here was the exact bug
// reported. rotate_ssh is the one thing HostCapabilityList has no handling
// for at all, so it is the part that moved.

const calls: { path: string; method?: string; body: unknown }[] = []
let rotateResult: 'ok' | 'rejected' = 'ok'

vi.mock('../api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/client')>()),
  api: vi.fn((path: string, opts?: RequestInit) => {
    calls.push({ path, method: opts?.method, body: opts?.body ? JSON.parse(String(opts.body)) : null })
    // GET /hosts is a LIST, and HostCapabilityList reads it to find this
    // host's cluster peers. Standalone here, so it offers no peer checkbox.
    if (path === '/hosts') return Promise.resolve([])
    if (path === '/hosts/5' && !opts?.method) {
      return Promise.resolve({ id: 5, name: 'pve1', capabilities: { monitoring: true } })
    }
    if (path.endsWith('/credentials')) {
      if (rotateResult === 'rejected') {
        return Promise.reject(new ApiError(502, { error: 'token_rejected', detail: 'nope' }))
      }
      return Promise.resolve({ id: 5, rotated: ['ssh_key'], public_key: 'ssh-ed25519 AAAA...',
                               consent_note: 'Install this key on the node to finish rotating.' })
    }
    return Promise.resolve({})
  }),
}))

import { ApiError } from '../api/client'
import { HostEditDialog } from '../components/HostEditDialog'

const host = { name: 'pve1', address: 'https://10.0.0.5:8006' }

const wrap = () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={qc}>
    <HostEditDialog hostId={5} host={host} onClose={() => {}} />
  </QueryClientProvider>)
}

describe('HostEditDialog, SSH key regeneration', () => {
  beforeEach(() => { calls.length = 0; rotateResult = 'ok' })
  afterEach(() => vi.restoreAllMocks())

  it('carries the checkbox and its explanatory text into the merged dialog', async () => {
    wrap()
    expect(await screen.findByText(
      'Regenerate SSH key (the new key still needs installing on the node)')).toBeInTheDocument()
  })

  it('does not call the API just from checking the box, only from Regenerate', async () => {
    wrap()
    fireEvent.click(await screen.findByLabelText(
      /regenerate ssh key \(the new key still needs installing on the node\)/i))
    await new Promise((r) => setTimeout(r, 10))
    expect(calls.some((c) => c.path === '/hosts/5/credentials')).toBe(false)
  })

  it('sends rotate_ssh: true and only that, no token id or secret', async () => {
    wrap()
    fireEvent.click(await screen.findByLabelText(
      /regenerate ssh key \(the new key still needs installing on the node\)/i))
    fireEvent.click(screen.getByRole('button', { name: 'Regenerate' }))
    await waitFor(() => expect(calls.some((c) =>
      c.path === '/hosts/5/credentials' && c.method === 'POST'
      && JSON.stringify(c.body) === JSON.stringify({ rotate_ssh: true }))).toBe(true))
  })

  it('shows the returned public key once rotated', async () => {
    wrap()
    fireEvent.click(await screen.findByLabelText(
      /regenerate ssh key \(the new key still needs installing on the node\)/i))
    fireEvent.click(screen.getByRole('button', { name: 'Regenerate' }))
    expect(await screen.findByText('ssh-ed25519 AAAA...')).toBeInTheDocument()
    expect(screen.getByText('Install this key on the node to finish rotating.')).toBeInTheDocument()
  })

  it('surfaces a 502 token_rejected without pretending the key rotated', async () => {
    rotateResult = 'rejected'
    wrap()
    fireEvent.click(await screen.findByLabelText(
      /regenerate ssh key \(the new key still needs installing on the node\)/i))
    fireEvent.click(screen.getByRole('button', { name: 'Regenerate' }))
    expect(await screen.findByText('Proxmox could not do this: nope')).toBeInTheDocument()
  })
})
