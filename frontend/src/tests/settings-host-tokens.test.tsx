import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const single = [{ id: 3, name: 'pve-01', address: 'https://10.0.0.5:8006', status: 'connected',
                 pve_version: '8.4.1', node_shell_enabled: false, team_id: null,
                 node_name: 'node1', cluster_name: null as string | null }]

// A cluster of three, the shape section 5 of the plan writes its copy for.
const clustered = [
  { ...single[0], cluster_name: 'lab-cluster' },
  { ...single[0], id: 4, name: 'pve-02', address: 'https://10.0.0.6:8006',
    node_name: 'node2', cluster_name: 'lab-cluster' },
  { ...single[0], id: 5, name: 'pve-03', address: 'https://10.0.0.7:8006',
    node_name: 'node3', cluster_name: 'lab-cluster' },
]

let hostRows = single
// Host ids whose POST /credentials is refused, so a test can refuse the
// origin, a peer, or neither.
let refuse: number[] = []
const posts: { path: string; body: Record<string, string> }[] = []

vi.mock('../api/client', async (orig) => ({
  ...(await orig() as object),
  api: vi.fn((path: string, opts?: RequestInit) => {
    const body = opts?.body ? JSON.parse(String(opts.body)) : null
    if (opts?.method === 'POST') posts.push({ path, body })
    if (path === '/hosts') return Promise.resolve(hostRows)
    const cred = /^\/hosts\/(\d+)\/credentials$/.exec(path)
    if (cred) {
      return refuse.includes(Number(cred[1]))
        ? Promise.reject(new ApiError(502, { detail: { error: 'token_rejected',
            detail: 'the new token did not work against that node: auth failed' } }))
        : Promise.resolve({ id: Number(cred[1]), rotated: [`api_token:${body.capability}`] })
    }
    const detail = /^\/hosts\/(\d+)$/.exec(path)
    if (detail) {
      return Promise.resolve({ id: Number(detail[1]), name: 'pve-01', capabilities: {
        monitoring: true, lifecycle: false, console: false, backup: false } })
    }
    if (path === '/entitlements') {
      return Promise.resolve({ tier: 'builtin', features: {}, grace: null, clock_skew: false })
    }
    if (path === '/schedules') return Promise.resolve([])
    if (path === '/auth/sessions') return Promise.resolve([])
    if (path === '/users') return Promise.resolve([])
    return Promise.resolve({})
  }),
}))

vi.mock('@tanstack/react-router', async (orig) => ({
  ...(await orig() as object),
  Link: ({ children }: { children?: unknown }) => <a>{children as never}</a>,
  useNavigate: () => () => {},
  useSearch: () => ({}),
}))

// Finding #4: this used to render HostTokensDialog directly, which meant it
// covered nothing about Settings actually reaching it -- deleting the
// Tokens button, the tokensHost state, or the dialog render from
// routes/settings.tsx would have left this green. Go through SettingsPage,
// same setup as settings.test.tsx, and click the real button.
//
// The Tokens dialog was merged into HostEditDialog and its button renamed to
// Edit (routes/settings.tsx), so this now covers that Edit opens the merged
// dialog showing name, address and the capability rows in one place.
import { ApiError } from '../api/client'
import { SettingsPage } from '../routes/settings'

const wrap = () => {
  const qc = new QueryClient({ defaultOptions: {
    queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={qc}><SettingsPage /></QueryClientProvider>)
}

/** Edit lives behind the row's actions menu now (routes/settings.tsx::
 *  HostRowMenu), since four named buttons no longer fit beside the section
 *  rail. Radix opens on pointerdown, not click (AccountMenu precedent). */
const openEdit = async () => {
  const row = await screen.findByRole('row', { name: /pve-01/ })
  fireEvent.pointerDown(within(row).getByRole('button', { name: 'Actions for pve-01' }),
                        { button: 0, ctrlKey: false })
  fireEvent.click(await screen.findByRole('menuitem', { name: 'Edit' }))
}

/** Open pve-01's Edit dialog and reveal one capability's token fields. */
const openTokenForm = async (label: string) => {
  wrap()
  await openEdit()
  const dialog = screen.getByRole('dialog')
  await within(dialog).findByText(label)
  fireEvent.click(within(dialog).getByRole('button',
    { name: `Add ${label} token, show fields` }))
  fireEvent.change(within(dialog).getByLabelText(`${label} token id`),
                   { target: { value: 'proxploy@pve!lifecycle' } })
  fireEvent.change(within(dialog).getByLabelText(`${label} token secret`),
                   { target: { value: 'lc' } })
  return dialog
}

describe('Settings host tokens', () => {
  beforeEach(() => { hostRows = single; refuse = []; posts.length = 0 })

  it('opens the merged Edit dialog for a host, with name, address and the capability list', async () => {
    wrap()
    await openEdit()
    expect(await screen.findByLabelText(/name/i)).toHaveValue('pve-01')
    expect(screen.getByLabelText(/^address$/i)).toHaveValue('https://10.0.0.5:8006')
    expect(await screen.findByText('Lifecycle')).toBeInTheDocument()
    // The dialog opens with its fields closed on every row now, so what proves
    // the list rendered is the control that would reveal them, not the field.
    // Four capabilities left open would have unrolled eight inputs on open.
    expect(screen.queryByLabelText('Lifecycle token id')).not.toBeInTheDocument()
    expect(screen.getByRole('button',
      { name: 'Add Lifecycle token, show fields' })).toBeInTheDocument()
  })

  // A token stored on one node of a cluster reaches the others, offered as one
  // pre ticked checkbox before Save rather than a prompt afterwards.
  describe('storing the same token on the other nodes of the cluster', () => {
    it('offers the peers, pre ticked and named, above Save', async () => {
      hostRows = clustered
      const dialog = await openTokenForm('Lifecycle')
      const box = await within(dialog).findByRole('checkbox',
        { name: /Also store this on the other nodes of cluster lab-cluster: node2, node3\./ })
      expect(box).toBeChecked()
      expect(box).toHaveAccessibleName(/A Proxmox API token works across the whole cluster/)
    })

    it('has no checkbox at all on a host with no cluster', async () => {
      await openTokenForm('Lifecycle')
      expect(screen.queryByRole('checkbox', { name: /Also store this/ })).not.toBeInTheDocument()
    })

    it('has no checkbox when the cluster has no other host enrolled', async () => {
      hostRows = [{ ...single[0], cluster_name: 'lab-cluster' }]
      await openTokenForm('Lifecycle')
      expect(screen.queryByRole('checkbox', { name: /Also store this/ })).not.toBeInTheDocument()
    })

    it('posts to the origin first and then to each ticked peer, capability named', async () => {
      hostRows = clustered
      const dialog = await openTokenForm('Lifecycle')
      await within(dialog).findByRole('checkbox', { name: /Also store this/ })
      fireEvent.click(within(dialog).getByRole('button', { name: 'Save Lifecycle token' }))

      await waitFor(() => expect(posts).toHaveLength(3))
      expect(posts.map(p => p.path)).toEqual([
        '/hosts/3/credentials', '/hosts/4/credentials', '/hosts/5/credentials'])
      for (const p of posts) {
        expect(p.body).toEqual({ token_id: 'proxploy@pve!lifecycle', token_secret: 'lc',
                                 capability: 'lifecycle' })
      }
      expect(await within(dialog).findByText(
        'Lifecycle token stored on node1, node2 and node3.')).toBeInTheDocument()
    })

    it('sends nothing to any peer when the origin refuses the token', async () => {
      hostRows = clustered
      refuse = [3]
      const dialog = await openTokenForm('Lifecycle')
      await within(dialog).findByRole('checkbox', { name: /Also store this/ })
      fireEvent.click(within(dialog).getByRole('button', { name: 'Save Lifecycle token' }))

      expect(await within(dialog).findByText(/Lifecycle: .*did not work/)).toBeInTheDocument()
      expect(posts.map(p => p.path)).toEqual(['/hosts/3/credentials'])
    })

    it('keeps the origin token when a peer refuses it, and says so', async () => {
      hostRows = clustered.slice(0, 2)
      refuse = [4]
      const dialog = await openTokenForm('Lifecycle')
      await within(dialog).findByRole('checkbox',
        { name: /the other nodes of cluster lab-cluster: node2\./ })
      fireEvent.click(within(dialog).getByRole('button', { name: 'Save Lifecycle token' }))

      expect(await within(dialog).findByText(
        'Lifecycle token stored on node1. node2 refused the same token, so Lifecycle '
        + 'is still not configured there. node1 keeps the token you just saved. Check '
        + 'that the token exists on node2 and that its permissions cover it, then add '
        + "it from node2's Edit dialog.")).toBeInTheDocument()
      // The origin's write stands: its row reports the token as stored.
      expect(within(dialog).getByRole('button',
        { name: 'Lifecycle token already stored' })).toBeInTheDocument()
    })

    it('names every node that refused, without pointing at one of them', async () => {
      hostRows = clustered
      refuse = [4, 5]
      const dialog = await openTokenForm('Lifecycle')
      await within(dialog).findByRole('checkbox', { name: /Also store this/ })
      fireEvent.click(within(dialog).getByRole('button', { name: 'Save Lifecycle token' }))

      expect(await within(dialog).findByText(
        'Lifecycle token stored on node1. node2 and node3 refused the same token, so '
        + 'Lifecycle is still not configured there. node1 keeps the token you just '
        + 'saved. Check that the token exists on node2 and node3 and that its '
        + "permissions cover it, then add it from each of those nodes' Edit dialog."))
        .toBeInTheDocument()
    })
  })
})
