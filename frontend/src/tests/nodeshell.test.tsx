import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, waitFor, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

vi.mock('../api/client', () => ({ api: vi.fn() }))
import { api } from '../api/client'

// NodeDetailPage is the route's own component and calls useParams() itself
// (see AppDetail/AppOverview in routes/apps.tsx for the same shape), it
// needs a route match to read $hostId from, which a bare QueryClientProvider
// doesn't provide. Stub just that hook, same technique cluster.test.tsx uses
// for Link/useNavigate/useSearch.
vi.mock('@tanstack/react-router', async (orig) => ({
  ...(await orig() as object),
  useParams: () => ({ hostId: '7' }),
}))

describe('node shell section', () => {
  it('shows a disabled button with a tooltip when node_shell_enabled is false', async () => {
    vi.mocked(api).mockImplementation((path: string) => {
      if (path.includes('/entitlements')) return Promise.resolve({ tier: 'pro', features: { 'terminal.node': true }, grace: null, clock_skew: false })
      if (path.startsWith('/hosts/')) return Promise.resolve({ id: 7, name: 'pve1', node_shell_enabled: false })
      return Promise.resolve([])
    })
    const { NodeDetailPage } = await import('../routes/hosts')
    const qc = new QueryClient()
    render(
      <QueryClientProvider client={qc}>
        <NodeDetailPage />
      </QueryClientProvider>,
    )
    // /node shell/i alone would match both the "Node shell" heading and the
    // "Open node shell" button text, scope to the heading to disambiguate.
    await waitFor(() => expect(screen.getByRole('heading', { name: /node shell/i })).toBeInTheDocument())
    const btn = screen.getByRole('button', { name: /open node shell/i })
    expect(btn).toBeDisabled()
    // Distinguish the two independent gates: this reason is the per-host
    // opt-in, not the entitlement. Wait for it, since entitlements/host
    // queries can still be in flight right after the heading first mounts.
    await waitFor(() => expect(btn).toHaveAttribute('title', 'Enable node shell in host settings first'))
  })

  it('shows the entitlement tooltip when terminal.node is off, even if the host opted in', async () => {
    vi.mocked(api).mockImplementation((path: string) => {
      if (path.includes('/entitlements')) return Promise.resolve({ tier: 'builtin', features: { 'terminal.node': false }, grace: null, clock_skew: false })
      if (path.startsWith('/hosts/')) return Promise.resolve({ id: 7, name: 'pve1', node_shell_enabled: true })
      return Promise.resolve([])
    })
    const { NodeDetailPage } = await import('../routes/hosts')
    const qc = new QueryClient()
    render(
      <QueryClientProvider client={qc}>
        <NodeDetailPage />
      </QueryClientProvider>,
    )
    const btn = await screen.findByRole('button', { name: /open node shell/i })
    await waitFor(() => expect(btn).toBeDisabled())
    await waitFor(() => expect(btn).toHaveAttribute('title', 'Pro: Node shells'))
  })
})
