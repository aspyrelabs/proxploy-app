/**
 * The selects that fill their <option> list from a query all handled the error
 * state and none of them handled the pending one, so for the length of the
 * first fetch each sat enabled showing only its placeholder. Opening one showed
 * an empty list, which reads as "there are none" when the truth is "not read
 * yet".
 *
 * A sample, not one case per select: what can break is the mechanism, not the
 * thirty-odd call sites. Four are covered here, one per shape.
 *  - TeamsCard, where the state had to be drilled down as a new prop.
 *  - Backups' retention Datastore and Settings' per-host Team, the two that
 *    handled neither state and so had no branch to extend.
 *  - VmCreateWizard's ISO image, the enabled-gated shape, where "waiting on the
 *    field above" and "loading" are different sentences and must stay so.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

/** path (exact, else longest prefix) -> what that call returns. Set per test. */
let routes: Record<string, unknown> = {}

vi.mock('../api/client', () => ({
  ApiError: class extends Error {},
  apiErrorDetail: (_e: unknown, fallback: string) => fallback,
  api: vi.fn((path: string) => {
    if (path in routes) return Promise.resolve(routes[path])
    const prefix = Object.keys(routes).filter((k) => path.startsWith(k))
      .sort((a, b) => b.length - a.length)[0]
    // An empty list, not null: these pages hang a dozen unrelated cards off
    // routes this file has no opinion about, and every one of them maps over
    // what it gets back.
    return Promise.resolve(prefix != null ? routes[prefix] : [])
  }),
}))

vi.mock('../lib/notify', () => ({
  notify: { error: vi.fn(), success: vi.fn(), info: vi.fn(), warning: vi.fn() },
}))

vi.mock('@tanstack/react-router', async (orig) => ({
  ...(await orig() as object),
  Link: ({ children }: { children?: unknown }) => <a>{children as never}</a>,
  useNavigate: () => () => {},
  useSearch: () => ({}),
}))

import { TeamsCard } from '../components/TeamsCard'
import { VmCreateWizard } from '../components/VmCreateWizard'
import { BackupsPage } from '../routes/backups'
import { SettingsPage } from '../routes/settings'

/** A promise this test decides when to settle: the only way to hold a query in
 *  its pending state long enough to look at the control it feeds. */
function deferred<T>() {
  let resolve!: (v: T) => void
  const promise = new Promise<T>((r) => { resolve = r })
  return { promise, resolve }
}

const wrap = (ui: React.ReactNode) => {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

const optionTexts = (sel: HTMLElement) =>
  [...sel.querySelectorAll('option')].map((o) => o.textContent)

beforeEach(() => {
  routes = {
    '/entitlements': {
      tier: 'pro', grace: null, clock_skew: false,
      features: new Proxy({}, { get: () => true }),
    },
  }
})

describe('TeamsCard, "Add member"', () => {
  const TEAM = { id: 1, name: 'Default', slug: 'default', description: null,
                 member_count: 1, host_count: 0 }

  it('says it is still reading the users rather than offering none', async () => {
    const users = deferred<unknown>()
    routes['/teams'] = [TEAM]
    routes['/teams/1/members'] = []
    routes['/users'] = users.promise
    wrap(<TeamsCard />)

    fireEvent.click(await screen.findByRole('button', { name: /Default/ }))
    const sel = await screen.findByLabelText('Add member')

    expect(sel).toBeDisabled()
    expect(optionTexts(sel)).toEqual(['Loading users…'])
    // The sentence being replaced: an open picker with nothing under it.
    expect(optionTexts(sel)).not.toContain('Select user…')

    users.resolve([{ id: 3, email: 'new@x.io', display_name: null,
                     is_active: true, teams: [] }])

    await waitFor(() => expect(sel).toBeEnabled())
    expect(optionTexts(sel)).toEqual(['Select user…', 'new@x.io'])
  })
})

describe('Backups, retention Datastore', () => {
  it('does not open on an empty datastore list before /backups has answered', async () => {
    const backups = deferred<unknown>()
    routes['/backups'] = backups.promise
    routes['/schedules'] = []
    routes['/hosts'] = [{ id: 1, name: 'host-01' }]
    wrap(<BackupsPage />)

    const sel = await screen.findByLabelText('Datastore')
    expect(sel).toBeDisabled()
    expect(optionTexts(sel)).toEqual(['Loading datastores…'])

    backups.resolve({
      backups: [{ id: 11, host_id: 1, host_name: 'host-01', storage: 'pbs-ds',
                  volid: 'pbs-ds:backup/ct/150/x', guest_type: 'ct', guest_vmid: 150,
                  guest_name: 'Immich', taken_at: null, size_bytes: 1024,
                  verify_state: 'ok', notes: null }],
      stats: { total: 1, total_bytes: 1024, ok_count: 1, failed_count: 0,
               success_rate_30d: 100,
               datastores: [{ storage: 'pbs-ds', count: 1, size_bytes: 1024 }] },
      synced_at: null, stale: false,
    })

    await waitFor(() => expect(sel).toBeEnabled())
    expect(optionTexts(sel)).toEqual(['pbs-ds'])
  })
})

describe('Settings, the per-host Team select', () => {
  it('does not call an assigned host unassigned while /teams is in flight', async () => {
    const teams = deferred<unknown>()
    routes['/hosts'] = [{ id: 1, name: 'host-01', address: '10.0.0.1', status: 'connected',
                          pve_version: '8.2', node_shell_enabled: false, team_id: 2 }]
    routes['/teams'] = teams.promise
    routes['/schedules'] = []
    wrap(<SettingsPage />)

    const sel = await screen.findByLabelText('team for host-01')
    expect(sel).toBeDisabled()
    // Host 1 is on team 2. With only "Unassigned" on offer the browser selects
    // it, and the column states the opposite of the truth.
    expect(optionTexts(sel)).toEqual(['Loading teams…'])

    teams.resolve([{ id: 2, name: 'Ops', slug: 'ops', description: null,
                     member_count: 0, host_count: 1 }])

    await waitFor(() => expect(sel).toBeEnabled())
    expect(optionTexts(sel)).toEqual(['Unassigned', 'Ops'])
    expect((sel as HTMLSelectElement).value).toBe('2')
  })
})

describe('VmCreateWizard, the enabled-gated ISO image select', () => {
  it('keeps "waiting on the field above" and "loading" as different sentences', async () => {
    const isos = deferred<unknown>()
    routes['/hosts'] = [{ id: 1, name: 'host-01' }]
    routes['/cluster/nodes'] = [{ host_id: 1, node: 'pve1' }]
    routes['/storage'] = [{ host_id: 1, node: 'pve1', storage: 'local', content: ['iso'] }]
    routes['/storage/1/local/content'] = isos.promise
    wrap(<VmCreateWizard onClose={() => {}} />)

    // Waited for by its option rather than by the control being enabled, so
    // this setup reaches step 1 with or without the fix and the assertions
    // below are the only thing under test.
    await screen.findByRole('option', { name: 'host-01' })
    fireEvent.change(screen.getByLabelText(/^host$/i), { target: { value: '1' } })
    fireEvent.change(screen.getByLabelText(/^node$/i), { target: { value: 'pve1' } })
    fireEvent.change(screen.getByLabelText(/vm name/i), { target: { value: 'ubuntu-lab' } })
    fireEvent.click(screen.getByRole('button', { name: 'Next' }))

    // No ISO storage picked yet, so nothing has been asked for. This select is
    // empty because the question above it is unanswered, which is not the bug.
    const iso = screen.getByLabelText(/iso image/i)
    expect(iso).toBeEnabled()
    expect(optionTexts(iso)).toEqual(['Select an ISO…'])

    fireEvent.change(screen.getByLabelText(/iso storage/i), { target: { value: 'local' } })

    await waitFor(() => expect(iso).toBeDisabled())
    expect(optionTexts(iso)).toEqual(['Loading ISOs…'])

    isos.resolve([{ volid: 'local:iso/ubuntu-24.04.iso', size: 6000000000 }])

    await waitFor(() => expect(iso).toBeEnabled())
    expect(optionTexts(iso)).toEqual(['Select an ISO…', 'local:iso/ubuntu-24.04.iso'])
  })
})
