/**
 * The EventSource must come back on its own.
 *
 * It opened once in an effect with no error handling. EventSource retries a
 * dropped connection by itself, but a retry that lands on a non-2xx (a 502
 * while the backend restarts, a 401 as a session expires) leaves it CLOSED for
 * good, and that tab never sees another event: every update then waits for the
 * 30s refetchInterval, which reads as a slow app rather than a broken stream.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { LiveProvider } from '../components/LiveProvider'

const opened: FakeES[] = []

class FakeES {
  static readonly CLOSED = 2
  static readonly CONNECTING = 0
  readyState = 0
  onerror: (() => void) | null = null
  onopen: (() => void) | null = null
  closed = false
  constructor() { opened.push(this) }
  addEventListener() { /* handlers are not what this file is about */ }
  close() { this.closed = true }
}

beforeEach(() => {
  opened.length = 0
  vi.useFakeTimers()
  vi.stubGlobal('EventSource', FakeES)
})
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

function mount() {
  const qc = new QueryClient()
  return { qc, ...render(
    <QueryClientProvider client={qc}><LiveProvider>{null}</LiveProvider></QueryClientProvider>) }
}

describe('LiveProvider', () => {
  it('reopens the stream after it gives up', async () => {
    mount()
    expect(opened).toHaveLength(1)
    // CLOSED is EventSource having given up, not a blip.
    opened[0].readyState = FakeES.CLOSED
    opened[0].onerror?.()
    await vi.advanceTimersByTimeAsync(1000)
    expect(opened).toHaveLength(2)
  })

  it('leaves a transient drop to EventSource\'s own retry', async () => {
    mount()
    // Still CONNECTING: its own retry is in flight, and opening a second
    // stream here would race two of them against each other.
    opened[0].readyState = FakeES.CONNECTING
    opened[0].onerror?.()
    await vi.advanceTimersByTimeAsync(5000)
    expect(opened).toHaveLength(1)
  })

  it('backs off instead of hammering a server that is down', async () => {
    mount()
    const fail = () => {
      const last = opened[opened.length - 1]
      last.readyState = FakeES.CLOSED
      last.onerror?.()
    }
    fail()
    await vi.advanceTimersByTimeAsync(1000)
    expect(opened).toHaveLength(2)
    fail()
    // Second wait is 2s, so 1s is not yet enough.
    await vi.advanceTimersByTimeAsync(1000)
    expect(opened).toHaveLength(2)
    await vi.advanceTimersByTimeAsync(1000)
    expect(opened).toHaveLength(3)
  })

  it('refetches on reconnect, because SSE has no replay', () => {
    const { qc } = mount()
    // Spied AFTER mount so this counts the reconnect, not the first open.
    const spy = vi.spyOn(qc, 'invalidateQueries')
    opened[0].onopen?.()
    // Synchronous on purpose: waitFor never resolves under fake timers.
    expect(spy).toHaveBeenCalledWith({ queryKey: ['apps'] })
    expect(spy).toHaveBeenCalledWith({ queryKey: ['vms'] })
  })

  it('stops trying once unmounted', async () => {
    const { unmount } = mount()
    opened[0].readyState = FakeES.CLOSED
    opened[0].onerror?.()
    unmount()
    await vi.advanceTimersByTimeAsync(30000)
    expect(opened).toHaveLength(1)
  })
})
