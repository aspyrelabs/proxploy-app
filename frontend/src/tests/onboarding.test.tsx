import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

type Onboarding = { admin_exists: boolean; host_added: boolean
                    ssh_pending: boolean; complete: boolean }
type HostDetail = { id: number; name: string
                    credentials: { kind: string; public_meta: string | null }[] }

let onboarding: Onboarding = { admin_exists: false, host_added: false,
  ssh_pending: false, complete: false }
let hostList: { id: number }[] = []
let hostDetail: Record<number, HostDetail> = {}
let verifyOutcome: { ok: true } | { ok: false; body: unknown } = { ok: true }
let meAuthed = true
let probeResult: unknown = { version: '9.2.10', release: '9.2', missing_privileges: [] }
// Held open by the pending-state tests below so they can observe the
// indeterminate ring before the awaited call resolves.
let probeHeld = false
let releaseProbe: ((v: unknown) => void) | null = null
let addHeld = false
let releaseAdd: ((v: unknown) => void) | null = null
let verifyHeld = false
let releaseVerify: ((v: unknown) => void) | null = null
const scriptResult = { script: "# Proxploy\npveum role add ProxployAudit -privs 'VM.Audit'\n",
                       capabilities: [
                         { key: 'monitoring', label: 'Read-only monitoring', why: 'Always required.', required: true, role: 'ProxployAudit' },
                         { key: 'lifecycle', label: 'Lifecycle', why: 'Start/stop.', required: false, role: 'ProxployLifecycle' },
                       ] }
let scriptCalls: { capabilities: string[]; node_shell: boolean; node_power: boolean }[] = []

function mockOnboarding(ob: Onboarding) { onboarding = ob }
// Simulates the reload case: no in-session host object, only what the
// server still knows, GET /hosts then GET /hosts/{id}.
function mockStoredHost(h: HostDetail) { hostList = [{ id: h.id }]; hostDetail[h.id] = h }
function mockVerifyFailure(body: unknown) { verifyOutcome = { ok: false, body } }
// The session died but the admin still exists: /auth/me 401s.
function mockSignedOut() { meAuthed = false }

beforeEach(() => {
  onboarding = { admin_exists: false, host_added: false, ssh_pending: false, complete: false }
  hostList = []
  hostDetail = {}
  verifyOutcome = { ok: true }
  meAuthed = true
  probeResult = { version: '9.2.10', release: '9.2', missing_privileges: [] }
  scriptCalls = []
  probeHeld = false; releaseProbe = null
  addHeld = false; releaseAdd = null
  verifyHeld = false; releaseVerify = null
})

vi.mock('../api/client', () => {
  class ApiErrorImpl extends Error {
    status: number; body: unknown
    constructor(status: number, body: unknown) { super(`API ${status}`); this.status = status; this.body = body }
  }
  return {
    api: vi.fn((path: string, init?: RequestInit) => {
      if (path === '/hosts/token-script' && init?.body) scriptCalls.push(JSON.parse(String(init.body)))
      if (path === '/meta/onboarding') return Promise.resolve(onboarding)
      if (path === '/auth/me') {
        return meAuthed
          ? Promise.resolve({ id: 1, email: 'ops@acme.io',
              display_name: 'Ops', role: 'owner', totp_enabled: false })
          : Promise.reject(new ApiErrorImpl(401, { detail: 'authentication required' }))
      }
      if (path === '/hosts/token-script') return Promise.resolve(scriptResult)
      if (path === '/hosts/probe') {
        if (probeHeld) return new Promise((resolve) => { releaseProbe = resolve })
        return Promise.resolve(probeResult)
      }
      if (path === '/hosts' && init?.method === 'POST') {
        if (addHeld) return new Promise((resolve) => { releaseAdd = resolve })
        return Promise.resolve({ id: 7, name: JSON.parse(String(init.body)).name })
      }
      if (path === '/hosts') return Promise.resolve(hostList)
      if (path.endsWith('/ssh/verify')) {
        if (verifyHeld) return new Promise((resolve) => { releaseVerify = resolve })
        return verifyOutcome.ok
          ? Promise.resolve({ verified: true, verified_at: 'now' })
          : Promise.reject(new ApiErrorImpl(502, verifyOutcome.body))
      }
      const m = /^\/hosts\/(\d+)$/.exec(path)
      if (m) return Promise.resolve(hostDetail[Number(m[1])] ?? null)
      return Promise.resolve(null)
    }),
    ApiError: ApiErrorImpl,
  }
})

vi.mock('@tanstack/react-router', async (orig) => ({
  ...(await orig() as object),
  useNavigate: () => vi.fn(),
}))

import { HostForm } from '../components/HostForm'
import { Wizard } from '../routes/onboarding'

const withQuery = (ui: React.ReactNode) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

const renderWizard = () => withQuery(<Wizard />)

describe('HostForm', () => {
  it('shows the honest root-consent copy with the SSH checkbox', () => {
    render(<HostForm onCreated={() => {}} />)
    expect(screen.getByLabelText(/address/i)).toBeDefined()
    // Exact, not /token id/i: the field's info button is labelled "What is the
    // API token id?" and a loose match now finds both.
    expect(screen.getByLabelText('API token id')).toBeDefined()
    expect(screen.getByText(/root shell on the node/i)).toBeDefined()
    expect(screen.getByRole('button', { name: /test connection/i })).toBeDefined()
  })

  // The two token fields were the only ones asking for something the operator
  // has to go and create elsewhere, with no hint of what it is or where it
  // comes from.
  it('explains the API token id and links to the docs', () => {
    render(<HostForm onCreated={() => {}} />)
    const toggle = screen.getByRole('button', { name: /what is the api token id/i })
    expect(screen.queryByText(/user@realm!name/)).not.toBeInTheDocument()

    fireEvent.click(toggle)
    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByText(/user@realm!name/)).toBeInTheDocument()

    const link = screen.getByRole('link', { name: /how to create one/i })
    expect(link).toHaveAttribute('href',
      'https://docs.proxploy.com/getting-started/proxmox-token/')
    expect(link).toHaveAttribute('target', '_blank')
    expect(link.getAttribute('rel')).toContain('noreferrer')
  })

  it('reports privileges the token is missing when testing the connection', async () => {
    // "Connected, PVE 9.2.10" on a token that cannot read rrddata is how a
    // host got enrolled broken and then reported as unreachable minutes later.
    probeResult = { version: '9.2.10', release: '9.2',
                    missing_privileges: ['Sys.Audit', 'Pool.Audit'] }
    render(<HostForm onCreated={() => {}} />)
    fireEvent.click(screen.getByRole('button', { name: /test connection/i }))
    expect(await screen.findByText(/Sys\.Audit/)).toBeInTheDocument()
    expect(screen.getByText(/Pool\.Audit/)).toBeInTheDocument()
  })

  it('says plainly when the token has everything it needs', async () => {
    probeResult = { version: '9.2.10', release: '9.2', missing_privileges: [] }
    render(<HostForm onCreated={() => {}} />)
    fireEvent.click(screen.getByRole('button', { name: /test connection/i }))
    expect(await screen.findByText(/Connected, PVE 9\.2\.10/)).toBeInTheDocument()
    expect(screen.queryByText(/missing/i)).not.toBeInTheDocument()
  })

  it('offers the pveum script so the operator never invents the privileges', async () => {
    render(<HostForm onCreated={() => {}} />)
    fireEvent.click(screen.getByRole('button', { name: /generate.*script|need a token/i }))
    expect(await screen.findByText(/pveum role add ProxployAudit/)).toBeInTheDocument()
  })

  it('copies exactly the script it displays', async () => {
    const writeText = vi.fn(() => Promise.resolve())
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
    render(<HostForm onCreated={() => {}} />)
    fireEvent.click(screen.getByRole('button', { name: /generate.*script|need a token/i }))
    await screen.findByText(/pveum role add ProxployAudit/)
    fireEvent.click(screen.getByRole('button', { name: /copy script/i }))
    expect(writeText).toHaveBeenCalledWith(scriptResult.script)
  })

  it('asks only for the capabilities left ticked', async () => {
    render(<HostForm onCreated={() => {}} />)
    // Doc 08: monitoring is mandatory, the rest are the operator's choice.
    fireEvent.click(screen.getByLabelText(/^Lifecycle$/))
    fireEvent.click(screen.getByRole('button', { name: /generate.*script/i }))
    await screen.findByText(/pveum role add ProxployAudit/)
    expect(scriptCalls.at(-1)?.capabilities).not.toContain('lifecycle')
    expect(scriptCalls.at(-1)?.capabilities).toContain('backup')
  })

  it('asks for Sys.Console only when node shells are opted into', async () => {
    render(<HostForm onCreated={() => {}} />)
    fireEvent.click(screen.getByRole('button', { name: /generate.*script|need a token/i }))
    await screen.findByText(/pveum role add ProxployAudit/)
    const calls = scriptCalls.at(-1)
    expect(calls?.node_shell).toBe(false)
  })

  it('asks for node power only when explicitly ticked, independent of capabilities', async () => {
    render(<HostForm onCreated={() => {}} />)
    fireEvent.click(screen.getByRole('button', { name: /generate.*script|need a token/i }))
    await screen.findByText(/pveum role add ProxployAudit/)
    // Off by default: the same "never widen a scope the operator did not
    // explicitly ask for" reasoning as node_shell above.
    expect(scriptCalls.at(-1)?.node_power).toBe(false)

    fireEvent.click(screen.getByLabelText(/node power/i))
    fireEvent.click(screen.getByRole('button', { name: /generate.*script/i }))
    await screen.findByText(/pveum role add ProxployAudit/)
    expect(scriptCalls.at(-1)?.node_power).toBe(true)
  })

  it('leaves TLS verification off by default', () => {
    // A stock Proxmox node serves a self-signed certificate, so verifying by
    // default failed the very first connection for almost everyone.
    render(<HostForm onCreated={() => {}} />)
    expect(screen.getByLabelText(/verify tls certificate/i)).not.toBeChecked()
  })

  it('warns that the token secret is shown only once', () => {
    render(<HostForm onCreated={() => {}} />)
    fireEvent.click(screen.getByRole('button', { name: /what is the api token secret/i }))
    expect(screen.getByText(/only once/i)).toBeInTheDocument()
  })

  it('collapses an open explanation again', () => {
    render(<HostForm onCreated={() => {}} />)
    const toggle = screen.getByRole('button', { name: /what is the api token id/i })
    fireEvent.click(toggle)
    fireEvent.click(toggle)
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByText(/user@realm!name/)).not.toBeInTheDocument()
  })

  it('shows the indeterminate ring while testing the connection, no percentage', async () => {
    probeHeld = true
    render(<HostForm onCreated={() => {}} />)
    fireEvent.click(screen.getByRole('button', { name: /test connection/i }))

    const status = await screen.findByRole('status')
    expect(status).toHaveAttribute('aria-busy', 'true')
    expect(document.body.textContent).not.toMatch(/\d+ ?%/)

    releaseProbe?.({ version: '9.2.10', release: '9.2', missing_privileges: [] })
    expect(await screen.findByText(/Connected, PVE 9\.2\.10/)).toBeInTheDocument()
  })

  it('shows the indeterminate ring while adding the host, no percentage', async () => {
    addHeld = true
    const onCreated = vi.fn()
    render(<HostForm onCreated={onCreated} />)
    fireEvent.change(screen.getByLabelText(/^name$/i), { target: { value: 'pve-01' } })
    fireEvent.change(screen.getByLabelText(/address/i), { target: { value: 'https://10.0.0.5:8006' } })
    fireEvent.change(screen.getByLabelText('API token id'), { target: { value: 'proxploy@pve!x' } })
    fireEvent.change(screen.getByLabelText('API token secret'), { target: { value: 'secret' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add host' }))

    const status = await screen.findByRole('status')
    expect(status).toHaveAttribute('aria-busy', 'true')
    expect(document.body.textContent).not.toMatch(/\d+ ?%/)

    releaseAdd?.({ id: 7, name: 'pve-01' })
    await new Promise((r) => setTimeout(r, 0))
    expect(onCreated).toHaveBeenCalled()
  })
})

describe('onboarding wizard', () => {
  it('resumes at the host step when the admin already exists', async () => {
    // The reload bug: local useState always restarted at step 0 and then
    // told the user their password was bad.
    mockOnboarding({ admin_exists: true, host_added: false, ssh_pending: false, complete: false })
    renderWizard()
    expect(await screen.findByLabelText('API token id')).toBeInTheDocument()
    expect(screen.queryByLabelText('Password (12+ chars)')).not.toBeInTheDocument()
  })

  it('resumes at the install step when a key is enrolled but unverified', async () => {
    // ssh_pending cannot tell "key pasted" from "not pasted", so the server
    // can only put you at Install; reaching Verify is a local acknowledgement.
    mockOnboarding({ admin_exists: true, host_added: true, ssh_pending: true, complete: false })
    renderWizard()
    expect(await screen.findByRole('button', { name: 'I have added it' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Verify access' })).not.toBeInTheDocument()
  })

  it('reaches the verify step from install', async () => {
    mockOnboarding({ admin_exists: true, host_added: true, ssh_pending: true, complete: false })
    mockStoredHost({ id: 7, name: 'pve1', credentials: [] })
    renderWizard()
    fireEvent.click(await screen.findByRole('button', { name: 'I have added it' }))
    expect(await screen.findByRole('button', { name: 'Verify access' })).toBeInTheDocument()
  })

  it('will not advance until the key actually works', async () => {
    mockOnboarding({ admin_exists: true, host_added: true, ssh_pending: true, complete: false })
    mockStoredHost({ id: 7, name: 'pve1', credentials: [] })
    mockVerifyFailure({ error: 'command_failed', detail: 'the key authenticated but `true` exited 1' })
    renderWizard()
    fireEvent.click(await screen.findByRole('button', { name: 'I have added it' }))
    fireEvent.click(await screen.findByRole('button', { name: /verify access/i }))
    expect(await screen.findByText(/not authorized yet/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /open the dashboard/i })).not.toBeInTheDocument()
  })

  it('calls out a host key mismatch as a security event, distinct from "not yet"', async () => {
    mockOnboarding({ admin_exists: true, host_added: true, ssh_pending: true, complete: false })
    mockStoredHost({ id: 7, name: 'pve1', credentials: [] })
    mockVerifyFailure({ error: 'host_key_mismatch', detail: 'fingerprint changed' })
    renderWizard()
    fireEvent.click(await screen.findByRole('button', { name: 'I have added it' }))
    fireEvent.click(await screen.findByRole('button', { name: /verify access/i }))
    expect(await screen.findByText(/stop and investigate/i)).toBeInTheDocument()
    expect(screen.queryByText(/not authorized yet/i)).not.toBeInTheDocument()
  })

  it('shows the indeterminate ring while SSH verify is in flight, no percentage', async () => {
    // The verify call has no progress signal (proxploy/services/ never calls
    // ctx.progress() for this path either), so the wait must announce itself
    // as busy without ever claiming a figure.
    mockOnboarding({ admin_exists: true, host_added: true, ssh_pending: true, complete: false })
    mockStoredHost({ id: 7, name: 'pve1', credentials: [] })
    verifyHeld = true
    renderWizard()
    fireEvent.click(await screen.findByRole('button', { name: 'I have added it' }))
    fireEvent.click(await screen.findByRole('button', { name: /verify access/i }))

    const status = await screen.findByRole('status')
    expect(status).toHaveAttribute('aria-busy', 'true')
    expect(document.body.textContent).not.toMatch(/\d+ ?%/)

    releaseVerify?.({ verified: true, verified_at: 'now' })
    expect(await screen.findByRole('button', { name: /open the dashboard/i })).toBeInTheDocument()
  })

  it('advances once the server actually verifies the key', async () => {
    mockOnboarding({ admin_exists: true, host_added: true, ssh_pending: true, complete: false })
    mockStoredHost({ id: 7, name: 'pve1', credentials: [{ kind: 'ssh_key', public_meta: 'ssh-ed25519 AAAA reload' }] })
    renderWizard()
    fireEvent.click(await screen.findByRole('button', { name: 'I have added it' }))
    fireEvent.click(await screen.findByRole('button', { name: /verify access/i }))
    expect(await screen.findByRole('button', { name: /open the dashboard/i })).toBeInTheDocument()
  })

  it('recovers the authorized_keys line after a reload with no host in session', async () => {
    mockOnboarding({ admin_exists: true, host_added: true, ssh_pending: true, complete: false })
    mockStoredHost({ id: 7, name: 'pve1', credentials: [
      { kind: 'api_token', public_meta: 'tok' },
      { kind: 'ssh_key', public_meta: 'ssh-ed25519 AAAAreload proxploy@pve-01' },
    ] })
    renderWizard()
    expect(await screen.findByText(/ssh-ed25519 AAAAreload/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /copy/i })).toBeInTheDocument()
  })

  it('copies exactly the command it displays, not just the bare key', async () => {
    const writeText = vi.fn(() => Promise.resolve())
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
    const key = 'ssh-ed25519 AAAAreload proxploy@pve-01'
    mockOnboarding({ admin_exists: true, host_added: true, ssh_pending: true, complete: false })
    mockStoredHost({ id: 7, name: 'pve1', credentials: [{ kind: 'ssh_key', public_meta: key }] })
    renderWizard()

    fireEvent.click(await screen.findByRole('button', { name: /copy/i }))
    // Copying the bare key while showing a shell command means whatever the
    // operator pastes into the node shell is not what the screen told them to
    // run.
    expect(writeText).toHaveBeenCalledWith(
      `echo '${key}' >> /root/.ssh/authorized_keys`)
  })

  it('starts at the admin step on a truly fresh install', async () => {
    mockOnboarding({ admin_exists: false, host_added: false, ssh_pending: false, complete: false })
    renderWizard()
    expect(await screen.findByLabelText('Password (12+ chars)')).toBeInTheDocument()
  })

  it('lands on the done step once everything is settled', async () => {
    mockOnboarding({ admin_exists: true, host_added: true, ssh_pending: false, complete: false })
    renderWizard()
    expect(await screen.findByRole('button', { name: /open the dashboard/i })).toBeInTheDocument()
  })

  it('lets a stranger skip the host step entirely', async () => {
    mockOnboarding({ admin_exists: true, host_added: false, ssh_pending: false, complete: false })
    renderWizard()
    fireEvent.click(await screen.findByRole('button', { name: /skip for now/i }))
    expect(await screen.findByRole('button', { name: /open the dashboard/i })).toBeInTheDocument()
  })

  it('lets you go back to a completed step', async () => {
    mockOnboarding({ admin_exists: true, host_added: false, ssh_pending: false, complete: false })
    renderWizard()
    // Lands on the host step, per the resume behaviour above.
    expect(await screen.findByLabelText('API token id')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /^Account/ }))
    expect(await screen.findByText(/cannot be changed/i)).toBeInTheDocument()
  })

  it('re-logs in after a password reset so the wizard is not logged out', async () => {
    const { api } = await import('../api/client')
    mockOnboarding({ admin_exists: true, host_added: false, ssh_pending: false, complete: false })
    renderWizard()
    await screen.findByLabelText('API token id')
    fireEvent.click(screen.getByRole('button', { name: /^Account/ }))

    fireEvent.change(await screen.findByLabelText('New password'),
      { target: { value: 'correct-horse-battery' } })
    fireEvent.click(screen.getByRole('button', { name: /set new password/i }))

    expect(await screen.findByText(/password updated/i)).toBeInTheDocument()
    const paths = (api as unknown as { mock: { calls: [string, RequestInit?][] } })
      .mock.calls.map(c => c[0])
    // The reset revokes every session including this one, so the login that
    // follows it is what keeps the wizard usable.
    expect(paths).toContain('/users/1/password')
    expect(paths.indexOf('/auth/login')).toBeGreaterThan(paths.indexOf('/users/1/password'))
  })

  it('offers remove-and-re-add when you go back to a host already added', async () => {
    mockOnboarding({ admin_exists: true, host_added: true, ssh_pending: true, complete: false })
    mockStoredHost({ id: 7, name: 'pve1', credentials: [] })
    renderWizard()
    await screen.findByRole('button', { name: 'I have added it' })
    fireEvent.click(screen.getByRole('button', { name: /^Host/ }))
    expect(await screen.findByRole('button', { name: /remove and re-add/i })).toBeInTheDocument()
    // The add form must NOT be offered while a host still exists.
    expect(screen.queryByLabelText('API token id')).not.toBeInTheDocument()
  })

  it('keeps a skipped host step clickable', async () => {
    mockOnboarding({ admin_exists: true, host_added: false, ssh_pending: false, complete: false })
    renderWizard()
    await screen.findByLabelText('API token id')
    fireEvent.click(screen.getByRole('button', { name: /skip for now/i }))
    const host = await screen.findByRole('button', { name: /^Host/ })
    expect(host.getAttribute('data-status')).toBe('skipped')
    expect(host).not.toBeDisabled()
  })

  it('will not review a password the server would reject', async () => {
    const { api } = await import('../api/client')
    mockOnboarding({ admin_exists: false, host_added: false, ssh_pending: false, complete: false })
    renderWizard()
    fireEvent.change(await screen.findByLabelText('Email'), { target: { value: 'short@example.com' } })
    fireEvent.change(screen.getByLabelText('Password (12+ chars)'), { target: { value: '123' } })
    fireEvent.click(screen.getByRole('button', { name: /review/i }))

    // "12+ chars" was a label the form never enforced: the only check was
    // UserIn's, surfacing as a 422 after the review screen had already said
    // the details were worth committing.
    expect(await screen.findByText(/at least 12 characters/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /create account/i })).not.toBeInTheDocument()
    expect((api as unknown as { mock: { calls: [string][] } }).mock.calls
      .map(c => c[0])).not.toContain('/users')
  })

  it('states the minimum on the field itself, not just in the label', async () => {
    mockOnboarding({ admin_exists: false, host_added: false, ssh_pending: false, complete: false })
    renderWizard()
    // The browser's own affordance, so the constraint is enforced before any
    // click as well as after.
    expect((await screen.findByLabelText('Password (12+ chars)'))
      .getAttribute('minlength')).toBe('12')
  })

  it('lets you correct the email at the review stage, before anything is created', async () => {
    const { api } = await import('../api/client')
    mockOnboarding({ admin_exists: false, host_added: false, ssh_pending: false, complete: false })
    renderWizard()
    fireEvent.change(await screen.findByLabelText('Email'), { target: { value: 'typo@acme.io' } })
    fireEvent.change(screen.getByLabelText('Password (12+ chars)'),
      { target: { value: 'correct-horse-battery' } })
    fireEvent.click(screen.getByRole('button', { name: /review/i }))

    // Nothing is committed yet: the review screen is still local.
    expect(await screen.findByText('typo@acme.io')).toBeInTheDocument()
    expect((api as unknown as { mock: { calls: [string][] } }).mock.calls
      .map(c => c[0])).not.toContain('/users')

    fireEvent.click(screen.getByRole('button', { name: /change details/i }))
    fireEvent.change(await screen.findByLabelText('Email'), { target: { value: 'ops@acme.io' } })
    fireEvent.click(screen.getByRole('button', { name: /review/i }))
    expect(await screen.findByText('ops@acme.io')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /create account/i }))
    const bodies = (api as unknown as { mock: { calls: [string, RequestInit?][] } })
      .mock.calls.filter(c => c[0] === '/users')
    expect(bodies).toHaveLength(1)
    expect(JSON.parse(String(bodies[0][1]?.body)).email).toBe('ops@acme.io')
  })

  it('does not re-offer the create form when the session died', async () => {
    // admin_exists is true but /auth/me 401s. Rendering the create form here
    // would POST /users for an account that exists and surface as "your
    // password is bad", the same confusion stepFrom() was written to kill.
    mockOnboarding({ admin_exists: true, host_added: false, ssh_pending: false, complete: false })
    mockSignedOut()
    renderWizard()
    await screen.findByLabelText('API token id')
    fireEvent.click(screen.getByRole('button', { name: /^Account/ }))
    expect(await screen.findByText(/signed out/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /create admin account/i })).not.toBeInTheDocument()
  })

  it('does not let you jump forward past the step the server is on', async () => {
    mockOnboarding({ admin_exists: true, host_added: false, ssh_pending: false, complete: false })
    renderWizard()
    await screen.findByLabelText('API token id')
    expect(screen.getByRole('button', { name: /^Install/ })).toBeDisabled()
  })
})
