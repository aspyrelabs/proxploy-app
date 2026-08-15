import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
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
// Controls what GET /hosts/capabilities does: 'ok' is the normal case, the
// other two are what the resilience tests below exercise.
let capsOutcome: 'ok' | 'error' | 'pending' = 'ok'

// The real shape of GET /hosts/capabilities (backend/proxploy/api/hosts.py),
// monitoring first and always required. The consequence-text tests below
// assert against this fixture's own `why` strings, not a literal repeated
// in the test, so they only pass if the component renders what the server
// actually sent.
const CAPABILITIES_CATALOG = [
  { key: 'monitoring', label: 'Read-only monitoring', required: true,
    why: 'Pollers, dashboard, metrics, and every read view. Always required.' },
  { key: 'lifecycle', label: 'Lifecycle', required: false,
    why: 'Start/stop/restart, resource edits, snapshots, clone, migration, VM create/destroy, '
       + 'and node-level network/storage config (bridges, storage pools, storage content).' },
  { key: 'console', label: 'Console', required: false,
    why: 'Console tickets for containers and VMs.' },
  { key: 'backup', label: 'Backup', required: false,
    why: 'vzdump/PBS backup and restore jobs, and backup listing.' },
]

vi.mock('../api/client', () => ({
  ApiError,
  api: vi.fn((path: string, opts?: RequestInit) => {
    const body = opts?.body ? JSON.parse(String(opts.body)) : null
    calls.push({ path, body })
    if (path === '/hosts/capabilities') {
      if (capsOutcome === 'error') return Promise.reject(new ApiError(500, { detail: 'boom' }))
      if (capsOutcome === 'pending') return new Promise(() => {})
      return Promise.resolve(CAPABILITIES_CATALOG)
    }
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

const withQuery = (ui: React.ReactNode) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return { ...render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>), qc }
}

const fill = (label: string, value: string) =>
  fireEvent.change(screen.getByLabelText(label), { target: { value } })

const fillHost = () => {
  fill('Name', 'pve-01')
  fill('Address', 'https://10.0.0.5:8006')
  fill('Monitoring token id', 'proxploy@pve!monitoring')
  fill('Monitoring token secret', 'mon-secret')
}

const credentialCalls = () => calls.filter(c => c.path.endsWith('/credentials'))
// Every assertion below that counts or indexes into `calls` cares about the
// host/credential requests HostForm's submit makes, not the capability
// catalog fetched on mount, so this is what those assertions filter on.
const hostCalls = () => calls.filter(c => c.path !== '/hosts/capabilities')

describe('HostForm capability tokens', () => {
  beforeEach(() => { calls.length = 0; reject = null; capsOutcome = 'ok' })
  afterEach(() => vi.restoreAllMocks())

  it('offers a token field for each capability still ticked, and none for the unticked', () => {
    withQuery(<HostForm onCreated={() => {}} />)
    expect(screen.getByLabelText('Lifecycle token id')).toBeInTheDocument()
    fireEvent.click(screen.getByLabelText(/^Lifecycle$/))
    expect(screen.queryByLabelText('Lifecycle token id')).not.toBeInTheDocument()
    expect(screen.getByLabelText('Backup token id')).toBeInTheDocument()
  })

  // The bug this relocation fixes: monitoring's token pair used to sit above
  // the box under a generic "API token" label, reading as a stray duplicate
  // of the capability tokens below it. Now all four collect in one place.
  it('collects the monitoring token in the same box as the other capability tokens, with no standalone API token field left at the top', () => {
    withQuery(<HostForm onCreated={() => {}} />)
    expect(screen.queryByLabelText('API token id')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('API token secret')).not.toBeInTheDocument()

    // .p-3, not .rounded-ctl: Button itself carries rounded-ctl, so that
    // selector matches the button before it reaches the surrounding box.
    const box = screen.getByRole('button', { name: 'Generate setup script' }).closest('.p-3')
    expect(box).not.toBeNull()
    const group = within(box as HTMLElement)
    expect(group.getByLabelText('Monitoring token id')).toBeInTheDocument()
    expect(group.getByLabelText('Monitoring token secret')).toBeInTheDocument()
    expect(group.getByLabelText('Lifecycle token id')).toBeInTheDocument()
    expect(group.getByLabelText('Console token id')).toBeInTheDocument()
    expect(group.getByLabelText('Backup token id')).toBeInTheDocument()
  })

  // Monitoring is mandatory, not another capability: it must render even
  // with every optional capability unticked, and stay a plain field, never a
  // checkbox.
  it('always shows the monitoring token fields, even with every capability unticked', () => {
    withQuery(<HostForm onCreated={() => {}} />)
    for (const label of ['Lifecycle', 'Console', 'Backup']) {
      fireEvent.click(screen.getByLabelText(new RegExp(`^${label}$`)))
    }
    expect(screen.getByLabelText('Monitoring token id')).toBeInTheDocument()
    expect(screen.getByLabelText('Monitoring token secret')).toBeInTheDocument()
    expect(screen.queryByRole('checkbox', { name: /monitoring/i })).not.toBeInTheDocument()
  })

  it('creates the host, then stores one capability token per filled pair', async () => {
    const onCreated = vi.fn()
    withQuery(<HostForm onCreated={onCreated} />)
    fillHost()
    fill('Lifecycle token id', 'proxploy@pve!lifecycle')
    fill('Lifecycle token secret', 'lc-secret')
    fireEvent.click(screen.getByRole('button', { name: 'Add host' }))

    await waitFor(() => expect(onCreated).toHaveBeenCalledWith({ id: 7, name: 'pve-01' }))
    expect(hostCalls()[0].path).toBe('/hosts')
    // The relocation moved where the monitoring token is collected, not what
    // POST /hosts sends: it still creates the host with token_id/token_secret
    // in the body, not as a fifth capability posted afterwards.
    expect(hostCalls()[0].body).toMatchObject({
      token_id: 'proxploy@pve!monitoring', token_secret: 'mon-secret',
    })
    expect(credentialCalls()).toEqual([{
      path: '/hosts/7/credentials',
      body: { token_id: 'proxploy@pve!lifecycle', token_secret: 'lc-secret',
              capability: 'lifecycle' },
    }])
  })

  it('skips a capability whose token pair was left blank', async () => {
    const onCreated = vi.fn()
    withQuery(<HostForm onCreated={onCreated} />)
    fillHost()
    fill('Console token id', 'proxploy@pve!console')  // secret left empty
    fireEvent.click(screen.getByRole('button', { name: 'Add host' }))
    await waitFor(() => expect(onCreated).toHaveBeenCalled())
    expect(credentialCalls()).toEqual([])
  })

  it('names the rejected capability, keeps the host, and does not advance', async () => {
    reject = 'console'
    const onCreated = vi.fn()
    withQuery(<HostForm onCreated={onCreated} />)
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
    withQuery(<HostForm onCreated={onCreated} />)
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
    withQuery(<HostForm onCreated={onCreated} />)
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
    withQuery(<HostForm onCreated={onCreated} />)
    fillHost()
    fireEvent.click(screen.getByRole('button', { name: 'Add host' }))
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith({ id: 7, name: 'pve-01' }))
    expect(hostCalls().map(c => c.path)).toEqual(['/hosts'])
  })

  // Finding #12: unticking every capability box (monitoring stays mandatory
  // and off-screen) must behave exactly as onboarding did before this
  // feature existed -- one POST and nothing else beyond the capability
  // catalog fetched once on mount, and no token-pair block.
  it('makes exactly one host-related call, to POST /hosts, when every capability is unticked', async () => {
    const onCreated = vi.fn()
    withQuery(<HostForm onCreated={onCreated} />)
    fillHost()
    for (const label of ['Lifecycle', 'Console', 'Backup']) {
      fireEvent.click(screen.getByLabelText(new RegExp(`^${label}$`)))
    }
    expect(screen.queryByText(/The script prints one token per capability/)).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Add host' }))
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith({ id: 7, name: 'pve-01' }))
    expect(hostCalls()).toHaveLength(1)
    expect(hostCalls()[0].path).toBe('/hosts')
  })

  // Finding #6: abandoning the form after the host is created (before Retry
  // or Continue) must not strand it -- invalidation happens at the point of
  // truth (POST /hosts resolving), not only inside onCreated. Proven with the
  // rejected-token flow, where onCreated is deliberately never called: the
  // old code only invalidated from the caller's onCreated, so this is the
  // one case that tells the two apart.
  it('invalidates the hosts list on host creation even when a rejected token means onCreated never fires', async () => {
    reject = 'console'
    const onCreated = vi.fn()
    const { qc } = withQuery(<HostForm onCreated={onCreated} />)
    const invalidateSpy = vi.spyOn(qc, 'invalidateQueries')
    fillHost()
    fill('Console token id', 'proxploy@pve!console')
    fill('Console token secret', 'bad')
    fireEvent.click(screen.getByRole('button', { name: 'Add host' }))
    await screen.findByText(/Console: .*did not work/i)
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['hosts'] })
    expect(onCreated).not.toHaveBeenCalled()
  })
})

// The "there is a section that says 'Don't have a token yet?'" request:
// unticking Lifecycle, Console, or Backup used to be silent about what that
// gives up. These assert against CAPABILITIES_CATALOG's own `why` strings,
// not a copy of them written into the test, so they only pass if the
// component is rendering what the server actually sent, not a paraphrase.
describe('HostForm capability consequence text', () => {
  beforeEach(() => { calls.length = 0; reject = null; capsOutcome = 'ok' })
  afterEach(() => vi.restoreAllMocks())

  const why = (key: string) => CAPABILITIES_CATALOG.find(c => c.key === key)!.why
  const untick = async (label: string) => {
    fireEvent.click(await screen.findByLabelText(new RegExp(`^${label}$`)))
  }

  it('names what stops working when Lifecycle is unticked', async () => {
    withQuery(<HostForm onCreated={() => {}} />)
    await untick('Lifecycle')
    expect(await screen.findByText((t) => t.includes(why('lifecycle')))).toBeInTheDocument()
  })

  it('names what stops working when Console is unticked', async () => {
    withQuery(<HostForm onCreated={() => {}} />)
    await untick('Console')
    expect(await screen.findByText((t) => t.includes(why('console')))).toBeInTheDocument()
  })

  it('names what stops working when Backup is unticked', async () => {
    withQuery(<HostForm onCreated={() => {}} />)
    await untick('Backup')
    expect(await screen.findByText((t) => t.includes(why('backup')))).toBeInTheDocument()
  })

  it('removes the consequence text once the capability is ticked again', async () => {
    withQuery(<HostForm onCreated={() => {}} />)
    await untick('Lifecycle')
    await screen.findByText((t) => t.includes(why('lifecycle')))
    fireEvent.click(screen.getByLabelText(new RegExp('^Lifecycle')))
    expect(screen.queryByText((t) => t.includes(why('lifecycle')))).not.toBeInTheDocument()
  })

  it('never renders monitoring as a checkbox and never shows its consequence text', async () => {
    withQuery(<HostForm onCreated={() => {}} />)
    await untick('Lifecycle')  // wait for the catalog so `why` text is possible at all
    expect(screen.queryByRole('checkbox', { name: /monitoring/i })).not.toBeInTheDocument()
    expect(screen.queryByText((t) => t.includes(why('monitoring')))).not.toBeInTheDocument()
  })

  // The important one: an operator must never be blocked from adding a host
  // because this descriptive endpoint is slow or broken.
  it('still renders every checkbox and can add a host while the capabilities query is loading', async () => {
    capsOutcome = 'pending'
    const onCreated = vi.fn()
    withQuery(<HostForm onCreated={onCreated} />)
    fillHost()
    expect(screen.getByLabelText(/^Lifecycle$/)).toBeInTheDocument()
    expect(screen.getByLabelText(/^Console$/)).toBeInTheDocument()
    expect(screen.getByLabelText(/^Backup$/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Add host' }))
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith({ id: 7, name: 'pve-01' }))
  })

  it('still renders every checkbox and can add a host when the capabilities query fails', async () => {
    capsOutcome = 'error'
    const onCreated = vi.fn()
    withQuery(<HostForm onCreated={onCreated} />)
    fillHost()
    expect(screen.getByLabelText(/^Lifecycle$/)).toBeInTheDocument()
    expect(screen.getByLabelText(/^Console$/)).toBeInTheDocument()
    expect(screen.getByLabelText(/^Backup$/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Add host' }))
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith({ id: 7, name: 'pve-01' }))
  })
})
