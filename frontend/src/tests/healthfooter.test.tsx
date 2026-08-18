import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

const state: { alerts: any[]; hosts: any[]; error: boolean } = { alerts: [], hosts: [], error: false }

vi.mock('../api/client', () => ({
  ApiError: class extends Error {},
  api: vi.fn((path: string) => {
    if (state.error) return Promise.reject(new Error('boom'))
    if (path.startsWith('/alerts')) return Promise.resolve(state.alerts)
    if (path === '/cluster/nodes') return Promise.resolve(state.hosts)
    return Promise.resolve(null)
  }),
}))

// Router-dependent bits (Link) need a real router in tests; mock them thin,
// matching cluster.test.tsx / activity.test.tsx. Spread the rest of the
// props through (not just children): the collapsed footer's accessible name
// and Radix's Tooltip.Trigger asChild wiring both ride on props Link would
// otherwise swallow.
vi.mock('@tanstack/react-router', async (orig) => ({
  ...(await orig() as object),
  Link: ({ to, children, ...rest }: { to?: string; children?: unknown }) =>
    <a href={to} {...rest}>{children as never}</a>,
}))

import { HealthFooter } from '../components/HealthFooter'

const wrap = (ui: React.ReactNode) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

/** Both queries have answered. The healthy footer renders nothing, and so does
 *  a pending one, so "empty" only means "nothing is wrong" once these landed. */
const fetched = async () => {
  const { api } = await import('../api/client')
  const paths = (api as ReturnType<typeof vi.fn>).mock.calls.map((c) => String(c[0]))
  return paths.some((p) => p.startsWith('/alerts')) && paths.includes('/cluster/nodes')
}

describe('HealthFooter', () => {
  it('renders nothing at all when nothing is wrong', async () => {
    // It used to say "All systems healthy". A standing reassurance derived from
    // three checks asserts health on everything it does not look at, which is
    // how it came to read healthy over a cluster that had lost quorum and could
    // not accept a write (doc 12 check 12). Silence cannot fail that way.
    state.alerts = []
    state.hosts = [{ status: 'connected' }, { status: 'connected' },
                   { status: 'connected' }]
    const { container } = wrap(<HealthFooter />)
    // Waited for, not asserted on the first paint: the queries have to land
    // before "nothing rendered" means "nothing is wrong" rather than "pending".
    await waitFor(async () => expect(await fetched()).toBe(true))
    expect(container).toBeEmptyDOMElement()
    expect(screen.queryByText(/healthy/i)).toBeNull()
  })

  it('says a cluster has no quorum, even with every node connected and no alerts', async () => {
    // The state that made this footer lie on real hardware (doc 12 check 12):
    // quorum lost, so /etc/pve is read-only and every write fails, while every
    // read answers perfectly. No node is unreachable and nothing is firing.
    state.alerts = []
    state.hosts = [{ status: 'connected', quorate: false },
                   { status: 'connected', quorate: false }]
    const { container } = wrap(<HealthFooter />)
    await waitFor(() =>
      expect(screen.getByText(/cluster has no quorum/i)).toBeInTheDocument())
    expect(screen.getByText(/writes will fail until quorum returns/i)).toBeInTheDocument()
    expect(container.querySelector('.bg-red')).not.toBeNull()
    expect(screen.queryByText(/all systems healthy/i)).toBeNull()
  })

  it('treats a null quorate as standalone, not as quorum loss', async () => {
    // NULL is a standalone host or one not yet polled. Reading either as quorum
    // loss would put a red warning under every standalone install.
    state.alerts = []
    state.hosts = [{ status: 'connected', quorate: null },
                   { status: 'connected' }]
    const { container } = wrap(<HealthFooter />)
    await waitFor(async () => expect(await fetched()).toBe(true))
    expect(container).toBeEmptyDOMElement()
    expect(screen.queryByText(/quorum/i)).toBeNull()
  })

  it('counts firing alerts and turns the dot red', async () => {
    state.alerts = [
      { id: 1, state: 'firing', severity: 'critical', message: 'host-02 CPU' },
      { id: 2, state: 'firing', severity: 'warning', message: 'redis memory' },
    ]
    state.hosts = [{ status: 'connected' }]
    const { container } = wrap(<HealthFooter />)
    await waitFor(() => expect(screen.getByText(/1 node · 2 alerts/i)).toBeInTheDocument())
    expect(screen.getByText(/2 alerts firing/i)).toBeInTheDocument()
    expect(container.querySelector('.bg-red')).not.toBeNull()
  })

  it('reports an unreachable node even with no alerts', async () => {
    state.alerts = []
    state.hosts = [{ status: 'connected' }, { status: 'unreachable' }]
    wrap(<HealthFooter />)
    await waitFor(() => expect(screen.getByText(/1 node unreachable/i)).toBeInTheDocument())
  })

  it('never claims "healthy" when a query errors, reports status unknown instead', async () => {
    state.error = true
    const { container } = wrap(<HealthFooter />)
    await waitFor(() => expect(screen.getByText(/status unknown/i)).toBeInTheDocument())
    expect(screen.queryByText(/all systems healthy/i)).not.toBeInTheDocument()
    expect(container.querySelector('.bg-green')).toBeNull()
    state.error = false
  })
})

// The 64px icon rail has ~32px of content width; the two-line body's own
// words ("systems", "healthy") are each wider than that at 12px Inter, so
// there is no room for any of it here: see CRITICAL 1 of the phase-fix
// report this covers. Collapsed drops to the dot alone.
describe('HealthFooter collapsed', () => {
  it('renders nothing collapsed either when nothing is wrong', async () => {
    state.alerts = []
    state.hosts = [{ status: 'connected' }, { status: 'connected' }, { status: 'connected' }]
    const { container } = wrap(<HealthFooter collapsed />)
    await waitFor(async () => expect(await fetched()).toBe(true))
    expect(container).toBeEmptyDOMElement()
  })

  it('renders the dot alone, with the headline as the link\'s accessible name', async () => {
    // The unhealthy case is what the rail has to fit: dot only, headline as the
    // accessible name, because a truncated fragment of it is worse than nothing.
    state.alerts = []
    state.hosts = [{ status: 'connected' }, { status: 'unreachable' }]
    const { container } = wrap(<HealthFooter collapsed />)
    const link = await screen.findByRole('link', { name: '1 node unreachable' })
    expect(link.textContent).toBe('')
    expect(container.querySelector('.bg-red')).not.toBeNull()
  })

  it('turns the dot red and renames the link when alerts are firing', async () => {
    state.alerts = [
      { id: 1, state: 'firing', severity: 'critical', message: 'host-02 CPU' },
    ]
    state.hosts = [{ status: 'connected' }]
    const { container } = wrap(<HealthFooter collapsed />)
    const link = await screen.findByRole('link', { name: '1 alert firing' })
    expect(link.textContent).toBe('')
    expect(container.querySelector('.bg-red')).not.toBeNull()
  })

  it('still says status unknown, collapsed, when a query errors', async () => {
    state.error = true
    wrap(<HealthFooter collapsed />)
    const link = await screen.findByRole('link', { name: 'Status unknown' })
    expect(link.textContent).toBe('')
    state.error = false
  })

  it('repeats the headline in a Radix tooltip on focus', async () => {
    // Unhealthy, because that is the only state the collapsed rail renders now,
    // and the tooltip is the only place the headline is readable there.
    state.alerts = []
    state.hosts = [{ status: 'unreachable' }]
    wrap(<HealthFooter collapsed />)
    const link = await screen.findByRole('link', { name: '1 node unreachable' })
    fireEvent.focus(link)
    const tooltip = await screen.findByRole('tooltip')
    expect(tooltip).toHaveTextContent('1 node unreachable')
  })
})
