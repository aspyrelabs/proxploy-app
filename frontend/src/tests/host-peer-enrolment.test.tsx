/**
 * The peer offer HostForm makes once a host of a cluster has been added
 * (docs/notes/cluster-peer-auto-enrolment-plan.md, phase 5).
 *
 * Every fixture here is the shape the shipped routes actually return,
 * backend/proxploy/api/hosts.py::list_peers and ::enrol_peers, including the
 * `detail` wording, which the panel renders rather than paraphrases.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const calls: { path: string; method: string; body: any }[] = []

// GET /hosts/{id}/peers. Reassigned per test.
let peersResult: any = null
// Held open by the in-flight test so it can see the checking state.
let peersHeld = false
let releasePeers: ((v: unknown) => void) | null = null
// POST /hosts/{id}/peers.
let enrolResults: any[] = []

const CAPABILITIES_CATALOG = [
  { key: 'monitoring', label: 'Read-only monitoring', required: true,
    why: 'Pollers, dashboard, metrics, and every read view. Always required.' },
  { key: 'lifecycle', label: 'Lifecycle', required: false, why: 'Start/stop.' },
  { key: 'console', label: 'Console', required: false, why: 'Console tickets.' },
  { key: 'backup', label: 'Backup', required: false, why: 'Backup and restore.' },
]

const peer = (over: Record<string, unknown> = {}) => ({
  node: 'node2', address: 'https://10.0.0.6:8006', online: true, reachable: true,
  tls_fingerprint: 'AB:CD:EF', already_enrolled_as: null, error: null, ...over,
})

const STANDALONE = { cluster: null, team: null, capabilities_to_copy: ['monitoring'],
                     multi_host_entitled: true, peers: [] }

const TWO_PEERS = {
  cluster: 'lab-cluster',
  team: { id: 2, name: 'Platform' },
  capabilities_to_copy: ['monitoring', 'lifecycle'],
  multi_host_entitled: true,
  peers: [peer(), peer({ node: 'node3', address: 'https://10.0.0.7:8006',
                         tls_fingerprint: '12:34:56' })],
}

vi.mock('../api/client', () => ({
  ApiError: class extends Error {
    status: number; body: unknown
    constructor(status: number, body: unknown) { super(`API ${status}`); this.status = status; this.body = body }
  },
  api: vi.fn((path: string, init?: RequestInit) => {
    const method = init?.method ?? 'GET'
    calls.push({ path, method, body: init?.body ? JSON.parse(String(init.body)) : null })
    if (path === '/hosts/capabilities') return Promise.resolve(CAPABILITIES_CATALOG)
    if (path === '/hosts' && method === 'POST') {
      return Promise.resolve({ id: 7, name: 'pve-01', node_name: 'node1',
                               cluster_name: 'lab-cluster' })
    }
    if (path === '/hosts/7/peers' && method === 'POST') {
      return Promise.resolve({ results: enrolResults })
    }
    if (path === '/hosts/7/peers') {
      if (peersHeld) return new Promise((resolve) => { releasePeers = resolve })
      return Promise.resolve(peersResult)
    }
    return Promise.resolve({})
  }),
}))

import { HostForm } from '../components/HostForm'

const withQuery = (ui: React.ReactNode) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

const fill = (label: string, value: string) =>
  fireEvent.change(screen.getByLabelText(label), { target: { value } })

function addHost(onCreated = vi.fn()) {
  withQuery(<HostForm onCreated={onCreated} />)
  fill('Name', 'pve-01')
  fill('Address', 'https://10.0.0.5:8006')
  fill('Monitoring token id', 'proxploy@pve!monitoring')
  fill('Monitoring token secret', 'mon-secret')
  fireEvent.click(screen.getByRole('button', { name: 'Add host' }))
  return onCreated
}

const peerCalls = () => calls.filter(c => c.path === '/hosts/7/peers')
const box = (node: string) => screen.getByRole('checkbox', { name: new RegExp(node) })
const row = (node: string) => box(node).closest('label') as HTMLElement

beforeEach(() => {
  calls.length = 0
  peersResult = STANDALONE
  peersHeld = false
  releasePeers = null
  enrolResults = []
})

describe('peer enrolment panel', () => {
  it('shows one checking state while the peers request is in flight, and no checkboxes', async () => {
    peersHeld = true
    addHost()
    expect(await screen.findByText('Checking the other nodes of cluster lab-cluster'))
      .toBeInTheDocument()
    // Nothing can be ticked before its reachability is known.
    expect(screen.queryByRole('checkbox', { name: /node2/ })).not.toBeInTheDocument()

    releasePeers?.(TWO_PEERS)
    expect(await screen.findByRole('checkbox', { name: /node2/ })).toBeInTheDocument()
  })

  it('renders both peers pre ticked and does not advance yet', async () => {
    peersResult = TWO_PEERS
    const onCreated = addHost()
    expect(await screen.findByText(
      'node1 is part of cluster lab-cluster. Proxploy found 2 other nodes in it.'))
      .toBeInTheDocument()
    expect(box('node2')).toBeChecked()
    expect(box('node3')).toBeChecked()
    expect(row('node2').textContent).toContain('https://10.0.0.6:8006')
    expect(row('node2').textContent).toContain('AB:CD:EF')
    expect(onCreated).not.toHaveBeenCalled()
  })

  it('names the team the peers will join, above the checkboxes, before anything is ticked', async () => {
    peersResult = TWO_PEERS
    addHost()
    const team = await screen.findByText(
      'These nodes will join the same team as node1: Platform.')
    expect(team.compareDocumentPosition(box('node2'))
           & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('says plainly when the peers will be in no team either', async () => {
    peersResult = { ...TWO_PEERS, team: null }
    addHost()
    expect(await screen.findByText(/node1 is not in a team, so these nodes will not be in one either/))
      .toBeInTheDocument()
  })

  it('shows an unreachable peer unticked, disabled, with its reason and no fingerprint', async () => {
    peersResult = { ...TWO_PEERS, peers: [peer(), peer({
      node: 'node3', address: 'https://10.0.0.7:8006', reachable: false,
      tls_fingerprint: null,
      error: { kind: 'unreachable',
               detail: 'Proxploy could not reach node3 at 10.0.0.7 on port 8006: '
                     + 'timed out. It cannot be added until it answers there.' },
    })] }
    addHost()
    await screen.findByRole('checkbox', { name: /node3/ })
    expect(box('node3')).not.toBeChecked()
    expect(box('node3')).toBeDisabled()
    expect(row('node3').textContent).toContain('It cannot be added until it answers there.')
    expect(row('node3').textContent).not.toMatch(/fingerprint/i)
  })

  it('shows a peer already in Proxploy unticked, disabled, and names the host it is', async () => {
    peersResult = { ...TWO_PEERS, peers: [peer({ already_enrolled_as: 'pve-02' })] }
    addHost()
    await screen.findByRole('checkbox', { name: /node2/ })
    expect(box('node2')).not.toBeChecked()
    expect(box('node2')).toBeDisabled()
    expect(row('node2').textContent).toContain('pve-02')
  })

  it('posts only the ticked node names', async () => {
    peersResult = TWO_PEERS
    addHost()
    fireEvent.click(await screen.findByRole('checkbox', { name: /node3/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Add these nodes' }))
    await waitFor(() => expect(peerCalls().some(c => c.method === 'POST')).toBe(true))
    expect(peerCalls().find(c => c.method === 'POST')?.body.nodes).toEqual(['node2'])
  })

  it('echoes back the fingerprint it displayed for each ticked node', async () => {
    peersResult = TWO_PEERS
    addHost()
    await screen.findByRole('checkbox', { name: /node2/ })
    fireEvent.click(screen.getByRole('button', { name: 'Add these nodes' }))
    await waitFor(() => expect(peerCalls().some(c => c.method === 'POST')).toBe(true))
    // A node that swapped its certificate between the panel rendering and this
    // click is refused by the backend rather than pinned to something the
    // operator never saw.
    expect(peerCalls().find(c => c.method === 'POST')?.body.tls_fingerprints)
      .toEqual({ node2: 'AB:CD:EF', node3: '12:34:56' })
  })

  it('adds nothing when the operator skips, and advances', async () => {
    peersResult = TWO_PEERS
    const onCreated = addHost()
    fireEvent.click(await screen.findByRole('button', { name: 'Skip' }))
    expect(onCreated).toHaveBeenCalledWith(expect.objectContaining({ id: 7 }))
    expect(peerCalls().some(c => c.method === 'POST')).toBe(false)
  })

  it('reports one result per peer, and never draws a skip as a failure', async () => {
    peersResult = { ...TWO_PEERS, peers: [
      peer(), peer({ node: 'node3', address: 'https://10.0.0.7:8006' }),
      peer({ node: 'node4', address: 'https://10.0.0.8:8006' })] }
    enrolResults = [
      { node: 'node2', status: 'enrolled', host_id: 8, address: 'https://10.0.0.6:8006',
        capabilities_stored: ['monitoring', 'lifecycle'], capabilities_failed: [],
        detail: null },
      { node: 'node3', status: 'failed', host_id: null, address: 'https://10.0.0.7:8006',
        capabilities_stored: [], capabilities_failed: [],
        detail: 'node3 was not added: Proxploy already has a different host called '
              + 'node3, at https://10.9.9.9:8006. Nothing was stored. Rename that '
              + 'host, then add this node again. Any other nodes you ticked were '
              + 'still added.' },
      { node: 'node4', status: 'skipped', host_id: null, address: 'https://10.0.0.8:8006',
        capabilities_stored: [], capabilities_failed: [],
        detail: 'node4 is already in Proxploy as pve-04. Nothing was stored.' },
    ]
    const onCreated = addHost()
    await screen.findByRole('checkbox', { name: /node2/ })
    fireEvent.click(screen.getByRole('button', { name: 'Add these nodes' }))

    expect(await screen.findByText(
      /node2 was added, with these tokens stored: Read-only monitoring, Lifecycle\./))
      .toBeInTheDocument()
    const failed = screen.getByText(/Proxploy already has a different host called node3/)
    const skipped = screen.getByText(/node4 is already in Proxploy as pve-04/)
    expect(failed.className).toContain('red')
    expect(skipped.className).not.toContain('red')

    expect(onCreated).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }))
    expect(onCreated).toHaveBeenCalledWith(expect.objectContaining({ id: 7 }))
  })

  it('names the peers and the tier requirement, with no checkboxes, when multi host is off', async () => {
    peersResult = { ...TWO_PEERS, multi_host_entitled: false }
    addHost()
    expect(await screen.findByText(/Adding more than one host needs a paid tier/))
      .toBeInTheDocument()
    expect(screen.getByText(/node2/)).toBeInTheDocument()
    expect(screen.getByText(/node3/)).toBeInTheDocument()
    expect(screen.queryByRole('checkbox', { name: /node2/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Add these nodes' })).not.toBeInTheDocument()
  })

  it('renders no panel at all for a standalone host, and advances as it does today', async () => {
    peersResult = STANDALONE
    const onCreated = addHost()
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith(
      expect.objectContaining({ id: 7 })))
    expect(screen.queryByText(/other nodes/)).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Skip' })).not.toBeInTheDocument()
  })
})
