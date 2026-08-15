import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const calls: { path: string; method?: string; body: unknown }[] = []
let notifyChannels = true
let teamsRbac = false
let hostRows: unknown[] = []
let hostsError = false
let channelsError = false
let clockSkew = false
let entitlementsError = false
const teamRows = [{ id: 1, name: 'Default', slug: 'default', description: null,
                    member_count: 1, host_count: 1 },
                   { id: 2, name: 'Ops', slug: 'ops', description: null,
                    member_count: 0, host_count: 0 }]

vi.mock('../api/client', () => ({
  ApiError: class extends Error {},
  api: vi.fn((path: string, opts?: RequestInit) => {
    if (path === '/entitlements') {
      if (entitlementsError) return Promise.reject(new Error('boom'))
      return Promise.resolve({
        tier: 'builtin',
        features: { 'notify.channels': notifyChannels, 'teams.rbac': teamsRbac },
        grace: null, clock_skew: clockSkew,
      })
    }
    if (path === '/hosts') {
      if (hostsError) return Promise.reject(new Error('boom'))
      return Promise.resolve(hostRows)
    }
    if (path === '/schedules') return Promise.resolve([])
    if (path === '/auth/sessions') return Promise.resolve([])
    if (path === '/teams' && !opts?.method) return Promise.resolve(teamRows)
    if (path === '/users' && !opts?.method) return Promise.resolve([])
    if (path.startsWith('/hosts/') && opts?.method === 'PATCH') {
      calls.push({ path, method: opts.method, body: JSON.parse(String(opts.body)) })
      return Promise.resolve({ id: 1, node_shell_enabled: true })
    }
    if (path === '/notifications/channels' && !opts?.method) {
      if (channelsError) return Promise.reject(new Error('boom'))
      return Promise.resolve([
        { id: 1, name: 'Home ntfy', kind: 'ntfy', events: ['job.failed'],
          enabled: true, last_notified_at: null },
      ])
    }
    calls.push({ path, method: opts?.method, body: opts?.body ? JSON.parse(String(opts.body)) : null })
    if (path.endsWith('/test')) return Promise.resolve({ sent: true })
    if (opts?.method === 'DELETE') return Promise.resolve(null)
    return Promise.resolve({ id: 1, name: 'Home ntfy', kind: 'ntfy', events: ['job.failed'],
                             enabled: false, last_notified_at: null })
  }),
}))

vi.mock('@tanstack/react-router', async (orig) => ({
  ...(await orig() as object),
  Link: ({ children }: { children?: unknown }) => <a>{children as never}</a>,
  useNavigate: () => () => {},
  useSearch: () => ({}),
}))

import { SettingsPage } from '../routes/settings'

const wrap = () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={qc}><SettingsPage /></QueryClientProvider>)
}

describe('SettingsPage, notification channels', () => {
  beforeEach(() => { calls.length = 0; notifyChannels = true; hostRows = [] })

  it('asks for confirmation before deleting a channel, and skips the call on cancel', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    wrap()
    fireEvent.click(await screen.findByRole('button', { name: 'Remove' }))
    expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining('Home ntfy'))
    await new Promise((r) => setTimeout(r, 10))
    expect(calls.some((c) => c.method === 'DELETE')).toBe(false)
  })

  it('deletes the channel once the confirmation is accepted', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    wrap()
    fireEvent.click(await screen.findByRole('button', { name: 'Remove' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'DELETE')).toBe(true))
  })

  it('toggles enabled/disabled via PATCH', async () => {
    wrap()
    fireEvent.click(await screen.findByRole('button', { name: 'Disable' }))
    await waitFor(() => expect(calls.some((c) =>
      c.method === 'PATCH' && c.path === '/notifications/channels/1'
      && JSON.stringify(c.body) === JSON.stringify({ enabled: false }))).toBe(true))
  })

  it('gates the Notifications card behind notify.channels: no fetch, no Add channel, when the plan lacks it', async () => {
    notifyChannels = false
    wrap()
    // TeamsCard also renders "Not included in your plan." (teams.rbac is off
    // in this test's entitlements mock too) -- scope to the Notifications
    // section specifically so the two identical messages don't collide.
    const section = (await screen.findByRole('heading', { name: 'Notifications' })).closest('section')!
    expect(await within(section).findByText('Not included in your plan.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Add channel' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Remove' })).toBeNull()
    expect(calls.some((c) => c.path === '/notifications/channels')).toBe(false)
  })
})

describe('SettingsPage, node shell toggle', () => {
  beforeEach(() => {
    calls.length = 0
    notifyChannels = true
    hostRows = [{ id: 5, name: 'pve1', address: 'https://10.0.0.9:8006', status: 'connected',
                 pve_version: '8.4.1', node_shell_enabled: false }]
  })

  it('renders the current node_shell_enabled state and PATCHes on toggle', async () => {
    // Regression test for finding #11: PATCH /hosts/{id} existed on the
    // backend with no frontend control anywhere that called it.
    wrap()
    const checkbox = await screen.findByRole('checkbox')
    expect(checkbox).not.toBeChecked()
    fireEvent.click(checkbox)
    await waitFor(() => expect(calls.some((c) =>
      c.method === 'PATCH' && c.path === '/hosts/5'
      && JSON.stringify(c.body) === JSON.stringify({ node_shell_enabled: true }))).toBe(true))
  })
})

describe('SettingsPage, host team assignment', () => {
  beforeEach(() => {
    calls.length = 0
    notifyChannels = true
    teamsRbac = true
    hostRows = [{ id: 5, name: 'pve1', address: 'https://10.0.0.9:8006', status: 'connected',
                 pve_version: '8.4.1', node_shell_enabled: false }]
  })

  it('no team select, no /teams fetch, when teams.rbac is off', async () => {
    teamsRbac = false
    wrap()
    await screen.findByText('pve1')
    expect(screen.queryByLabelText('team for pve1')).toBeNull()
    expect(calls.some((c) => c.path === '/teams')).toBe(false)
  })

  it('PATCHes {node_shell_enabled, team_id} when a team is picked for a host', async () => {
    wrap()
    const select = await screen.findByLabelText('team for pve1') as HTMLSelectElement
    // Options populate once GET /teams resolves -- wait for the real "Ops"
    // option before firing change, or jsdom drops the assigned value (no
    // matching <option> yet) and the change event fires with value "".
    await waitFor(() => expect(select.querySelector('option[value="2"]')).not.toBeNull())
    fireEvent.change(select, { target: { value: '2' } })
    await waitFor(() => expect(calls.some((c) =>
      c.method === 'PATCH' && c.path === '/hosts/5'
      && JSON.stringify(c.body) === JSON.stringify({ node_shell_enabled: false, team_id: 2 })))
      .toBe(true))
  })
})

describe('SettingsPage, hosts and channels error vs empty', () => {
  beforeEach(() => {
    calls.length = 0
    notifyChannels = true
    teamsRbac = false
    hostsError = false
    channelsError = false
    hostRows = []
  })

  it('says the hosts could not be read rather than showing "no hosts yet"', async () => {
    hostsError = true
    wrap()
    expect(await screen.findByText(/hosts not readable/i)).toBeInTheDocument()
    expect(screen.queryByText('No hosts yet.')).not.toBeInTheDocument()
  })

  it('shows the real empty-hosts copy when there genuinely are none', async () => {
    wrap()
    expect(await screen.findByText('No hosts yet.')).toBeInTheDocument()
    expect(screen.queryByText(/hosts not readable/i)).not.toBeInTheDocument()
  })

  it('says the channels could not be read rather than showing "no channels yet"', async () => {
    channelsError = true
    wrap()
    expect(await screen.findByText(/channels not readable/i)).toBeInTheDocument()
    expect(screen.queryByText('No channels yet')).not.toBeInTheDocument()
  })
})

describe('SettingsPage, clock skew', () => {
  beforeEach(() => {
    calls.length = 0
    notifyChannels = true
    teamsRbac = false
    hostRows = []
  })

  it('renders the clock message, not the grace/license-refresh message, when clock_skew is true', async () => {
    clockSkew = true
    wrap()
    expect(await screen.findByText(/clock looks wrong/i)).toBeInTheDocument()
    expect(screen.queryByText(/license refresh failing/i)).toBeNull()
  })

  it('renders no clock message when clock_skew is false', async () => {
    clockSkew = false
    wrap()
    await screen.findByText('Plan')
    expect(screen.queryByText(/clock looks wrong/i)).toBeNull()
  })
})

afterEach(() => vi.restoreAllMocks())

describe('SettingsPage, the plan card', () => {
  beforeEach(() => {
    calls.length = 0; hostRows = []; entitlementsError = false; teamsRbac = true
  })
  afterEach(() => { entitlementsError = false })

  it('does not call the install FREE before the plan has been fetched', () => {
    // api/hooks.ts defaults tier to 'builtin' so gating fails closed, which is
    // right for security and wrong to print. A paid install read "FREE" for
    // the length of the fetch and then corrected itself.
    wrap()
    expect(screen.queryByText('FREE')).not.toBeInTheDocument()
    expect(screen.getByLabelText('Checking your plan')).toBeInTheDocument()
  })

  it('says it could not check, rather than FREE, when the plan fetch fails', async () => {
    entitlementsError = true
    wrap()
    // TotpCard says the same sentence for the same reason, so more than one
    // match is expected here; the property under test is that the tier is NOT
    // stated as fact.
    expect((await screen.findAllByText('Could not check your plan, try reloading.')).length)
      .toBeGreaterThan(0)
    expect(screen.queryByText('FREE')).not.toBeInTheDocument()
  })

  it('shows the tier once it lands', async () => {
    wrap()
    expect(await screen.findByText('FREE')).toBeInTheDocument()
    expect(screen.queryByLabelText('Checking your plan')).not.toBeInTheDocument()
  })
})

describe('SettingsPage, unassigning a host from its team', () => {
  beforeEach(() => {
    calls.length = 0; teamsRbac = true; entitlementsError = false
    hostRows = [{ id: 1, name: 'pve1', address: 'https://pve:8006', status: 'connected',
                  node_shell_enabled: false, team_id: 2, capabilities: {} }]
  })

  it('sends team_id null, instead of skipping the request entirely', async () => {
    // The option's value is '' and the handler skipped falsy values, so
    // "Unassigned" fired nothing and the select snapped back to the old team.
    wrap()
    const select = await screen.findByLabelText('team for pve1')
    fireEvent.change(select, { target: { value: '' } })
    await waitFor(() => {
      const patch = calls.find((c) => c.method === 'PATCH')
      expect(patch).toBeTruthy()
      expect((patch!.body as { team_id: number | null }).team_id).toBeNull()
    })
  })
})
