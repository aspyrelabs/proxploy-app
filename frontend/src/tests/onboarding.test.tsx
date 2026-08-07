import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

type Onboarding = { admin_exists: boolean; host_added: boolean
                    ssh_pending: boolean; complete: boolean }
type HostDetail = { id: number
                    credentials: { kind: string; public_meta: string | null }[] }

let onboarding: Onboarding = { admin_exists: false, host_added: false,
  ssh_pending: false, complete: false }
let hostList: { id: number }[] = []
let hostDetail: Record<number, HostDetail> = {}
let verifyOutcome: { ok: true } | { ok: false; body: unknown } = { ok: true }

function mockOnboarding(ob: Onboarding) { onboarding = ob }
// Simulates the reload case: no in-session host object, only what the
// server still knows, GET /hosts then GET /hosts/{id}.
function mockStoredHost(h: HostDetail) { hostList = [{ id: h.id }]; hostDetail[h.id] = h }
function mockVerifyFailure(body: unknown) { verifyOutcome = { ok: false, body } }

beforeEach(() => {
  onboarding = { admin_exists: false, host_added: false, ssh_pending: false, complete: false }
  hostList = []
  hostDetail = {}
  verifyOutcome = { ok: true }
})

vi.mock('../api/client', () => {
  class ApiErrorImpl extends Error {
    status: number; body: unknown
    constructor(status: number, body: unknown) { super(`API ${status}`); this.status = status; this.body = body }
  }
  return {
    api: vi.fn((path: string) => {
      if (path === '/meta/onboarding') return Promise.resolve(onboarding)
      if (path === '/hosts') return Promise.resolve(hostList)
      if (path.endsWith('/ssh/verify')) {
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
    expect(screen.getByLabelText(/token id/i)).toBeDefined()
    expect(screen.getByText(/root shell on the node/i)).toBeDefined()
    expect(screen.getByRole('button', { name: /test connection/i })).toBeDefined()
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

  it('resumes at the authorize step when a key is enrolled but unverified', async () => {
    mockOnboarding({ admin_exists: true, host_added: true, ssh_pending: true, complete: false })
    renderWizard()
    expect(await screen.findByRole('button', { name: 'Verify access' })).toBeInTheDocument()
  })

  it('will not advance until the key actually works', async () => {
    mockOnboarding({ admin_exists: true, host_added: true, ssh_pending: true, complete: false })
    mockStoredHost({ id: 7, credentials: [] })
    mockVerifyFailure({ error: 'command_failed', detail: 'the key authenticated but `true` exited 1' })
    renderWizard()
    fireEvent.click(await screen.findByRole('button', { name: /verify access/i }))
    expect(await screen.findByText(/not authorized yet/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /open the dashboard/i })).not.toBeInTheDocument()
  })

  it('calls out a host key mismatch as a security event, distinct from "not yet"', async () => {
    mockOnboarding({ admin_exists: true, host_added: true, ssh_pending: true, complete: false })
    mockStoredHost({ id: 7, credentials: [] })
    mockVerifyFailure({ error: 'host_key_mismatch', detail: 'fingerprint changed' })
    renderWizard()
    fireEvent.click(await screen.findByRole('button', { name: /verify access/i }))
    expect(await screen.findByText(/stop and investigate/i)).toBeInTheDocument()
    expect(screen.queryByText(/not authorized yet/i)).not.toBeInTheDocument()
  })

  it('advances once the server actually verifies the key', async () => {
    mockOnboarding({ admin_exists: true, host_added: true, ssh_pending: true, complete: false })
    mockStoredHost({ id: 7, credentials: [{ kind: 'ssh_key', public_meta: 'ssh-ed25519 AAAA reload' }] })
    renderWizard()
    fireEvent.click(await screen.findByRole('button', { name: /verify access/i }))
    expect(await screen.findByRole('button', { name: /open the dashboard/i })).toBeInTheDocument()
  })

  it('recovers the authorized_keys line after a reload with no host in session', async () => {
    mockOnboarding({ admin_exists: true, host_added: true, ssh_pending: true, complete: false })
    mockStoredHost({ id: 7, credentials: [
      { kind: 'api_token', public_meta: 'tok' },
      { kind: 'ssh_key', public_meta: 'ssh-ed25519 AAAAreload proxploy@pve-01' },
    ] })
    renderWizard()
    expect(await screen.findByText(/ssh-ed25519 AAAAreload/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /copy key line/i })).toBeInTheDocument()
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
})
