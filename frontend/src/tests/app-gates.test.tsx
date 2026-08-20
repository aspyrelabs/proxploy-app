import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

let features: Record<string, boolean> = { 'apps.lifecycle': true, 'apps.open_ui': true }
let capabilities: Record<string, boolean> | null = { lifecycle: true, console: true }

vi.mock('../api/client', () => ({
  api: vi.fn((path: string) => {
    if (path === '/entitlements') {
      return Promise.resolve({ tier: 'builtin', grace: null, clock_skew: false, features })
    }
    if (path.startsWith('/hosts')) {
      return Promise.resolve([{ id: 1, name: 'pve1', capabilities }])
    }
    return Promise.resolve(null)
  }),
  ApiError: class extends Error {},
}))

import { useAppActionGates } from '../api/app-gates'

const wrap = ({ children }: { children: React.ReactNode }) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
}

describe('useAppActionGates', () => {
  it('withholds nothing once both fetches land and both say yes', async () => {
    features = { 'apps.lifecycle': true, 'apps.open_ui': true }
    capabilities = { lifecycle: true, console: true }
    const { result } = renderHook(() => useAppActionGates(1), { wrapper: wrap })
    await waitFor(() => expect(result.current.lifecycle.denied).toBe(false))
    expect(result.current.console.denied).toBe(false)
    expect(result.current.openUi.denied).toBe(false)
    expect(result.current.lifecycle.reason).toBeUndefined()
  })

  it('withholds nothing while the fetches are still in flight', () => {
    // Gating on an unresolved entitlement would grey out every action for the
    // whole first fetch, for every plan, not only the ones that lack the flag.
    // Only an answer that has actually arrived may withhold anything.
    const { result } = renderHook(() => useAppActionGates(1), { wrapper: wrap })
    expect(result.current.lifecycle.denied).toBe(false)
    expect(result.current.console.denied).toBe(false)
  })

  it('explains a missing lifecycle token rather than only greying out', async () => {
    features = { 'apps.lifecycle': true, 'apps.open_ui': true }
    capabilities = { lifecycle: false, console: true }
    const { result } = renderHook(() => useAppActionGates(1), { wrapper: wrap })
    await waitFor(() => expect(result.current.lifecycle.denied).toBe(true))
    expect(result.current.lifecycle.reason).toMatch(/Settings/)
    expect(result.current.console.denied).toBe(false)
  })

  it('reports a plan that does not include an action', async () => {
    features = { 'apps.lifecycle': false, 'apps.open_ui': false }
    capabilities = { lifecycle: true, console: true }
    const { result } = renderHook(() => useAppActionGates(1), { wrapper: wrap })
    await waitFor(() => expect(result.current.lifecycle.denied).toBe(true))
    expect(result.current.lifecycle.reason).toBe('Not included in your plan')
    expect(result.current.openUi.denied).toBe(true)
  })
})
