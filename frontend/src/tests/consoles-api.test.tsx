import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from '../api/client'
import { useConsoleTicket, useReconnectingTicket } from '../api/consoles'

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

describe('useReconnectingTicket', () => {
  afterEach(() => vi.useRealTimers())

  it('caps reconnect attempts at 3 with backoff, then reports failed instead of retrying forever', async () => {
    // Regression test for finding #5: on a host affected by the plan's
    // documented PVE-version limitation, an uncapped reconnect loop spins
    // forever -- real ticket/audit rows and real termproxy calls, every time.
    vi.mocked(api).mockResolvedValue({ ticket: 'tix', expires_at: '2026-01-01T00:00:00Z' })
    vi.useFakeTimers()
    const { result } = renderHook(() => useReconnectingTicket('app', 42), { wrapper })

    await act(async () => { result.current.start() })
    expect(result.current.failed).toBe(false)

    // Three reconnects, each with its own backoff delay -- all within the cap.
    for (let i = 0; i < 3; i++) {
      act(() => { result.current.reconnect() })
      await act(async () => { await vi.advanceTimersByTimeAsync(5000) })
    }
    expect(result.current.failed).toBe(false)

    // The 4th reconnect exceeds MAX_RECONNECT_ATTEMPTS -- no more timers, no
    // more ticket mints, straight to the cap-reached state.
    const callsBefore = vi.mocked(api).mock.calls.length
    act(() => { result.current.reconnect() })
    expect(result.current.failed).toBe(true)
    expect(vi.mocked(api).mock.calls.length).toBe(callsBefore)
  })

  it('giveUp() short-circuits straight to failed regardless of attempt count', () => {
    // Regression test for finding #6: a terminal PtyBridge error (surfaced by
    // Terminal.tsx as fatal:true) must not be treated as just another
    // transient drop worth retrying -- it goes straight to the cap-reached
    // message so the user can actually read the error before anything
    // remounts over it.
    vi.mocked(api).mockResolvedValue({ ticket: 'tix', expires_at: '2026-01-01T00:00:00Z' })
    const { result } = renderHook(() => useReconnectingTicket('app', 42), { wrapper })
    expect(result.current.failed).toBe(false)
    act(() => { result.current.giveUp() })
    expect(result.current.failed).toBe(true)
  })

  it('start() resets a prior failed state (e.g. navigating to a different console)', async () => {
    vi.mocked(api).mockResolvedValue({ ticket: 'tix', expires_at: '2026-01-01T00:00:00Z' })
    const { result } = renderHook(() => useReconnectingTicket('app', 42), { wrapper })
    act(() => { result.current.giveUp() })
    expect(result.current.failed).toBe(true)
    await act(async () => { result.current.start() })
    expect(result.current.failed).toBe(false)
  })
})
