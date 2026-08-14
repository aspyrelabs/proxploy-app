import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, fireEvent } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

const hostRows = [{ id: 3, name: 'pve-01', address: 'https://10.0.0.5:8006', status: 'connected',
                   pve_version: '8.4.1', node_shell_enabled: false, team_id: null }]

vi.mock('../api/client', () => ({
  ApiError: class extends Error {},
  api: vi.fn((path: string) => {
    if (path === '/hosts') return Promise.resolve(hostRows)
    if (path === '/hosts/3') {
      return Promise.resolve({ id: 3, name: 'pve-01', capabilities: {
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
import { SettingsPage } from '../routes/settings'

const wrap = () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}><SettingsPage /></QueryClientProvider>)
}

describe('Settings host tokens', () => {
  it('opens the capability list for a host from the Tokens button', async () => {
    wrap()
    fireEvent.click(await screen.findByRole('button', { name: 'Tokens' }))
    expect(await screen.findByText('Lifecycle')).toBeInTheDocument()
    // The dialog opens with its fields closed on every row now, so what proves
    // the list rendered is the control that would reveal them, not the field.
    // Four capabilities left open would have unrolled eight inputs on open.
    expect(screen.queryByLabelText('Lifecycle token id')).not.toBeInTheDocument()
    expect(screen.getByRole('button',
      { name: 'Add Lifecycle token, show fields' })).toBeInTheDocument()
  })
})
