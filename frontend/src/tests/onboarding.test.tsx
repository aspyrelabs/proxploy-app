import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

type Onboarding = { admin_exists: boolean; host_added: boolean
                    ssh_pending: boolean; complete: boolean }

let onboarding: Onboarding = { admin_exists: false, host_added: false,
  ssh_pending: false, complete: false }
function mockOnboarding(ob: Onboarding) { onboarding = ob }

vi.mock('../api/client', () => ({
  api: vi.fn((path: string) => {
    if (path === '/meta/onboarding') return Promise.resolve(onboarding)
    return Promise.resolve(null)
  }),
  ApiError: class extends Error {},
}))

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
    expect(await screen.findByRole('button', { name: 'I have authorized it' })).toBeInTheDocument()
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
