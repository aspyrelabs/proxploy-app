import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const calls: { path: string; method?: string; body: unknown }[] = []
let notifyChannels = true
let teamsRbac = false
let hostRows: unknown[] = []
const teamRows = [{ id: 1, name: 'Default', slug: 'default', description: null,
                    member_count: 1, host_count: 1 },
                   { id: 2, name: 'Ops', slug: 'ops', description: null,
                    member_count: 0, host_count: 0 }]

vi.mock('../api/client', () => ({
  ApiError: class extends Error {},
  api: vi.fn((path: string, opts?: RequestInit) => {
    if (path === '/entitlements') {
      return Promise.resolve({
        tier: 'builtin',
        features: { 'notify.channels': notifyChannels, 'teams.rbac': teamsRbac },
        grace: null,
      })
    }
    if (path === '/hosts') return Promise.resolve(hostRows)
    if (path === '/schedules') return Promise.resolve([])
    if (path === '/teams' && !opts?.method) return Promise.resolve(teamRows)
    if (path === '/users' && !opts?.method) return Promise.resolve([])
    if (path.startsWith('/hosts/') && opts?.method === 'PATCH') {
      calls.push({ path, method: opts.method, body: JSON.parse(String(opts.body)) })
      return Promise.resolve({ id: 1, node_shell_enabled: true })
    }
    if (path === '/notifications/channels' && !opts?.method) {
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

describe('SettingsPage — notification channels', () => {
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

describe('SettingsPage — node shell toggle', () => {
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

describe('SettingsPage — host team assignment', () => {
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

afterEach(() => vi.restoreAllMocks())
