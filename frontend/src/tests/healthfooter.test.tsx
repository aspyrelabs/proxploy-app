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

describe('HealthFooter', () => {
  it('reads "All systems healthy" with nodes and no firing alerts', async () => {
    state.alerts = []
    state.hosts = [{ status: 'connected' }, { status: 'connected' },
                   { status: 'connected' }]
    wrap(<HealthFooter />)
    await waitFor(() => expect(screen.getByText(/all systems healthy/i)).toBeInTheDocument())
    expect(screen.getByText(/3 nodes · 0 alerts/i)).toBeInTheDocument()
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
  it('renders the dot alone, with the headline as the link\'s accessible name', async () => {
    state.alerts = []
    state.hosts = [{ status: 'connected' }, { status: 'connected' }, { status: 'connected' }]
    const { container } = wrap(<HealthFooter collapsed />)
    const link = await screen.findByRole('link', { name: 'All systems healthy' })
    // The headline lives only in the accessible name, not as visible text:
    // a truncated fragment of it would be worse than nothing.
    expect(link.textContent).toBe('')
    expect(container.querySelector('.bg-green')).not.toBeNull()
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
    state.alerts = []
    state.hosts = [{ status: 'connected' }]
    wrap(<HealthFooter collapsed />)
    const link = await screen.findByRole('link', { name: 'All systems healthy' })
    fireEvent.focus(link)
    const tooltip = await screen.findByRole('tooltip')
    expect(tooltip).toHaveTextContent('All systems healthy')
  })
})
