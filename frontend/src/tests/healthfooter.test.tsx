import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
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
// matching cluster.test.tsx / activity.test.tsx.
vi.mock('@tanstack/react-router', async (orig) => ({
  ...(await orig() as object),
  Link: ({ children }: { children?: unknown }) => <a>{children as never}</a>,
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

  it('never claims "healthy" when a query errors — reports status unknown instead', async () => {
    state.error = true
    const { container } = wrap(<HealthFooter />)
    await waitFor(() => expect(screen.getByText(/status unknown/i)).toBeInTheDocument())
    expect(screen.queryByText(/all systems healthy/i)).not.toBeInTheDocument()
    expect(container.querySelector('.bg-green')).toBeNull()
    state.error = false
  })
})
