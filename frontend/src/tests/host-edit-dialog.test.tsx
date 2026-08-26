import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { toastSuccess } = vi.hoisted(() => ({ toastSuccess: vi.fn() }))
vi.mock('../lib/notify', () => ({
  notify: { success: toastSuccess, error: vi.fn(), info: vi.fn(), warning: vi.fn() },
}))

let testResult: 'connected' | 'unreachable' = 'connected'
const calls: { path: string; method?: string; body: unknown }[] = []
// Finding #9: left undefined (as it always was before this fix), the mount
// GET HostCapabilityList fires renders an empty list in every test in this
// file, so Task 3's wiring only had accidental coverage. One test below sets
// this to exercise the real thing.
let hostCapabilities: Record<string, boolean> | undefined
// What POST /hosts/{id}/test reports about TLS: the pin stored at enrolment,
// and the fingerprint the node is presenting, which the backend only fetches
// when that pin refused the connection. Null by default, which is what a host
// that connected reports and what every other test in this file runs with.
const PINNED = 'AB:CD:EF:01:23:45:67:89:AB:CD:EF:01:23:45:67:89:AB:CD:EF:01:23:45:67:89:AB:CD:EF:01:23:45:67:9F'
const PRESENTED = '12:34:56:78:9A:BC:DE:F0:12:34:56:78:9A:BC:DE:F0:12:34:56:78:9A:BC:DE:F0:12:34:56:78:9A:BC:DE:EF'
let fingerprints: { tls_fingerprint: string | null; tls_fingerprint_seen: string | null }
let capabilityGaps: Record<string, string[] | null> | undefined
// GET /hosts/{id}/peers, which the peer panel in this dialog fires on mount.
// Standalone by default, so every test that is not about peers behaves exactly
// as it did before the panel was mounted here: no panel at all.
const STANDALONE = { cluster: null, team: null, capabilities_to_copy: ['monitoring'],
                     multi_host_entitled: true, peers: [] }
let peersResult: unknown = STANDALONE
// What POST /hosts/{id}/ssh/verify does. Verified by default, which is what
// every test that is not about the SSH pin ran with before this existed.
const SSH_PINNED = 'SHA256:g6u8niJFRLc24lBpY/wfoWpYOjVwej34E3RsaWg+u+A'
const SSH_PRESENTED = 'SHA256:A5ZL7u1eFiznvbB1exWOObi0YqPt7S6gLZbQ9GgmtIY'
let sshVerify: 'ok' | 'mismatch' | 'no_key' = 'ok'
// The Proxmox node name GET /hosts/{id} reports, which is what the cluster
// calls this host and what the panel names.
let nodeName: string | null = 'pve1'

vi.mock('../api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/client')>()),
  api: vi.fn((path: string, opts?: RequestInit) => {
    const body = opts?.body ? JSON.parse(String(opts.body)) : null
    calls.push({ path, method: opts?.method, body })
    // GET /hosts is a LIST, and HostCapabilityList reads it to find this
    // host's cluster peers. Standalone here, so it offers no peer checkbox.
    if (path === '/hosts') return Promise.resolve([])
    if (path.endsWith('/peers')) return Promise.resolve(peersResult)
    if (path === '/hosts/capabilities') {
      return Promise.resolve([
        { key: 'monitoring', label: 'Read-only monitoring', required: true },
        { key: 'lifecycle', label: 'Lifecycle', required: false },
      ])
    }
    if (path.endsWith('/ssh/verify')) {
      if (sshVerify === 'ok') return Promise.resolve({ verified: true })
      if (sshVerify === 'no_key') {
        return Promise.reject(new ApiError(502, { error: 'no_key',
          detail: 'this host has no enrolled SSH key' }))
      }
      return Promise.reject(new ApiError(502, {
        error: 'host_key_mismatch',
        detail: `host key changed: pinned ${SSH_PINNED}, saw ${SSH_PRESENTED}`,
        ssh_host_key_fingerprint: SSH_PINNED,
        ssh_host_key_fingerprint_seen: SSH_PRESENTED }))
    }
    if (path.endsWith('/test')) {
      return Promise.resolve({ id: 1, status: testResult, pve_version: '8.4.1',
                               capability_gaps: capabilityGaps, ...fingerprints })
    }
    if (path.endsWith('/credentials')) {
      return Promise.resolve({ id: 1, rotated: ['api_token'] })
    }
    if (path === '/hosts/1' && !opts?.method) {
      // HostCapabilityList's own mount GET.
      return Promise.resolve({ id: 1, name: 'pve1', node_name: nodeName,
                               capabilities: hostCapabilities })
    }
    // PATCH /hosts/{id}
    return Promise.resolve({ id: 1, node_shell_enabled: false })
  }),
}))

import { ApiError } from '../api/client'
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
  beforeEach(() => {
    testResult = 'connected'; calls.length = 0; toastSuccess.mockClear(); hostCapabilities = undefined
    sshVerify = 'ok'
    fingerprints = { tls_fingerprint: PINNED, tls_fingerprint_seen: null }
    capabilityGaps = undefined
    peersResult = STANDALONE; nodeName = 'pve1'
  })
  afterEach(() => vi.restoreAllMocks())

  it('starts pre-filled with the current name and address', () => {
    wrap()
    expect(screen.getByLabelText(/name/i)).toHaveValue('pve1')
    expect(screen.getByLabelText(/^address$/i)).toHaveValue('https://10.0.0.5:8006')
  })

  it('PATCHes only the changed name and address', async () => {
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

  it('surfaces a PATCH failure', async () => {
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

  // Regression: the dialog used to show a standalone "New monitoring token
  // id/secret" pair above the Capabilities list, duplicating monitoring's own
  // row there. Both checks run with the monitoring row actually present and
  // open, so a re-added standalone pair could not hide behind it: the
  // capability row's own fields are labelled "Monitoring token id/secret"
  // (no "New" prefix), which is a different string.
  // A pin is the only integrity a connection to a self-signed node has, and
  // nothing in the product could change one before this: a renewed
  // certificate left a host row nobody could fix from the UI.
  it('shows both fingerprints in full and offers to accept the new one', async () => {
    testResult = 'unreachable'
    fingerprints = { tls_fingerprint: PINNED, tls_fingerprint_seen: PRESENTED }
    wrap()
    fireEvent.click(screen.getByRole('button', { name: /test connection/i }))
    expect(await screen.findByText(new RegExp(`pve1.s TLS certificate has changed`, 'i'))).toBeInTheDocument()
    // In full, never truncated: the operator compares them against the node.
    expect(screen.getByText(PINNED)).toBeInTheDocument()
    expect(screen.getByText(PRESENTED)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /accept the new certificate/i }))
    await waitFor(() => expect(calls.some((c) => c.method === 'PATCH')).toBe(true))
    expect(calls.find((c) => c.method === 'PATCH')!.body).toEqual({ tls_fingerprint: PRESENTED })
  })

  it('offers nothing to accept while the presented certificate matches the pin', async () => {
    fingerprints = { tls_fingerprint: PINNED, tls_fingerprint_seen: PINNED }
    wrap()
    fireEvent.click(screen.getByRole('button', { name: /test connection/i }))
    expect(await screen.findByText(/connected, pve 8\.4\.1/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /accept the new certificate/i })).not.toBeInTheDocument()
    expect(screen.queryByText(/certificate has changed/i)).not.toBeInTheDocument()
  })

  // A host enrolled before the panel shipped gets the same offer here, so
  // nobody has to remove and re-add a host to get it.
  const peer = (over: Record<string, unknown> = {}) => ({
    node: 'node2', address: 'https://10.0.0.6:8006', online: true, reachable: true,
    tls_fingerprint: 'AB:CD:EF', already_enrolled_as: null, error: null, ...over,
  })

  it('offers the other nodes of the cluster to a host enrolled before the panel existed',
    async () => {
      nodeName = 'node1'
      peersResult = { cluster: 'lab-cluster', team: { id: 2, name: 'Platform' },
                      capabilities_to_copy: ['monitoring'], multi_host_entitled: true,
                      peers: [peer()] }
      wrap()
      // The Proxmox node name, which is what the cluster calls this host, not
      // the Proxploy host name.
      expect(await screen.findByText('node1 is part of cluster lab-cluster. '
        + 'Proxploy found 1 other node in it.')).toBeInTheDocument()
      expect(screen.getByText(/node2, https:\/\/10\.0\.0\.6:8006/)).toBeInTheDocument()
      expect(screen.getByRole('checkbox', { name: /node2/ })).toBeChecked()
    })

  it('offers nothing on a standalone host, exactly as the add-host flow does', async () => {
    wrap()
    await waitFor(() => expect(calls.some((c) => c.path === '/hosts/1/peers')).toBe(true))
    await waitFor(() => expect(screen.queryByText(/checking the other nodes/i)).toBeNull())
    expect(screen.queryByText(/is part of cluster/i)).toBeNull()
    expect(screen.queryByRole('button', { name: /add these nodes/i })).toBeNull()
  })

  // The common case for this dialog: it is where someone goes after enrolling
  // a cluster, so every peer is usually already in Proxploy. That is
  // information, not an empty panel and not a failure.
  it('names the peers that are already in Proxploy instead of showing an empty panel',
    async () => {
      nodeName = 'node1'
      peersResult = { cluster: 'lab-cluster', team: null, capabilities_to_copy: ['monitoring'],
                      multi_host_entitled: true,
                      peers: [peer({ already_enrolled_as: 'pve-02' }),
                              peer({ node: 'node3', address: 'https://10.0.0.7:8006',
                                     already_enrolled_as: 'pve-03' })] }
      wrap()
      expect(await screen.findByText('Already in Proxploy as pve-02.')).toBeInTheDocument()
      expect(screen.getByText('Already in Proxploy as pve-03.')).toBeInTheDocument()
      for (const name of [/node2/, /node3/]) {
        const box = screen.getByRole('checkbox', { name })
        expect(box).toBeDisabled()
        expect(box).not.toBeChecked()
      }
      expect(screen.getByRole('button', { name: /add these nodes/i })).toBeDisabled()
    })

  // The dialog is not a wizard: there is nothing to continue to, so the panel
  // offers nothing that pretends there is. Cancel and Save are how it closes.
  it('has no Skip or Continue in the dialog, which continues to nothing', async () => {
    nodeName = 'node1'
    peersResult = { cluster: 'lab-cluster', team: null, capabilities_to_copy: ['monitoring'],
                    multi_host_entitled: true, peers: [peer()] }
    wrap()
    expect(await screen.findByText(/is part of cluster lab-cluster/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^skip$/i })).toBeNull()
    expect(screen.queryByRole('button', { name: /^continue$/i })).toBeNull()
  })

  it('has no standalone monitoring token fields, only the Capabilities row', async () => {
    hostCapabilities = { monitoring: true, lifecycle: false, console: false, backup: false }
    wrap()
    fireEvent.click(await screen.findByRole('button', { name: /rotate monitoring token, show fields/i }))
    expect(await screen.findByLabelText(/^monitoring token id$/i)).toBeInTheDocument()
    expect(screen.queryByLabelText(/^new monitoring token id$/i)).not.toBeInTheDocument()
    expect(screen.queryByLabelText(/^new monitoring token secret$/i)).not.toBeInTheDocument()
  })
})


// --- the SSH host key pin, the one with no way back until now ---------------
//
// Rejoining a node to a Proxmox cluster rotates its SSH host key. Nothing in
// the product could change Host.ssh_host_key_fingerprint (it is only written
// when the stored pin is already null), so a routine rotation failed every
// install on that host with no fix but a manual database write. This is the
// same control the TLS pin has had, for the other pin.

describe('HostEditDialog SSH host key pin', () => {
  it('shows both fingerprints in full and offers to accept the new key', async () => {
    sshVerify = 'mismatch'
    wrap()
    fireEvent.click(screen.getByRole('button', { name: /test connection/i }))
    expect(await screen.findByText(/SSH host key has changed/i)).toBeInTheDocument()
    // In full, never truncated: the operator compares them against the node.
    expect(screen.getByText(SSH_PINNED)).toBeInTheDocument()
    expect(screen.getByText(SSH_PRESENTED)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /accept the new host key/i }))
    await waitFor(() => expect(calls.some(
      (c) => c.method === 'PATCH'
        && (c.body as { ssh_host_key_fingerprint?: string })?.ssh_host_key_fingerprint
           === SSH_PRESENTED)).toBe(true))
  })

  it('says installs are what breaks, since that is where it bites', async () => {
    sshVerify = 'mismatch'
    wrap()
    fireEvent.click(screen.getByRole('button', { name: /test connection/i }))
    expect(await screen.findByText(/App Store installs, updates and migration/i))
      .toBeInTheDocument()
  })

  it('offers nothing while the SSH key still verifies', async () => {
    sshVerify = 'ok'
    wrap()
    fireEvent.click(screen.getByRole('button', { name: /test connection/i }))
    await waitFor(() => expect(calls.some((c) => c.path === '/hosts/1/ssh/verify')).toBe(true))
    expect(screen.queryByText(/SSH host key has changed/i)).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /accept the new host key/i }))
      .not.toBeInTheDocument()
  })

  it('stays quiet for a host with no enrolled key, which is the normal case', async () => {
    sshVerify = 'no_key'
    wrap()
    fireEvent.click(screen.getByRole('button', { name: /test connection/i }))
    await waitFor(() => expect(calls.some((c) => c.path === '/hosts/1/ssh/verify')).toBe(true))
    expect(screen.queryByText(/SSH host key has changed/i)).not.toBeInTheDocument()
    // And it must not be reported as a connection error either.
    expect(screen.queryByText(/no enrolled SSH key/i)).not.toBeInTheDocument()
  })

  it('checks SSH even when the API check says the host is connected', async () => {
    // The whole failure mode: a rotated key answers the API perfectly and
    // fails every install, so checking only the API reports a healthy host
    // that cannot do the thing the key exists for.
    testResult = 'connected'
    sshVerify = 'mismatch'
    wrap()
    fireEvent.click(screen.getByRole('button', { name: /test connection/i }))
    expect(await screen.findByText(/Connected, PVE 8\.4\.1/i)).toBeInTheDocument()
    expect(await screen.findByText(/SSH host key has changed/i)).toBeInTheDocument()
  })
})

describe('HostEditDialog capability gaps', () => {
  beforeEach(() => {
    testResult = 'connected'; calls.length = 0; toastSuccess.mockClear()
    hostCapabilities = undefined; sshVerify = 'ok'
    fingerprints = { tls_fingerprint: PINNED, tls_fingerprint_seen: null }
    capabilityGaps = undefined
    peersResult = STANDALONE; nodeName = 'pve1'
  })
  afterEach(() => vi.restoreAllMocks())

  it('names the privileges a token is missing, per capability', async () => {
    // The drift case: SDN.Use and VM.Config.HWType were added to the Lifecycle
    // role on 2026-08-18, so every token generated before that is short of them
    // and the only other symptom is a 403 partway through a job.
    capabilityGaps = { lifecycle: ['SDN.Use', 'VM.Config.HWType'] }
    wrap()
    fireEvent.click(screen.getByRole('button', { name: /test connection/i }))
    await waitFor(() =>
      expect(screen.getByText(/missing privileges Proxploy needs/i)).toBeInTheDocument())
    expect(screen.getByText(/SDN\.Use, VM\.Config\.HWType/)).toBeInTheDocument()
    expect(screen.getByText(/lifecycle/i)).toBeInTheDocument()
  })

  it('says "could not check" for a token that cannot read its own permissions', async () => {
    capabilityGaps = { lifecycle: null }
    wrap()
    fireEvent.click(screen.getByRole('button', { name: /test connection/i }))
    await waitFor(() =>
      expect(screen.getByText(/could not check/i)).toBeInTheDocument())
  })

  it('says nothing when every token is fully granted', async () => {
    capabilityGaps = {}
    wrap()
    fireEvent.click(screen.getByRole('button', { name: /test connection/i }))
    await waitFor(() =>
      expect(calls.some((c) => c.path === '/hosts/1/test')).toBe(true))
    expect(screen.queryByText(/missing privileges/i)).toBeNull()
  })
})
