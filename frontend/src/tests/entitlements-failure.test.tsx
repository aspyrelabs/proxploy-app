import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { api } from '../api/client'
import { useEntitlements } from '../api/hooks'

vi.mock('../api/client', () => ({ api: vi.fn() }))

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
}

describe('useEntitlements', () => {
  it('does not silently hide every gated feature when entitlements fail to load', async () => {
    // has() returning false on error is indistinguishable from "not
    // entitled", so a backend blip reads to the user as a downgrade. It must
    // be possible to tell "no" from "do not know".
    vi.mocked(api).mockRejectedValue(new Error('boom'))
    const { result } = renderHook(() => useEntitlements(), { wrapper })
    await waitFor(() => expect(result.current.unknown).toBe(true))
    expect(result.current.has('storage.manage')).toBe(false)
  })

  it('unknown is false and has() reflects the real flags once entitlements load', async () => {
    vi.mocked(api).mockResolvedValue({
      tier: 'pro', features: { 'storage.manage': true }, grace: null,
    })
    const { result } = renderHook(() => useEntitlements(), { wrapper })
    await waitFor(() => expect(result.current.data).toBeDefined())
    expect(result.current.unknown).toBe(false)
    expect(result.current.has('storage.manage')).toBe(true)
    expect(result.current.has('teams.rbac')).toBe(false)
  })
})
