// These cases share module-level OPTIONS and RULES and mutate them in place,
// so they depend on running in declaration order, which vitest guarantees.
// Reordering them will fail in ways that look like component bugs. If this
// ever needs to change, give each case its own fixture rather than adding
// beforeEach resets on top of the sharing.

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

let OPTIONS: any = {
  scope: 'cluster', digest: 'd1',
  options: { digest: 'd1' },
  defaults: { enable: 0, ebtables: 1, policy_in: 'DROP', policy_out: 'ACCEPT',
              policy_forward: 'ACCEPT' },
}
let RULES: any = { scope: 'cluster', digest: 'd1', rules: [] }

const calls: { path: string; method: string; body: any }[] = []

vi.mock('../api/client', () => {
  class ApiError extends Error {
    status: number; body: unknown
    constructor(status: number, body: unknown) {
      super(`API ${status}`); this.status = status; this.body = body
    }
  }
  return {
    ApiError,
    api: vi.fn((path: string, opts?: RequestInit) => {
      const method = (opts?.method ?? 'GET').toUpperCase()
      if (method !== 'GET') {
        calls.push({ path, method, body: opts?.body ? JSON.parse(String(opts.body)) : {} })
        return Promise.resolve({ ok: true })
      }
      if (path.endsWith('/options')) return Promise.resolve(OPTIONS)
      if (path.endsWith('/rules')) return Promise.resolve(RULES)
      return Promise.resolve({})
    }),
  }
})

import { FirewallOptionsPanel } from '../components/FirewallOptionsPanel'

function renderPanel(canEdit = true) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <FirewallOptionsPanel scope={{ kind: 'cluster', hostId: 1 }} canEdit={canEdit} />
    </QueryClientProvider>,
  )
}

describe('FirewallOptionsPanel', () => {
  it('shows an unset option as the default Proxmox will actually apply', async () => {
    // The options object is empty apart from a digest. Reading that as "no
    // policy" is wrong: PVE drops inbound traffic by default.
    renderPanel()
    await screen.findByLabelText('Incoming policy')
    const policy = screen.getByLabelText('Incoming policy') as HTMLSelectElement
    expect(policy.value).toBe('DROP')
  })

  it('warns that nothing will get through when there are no allow rules', async () => {
    RULES = { scope: 'cluster', digest: 'd1', rules: [] }
    renderPanel()
    await screen.findByLabelText('Firewall enabled')
    fireEvent.click(screen.getByLabelText('Firewall enabled'))
    await screen.findByText(/no rule here allows any through/i)
  })

  it('counts the allow rules that will still let traffic through', async () => {
    RULES = { scope: 'cluster', digest: 'd1', rules: [
      { pos: 0, type: 'in', action: 'ACCEPT', enable: 1 },
      { pos: 1, type: 'in', action: 'ACCEPT', enable: 0 },   // off, does not count
      { pos: 2, type: 'out', action: 'ACCEPT', enable: 1 },  // outgoing, does not count
    ] }
    renderPanel()
    await screen.findByLabelText('Firewall enabled')
    fireEvent.click(screen.getByLabelText('Firewall enabled'))
    await screen.findByText(/1 rule here will still let traffic through/i)
  })

  it('stays quiet on a firewall that is off and nobody has touched', async () => {
    // Proxmox defaults policy_in to DROP, so an untouched scope resolves to deny.
    // Warning on every visit is how a warning stops being read.
    renderPanel()
    await screen.findByLabelText('Firewall enabled')
    expect(screen.queryByText(/dropped by default/i)).toBeNull()
  })

  it('speaks in the present tense about a firewall that is already on', async () => {
    OPTIONS = { ...OPTIONS, options: { enable: 1, digest: 'd1' } }
    RULES = { scope: 'cluster', digest: 'd1', rules: [] }
    renderPanel()
    await screen.findByText(/is being dropped by default/i)
    OPTIONS = { ...OPTIONS, options: { digest: 'd1' } }   // restore for later cases
  })

  it('does not warn when the default policy already accepts', async () => {
    OPTIONS = { ...OPTIONS, options: { policy_in: 'ACCEPT', digest: 'd1' } }
    renderPanel()
    await screen.findByLabelText('Incoming policy')
    expect(screen.queryByText(/will be dropped/i)).toBeNull()
    OPTIONS = { ...OPTIONS, options: { digest: 'd1' } }   // restore for later tests
  })

  it('lets the operator enable anyway, it warns and never blocks', async () => {
    calls.length = 0
    renderPanel()
    await screen.findByLabelText('Firewall enabled')
    fireEvent.click(screen.getByLabelText('Firewall enabled'))
    fireEvent.click(screen.getByRole('button', { name: /save/i }))
    await waitFor(() => expect(calls).toHaveLength(1))
    expect(calls[0].method).toBe('PUT')
    expect(calls[0].body.enable).toBe(1)
  })

  it('sends only the options that were touched, plus the digest', async () => {
    calls.length = 0
    renderPanel()
    await screen.findByLabelText('Firewall enabled')
    fireEvent.click(screen.getByLabelText('Firewall enabled'))
    fireEvent.click(screen.getByRole('button', { name: /save/i }))
    await waitFor(() => expect(calls).toHaveLength(1))
    expect(calls[0].body).toEqual({ enable: 1, digest: 'd1' })
  })

  it('is read only for a viewer', async () => {
    renderPanel(false)
    await screen.findByLabelText('Incoming policy')
    expect((screen.getByLabelText('Incoming policy') as HTMLSelectElement).disabled)
      .toBe(true)
    expect(screen.queryByRole('button', { name: /save/i })).toBeNull()
  })
})
