import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { notifyError } = vi.hoisted(() => ({ notifyError: vi.fn() }))
vi.mock('../lib/notify', () => ({ notify: { error: notifyError, success: vi.fn(), info: vi.fn(), warning: vi.fn() } }))

type Call = { path: string; method?: string; body: unknown }
const calls: Call[] = []
let teamsRbac = true
let createStatus: 201 | 403 = 201
let teamsError = false
let membersError = false

const TEAMS = [
  { id: 1, name: 'Default', slug: 'default', description: null, member_count: 1, host_count: 2 },
  { id: 2, name: 'Ops', slug: 'ops', description: null, member_count: 1, host_count: 0 },
]
const MEMBERS: Record<number, { user_id: number; email: string; display_name: string | null; role: string }[]> = {
  1: [{ user_id: 1, email: 'admin@example.com', display_name: null, role: 'owner' }],
  2: [{ user_id: 2, email: 'v@x.io', display_name: null, role: 'viewer' },
      { user_id: 4, email: 'multi@x.io', display_name: null, role: 'admin' }],
}
const USERS = [
  { id: 1, email: 'admin@example.com', display_name: null, is_active: true,
    teams: [{ team_id: 1, role: 'owner' }] },
  // Ops-only membership -- removing this one is the "denied everything
  // afterwards" case (A1) the warning has to catch.
  { id: 2, email: 'v@x.io', display_name: null, is_active: true,
    teams: [{ team_id: 2, role: 'viewer' }] },
  { id: 3, email: 'new@x.io', display_name: null, is_active: true, teams: [] },
  // Belongs to both teams -- removing from Ops still leaves default-team
  // access, so no lockout warning should fire for this one.
  { id: 4, email: 'multi@x.io', display_name: null, is_active: true,
    teams: [{ team_id: 1, role: 'viewer' }, { team_id: 2, role: 'admin' }] },
]

const { ApiError } = vi.hoisted(() => ({
  ApiError: class extends Error {
    status: number; body: unknown
    constructor(status: number, body: unknown) { super(`API ${status}`); this.status = status; this.body = body }
  },
}))

vi.mock('../api/client', () => ({
  ApiError,
  api: vi.fn((path: string, opts?: RequestInit) => {
    const method = opts?.method
    if (path === '/entitlements') {
      return Promise.resolve({ tier: 'builtin', features: { 'teams.rbac': teamsRbac }, grace: null, clock_skew: false })
    }
    if (path === '/teams' && !method) {
      if (teamsError) return Promise.reject(new ApiError(502, { detail: 'boom' }))
      return Promise.resolve(TEAMS)
    }
    if (path === '/users' && !method) return Promise.resolve(USERS)
    const membersMatch = path.match(/^\/teams\/(\d+)\/members$/)
    if (membersMatch && !method) {
      if (membersError) return Promise.reject(new ApiError(502, { detail: 'boom' }))
      return Promise.resolve(MEMBERS[Number(membersMatch[1])] ?? [])
    }
    if (path === '/teams' && method === 'POST') {
      calls.push({ path, method, body: opts?.body ? JSON.parse(String(opts.body)) : null })
      if (createStatus === 403) return Promise.reject(new ApiError(403, { detail: 'forbidden' }))
      return Promise.resolve({ id: 3, name: 'New', slug: 'new', description: null,
                               member_count: 0, host_count: 0 })
    }
    const memberWrite = path.match(/^\/teams\/(\d+)\/members\/(\d+)$/)
    if (memberWrite && (method === 'PUT' || method === 'DELETE')) {
      calls.push({ path, method, body: opts?.body ? JSON.parse(String(opts.body)) : null })
      if (method === 'DELETE' && path === '/teams/1/members/1') {
        return Promise.reject(new ApiError(409, { detail: 'cannot remove the last owner' }))
      }
      return Promise.resolve({ ok: true })
    }
    calls.push({ path, method, body: opts?.body ? JSON.parse(String(opts.body)) : null })
    return Promise.resolve(null)
  }),
}))

import { TeamsCard } from '../components/TeamsCard'

const wrap = () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={qc}><TeamsCard /></QueryClientProvider>)
}

describe('TeamsCard', () => {
  beforeEach(() => {
    calls.length = 0; notifyError.mockClear(); teamsRbac = true; createStatus = 201
    teamsError = false; membersError = false
  })
  afterEach(() => vi.restoreAllMocks())

  it('says the teams could not be read rather than showing "no teams yet"', async () => {
    teamsError = true
    wrap()
    expect(await screen.findByText(/teams not readable/i)).toBeInTheDocument()
    expect(screen.queryByText('No teams yet.')).not.toBeInTheDocument()
  })

  it('says the members could not be read rather than showing "no members yet"', async () => {
    membersError = true
    wrap()
    fireEvent.click(await screen.findByText('Ops', { exact: false }))
    expect(await screen.findByText(/members not readable/i)).toBeInTheDocument()
    expect(screen.queryByText('No members yet.')).not.toBeInTheDocument()
  })

  it('gates the whole card behind teams.rbac: no fetch, plan message shown', async () => {
    teamsRbac = false
    wrap()
    expect(await screen.findByText('Not included in your plan.')).toBeInTheDocument()
    expect(calls.some((c) => c.path === '/teams')).toBe(false)
    expect(screen.queryByRole('button', { name: 'New team' })).toBeNull()
  })

  it('lists teams with member and host counts', async () => {
    wrap()
    const nameCell = await screen.findByText('Ops', { exact: false })
    expect(nameCell).toBeInTheDocument()
    const row = nameCell.closest('tr')!
    expect(row.textContent).toContain('1') // member_count
    expect(row.textContent).toContain('0') // host_count
  })

  // SKIPPED WITH THE BUTTON, NOT DELETED. The affordance this drives is
  // commented out in TeamsCard.tsx until the Teams plan ships; the mutation and the
  // endpoint behind it are untouched. Unskip when the button returns.
  it.skip('renders the create-team form for every role and posts on submit', async () => {
    wrap()
    fireEvent.click(await screen.findByRole('button', { name: 'New team' }))
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Ops2' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create team' }))
    await waitFor(() => expect(calls.some((c) =>
      c.path === '/teams' && c.method === 'POST'
      && JSON.stringify(c.body) === JSON.stringify({ name: 'Ops2' }))).toBe(true))
  })

  // SKIPPED WITH THE BUTTON, NOT DELETED. The affordance this drives is
  // commented out in TeamsCard.tsx until the Teams plan ships; the mutation and the
  // endpoint behind it are untouched. Unskip when the button returns.
  it.skip('surfaces a 403 from create-team as an error toast rather than hiding the form', async () => {
    createStatus = 403
    wrap()
    fireEvent.click(await screen.findByRole('button', { name: 'New team' }))
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'X' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create team' }))
    await waitFor(() => expect(notifyError).toHaveBeenCalledWith('forbidden'))
  })

  it('expands a team to list members with a role select wired to PUT', async () => {
    wrap()
    fireEvent.click(await screen.findByText('Ops', { exact: false }))
    // Wait for the role <select> specifically, not the plain "v@x.io" text --
    // that string also appears as a candidate option in the "Add member"
    // picker while the members fetch is still in flight (memberIds is an
    // empty Set until it resolves), so a plain findByText races the fetch.
    const roleSelect = await screen.findByLabelText('role for v@x.io') as HTMLSelectElement
    expect(roleSelect.value).toBe('viewer')
    fireEvent.change(roleSelect, { target: { value: 'admin' } })
    await waitFor(() => expect(calls.some((c) =>
      c.path === '/teams/2/members/2' && c.method === 'PUT'
      && JSON.stringify(c.body) === JSON.stringify({ role: 'admin' }))).toBe(true))
  })

  it('"Add member" is populated from GET /users and PUTs the picked user+role', async () => {
    wrap()
    fireEvent.click(await screen.findByText('Ops', { exact: false }))
    await screen.findByLabelText('role for v@x.io') // members loaded -> picker excludes existing members
    fireEvent.change(screen.getByLabelText('Add member'), { target: { value: '3' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add' }))
    await waitFor(() => expect(calls.some((c) =>
      c.path === '/teams/2/members/3' && c.method === 'PUT'
      && JSON.stringify(c.body) === JSON.stringify({ role: 'viewer' }))).toBe(true))
  })

  it('warns before removing a member\'s only remaining team membership', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    wrap()
    fireEvent.click(await screen.findByText('Ops', { exact: false }))
    const memberRow = (await screen.findByLabelText('role for v@x.io')).closest('tr')!
    fireEvent.click(within(memberRow).getByRole('button', { name: 'Remove' }))
    expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining('only team'))
    await new Promise((r) => setTimeout(r, 10))
    expect(calls.some((c) => c.method === 'DELETE')).toBe(false)
  })

  it('surfaces the 409 "last owner" refusal from the backend rather than swallowing it', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    wrap()
    fireEvent.click(await screen.findByText('Default', { exact: false }))
    const memberRow = (await screen.findByLabelText('role for admin@example.com')).closest('tr')!
    fireEvent.click(within(memberRow).getByRole('button', { name: 'Remove' }))
    await waitFor(() => expect(notifyError).toHaveBeenCalledWith('cannot remove the last owner'))
  })

  it('removing a member with other teams asks a plain confirmation, no lockout warning', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    wrap()
    fireEvent.click(await screen.findByText('Ops', { exact: false }))
    const memberRow = (await screen.findByLabelText('role for multi@x.io')).closest('tr')!
    fireEvent.click(within(memberRow).getByRole('button', { name: 'Remove' }))
    expect(window.confirm).toHaveBeenCalledWith('Remove multi@x.io from Ops?')
    await waitFor(() => expect(calls.some((c) =>
      c.path === '/teams/2/members/4' && c.method === 'DELETE')).toBe(true))
  })
})
