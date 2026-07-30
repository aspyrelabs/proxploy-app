import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { api } from '../api/client'
import { useConsoleTicket } from '../api/consoles'

vi.mock('../api/client', () => ({ api: vi.fn() }))

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient()
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
}

describe('useConsoleTicket', () => {
  it('POSTs to the app console path for kind=app', async () => {
    vi.mocked(api).mockResolvedValueOnce({ ticket: 't1', expires_at: '2026-01-01T00:00:00Z' })
    const { result } = renderHook(() => useConsoleTicket('app', 42), { wrapper })
    result.current.mutate()
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(api).toHaveBeenCalledWith('/apps/42/console/tickets', { method: 'POST' })
  })

  it('POSTs to the host shell path for kind=host', async () => {
    vi.mocked(api).mockResolvedValueOnce({ ticket: 't2', expires_at: '2026-01-01T00:00:00Z' })
    const { result } = renderHook(() => useConsoleTicket('host', 7), { wrapper })
    result.current.mutate()
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(api).toHaveBeenCalledWith('/hosts/7/shell/tickets', { method: 'POST' })
  })

  it('POSTs to the vm console path for kind=vm', async () => {
    vi.mocked(api).mockResolvedValueOnce({ ticket: 't3', expires_at: '2026-01-01T00:00:00Z' })
    const { result } = renderHook(() => useConsoleTicket('vm', 9), { wrapper })
    result.current.mutate()
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(api).toHaveBeenCalledWith('/vms/9/console/tickets', { method: 'POST' })
  })
})
