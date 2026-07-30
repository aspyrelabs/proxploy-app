import { render, waitFor, screen } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { Terminal } from '../components/terminal/Terminal'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('../api/client', () => ({ api: vi.fn().mockResolvedValue({ ticket: 'tix', expires_at: '2026-01-01T00:00:00Z' }) }))

class FakeWebSocket {
  static instances: FakeWebSocket[] = []
  onopen: (() => void) | null = null
  onmessage: ((e: { data: string }) => void) | null = null
  onclose: (() => void) | null = null
  sent: string[] = []
  url: string
  constructor(url: string) { this.url = url; FakeWebSocket.instances.push(this) }
  send(data: string) { this.sent.push(data) }
  close() { this.onclose?.() }
}

beforeEach(() => {
  FakeWebSocket.instances = []
  // @ts-expect-error test stub
  global.WebSocket = FakeWebSocket
})

describe('Terminal', () => {
  it('opens a websocket at the given url and writes incoming frames', async () => {
    render(<Terminal wsUrl="ws://test/console" />)
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1))
    const ws = FakeWebSocket.instances[0]
    expect(ws.url).toBe('ws://test/console')
    ws.onopen?.()
    ws.onmessage?.({ data: 'hello\n' })
    // no throw = xterm.js accepted the write; deeper terminal-content
    // assertions would need a headless-canvas shim this suite doesn't have.
  })

  it('sends a resize control frame on mount (initial fit)', async () => {
    render(<Terminal wsUrl="ws://test/console" />)
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1))
    const ws = FakeWebSocket.instances[0]
    ws.onopen?.()
    await waitFor(() => expect(ws.sent.some(s => s.includes('"type":"resize"'))).toBe(true))
  })

  it('calls onDrop when the socket closes on its own, not on unmount', async () => {
    const onDrop = vi.fn()
    const { unmount } = render(<Terminal wsUrl="ws://test/console" onDrop={onDrop} />)
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1))
    FakeWebSocket.instances[0].onclose?.()
    expect(onDrop).toHaveBeenCalledTimes(1)
    expect(onDrop).toHaveBeenCalledWith({ fatal: false })
    onDrop.mockClear()
    unmount()  // cleanup also calls ws.close(), which must NOT re-fire onDrop
    expect(onDrop).not.toHaveBeenCalled()
  })

  it('renders the PtyBridge error message from an exit control frame, and reports fatal:true', async () => {
    const onDrop = vi.fn()
    render(<Terminal wsUrl="ws://test/console" onDrop={onDrop} />)
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1))
    const ws = FakeWebSocket.instances[0]
    ws.onopen?.()
    // The "OK" literal must never reach here (finding #7) -- only a real
    // structured exit frame with the actionable PVE-rejection message
    // (finding #6, the whole point of the spike-correction mitigation).
    ws.onmessage?.({ data: JSON.stringify({ type: 'exit', code: 1, error: 'termproxy rejected the handshake' }) })
    ws.onclose?.()
    expect(onDrop).toHaveBeenCalledWith({ fatal: true })
  })
})

describe('AppConsole', () => {
  it('requests a ticket on mount and opens the terminal at the ticketed url', async () => {
    const { AppConsole } = await import('../routes/apps')
    const qc = new QueryClient()
    render(
      <QueryClientProvider client={qc}>
        <AppConsole appId={42} />
      </QueryClientProvider>,
    )
    await waitFor(() => expect(FakeWebSocket.instances.length).toBe(1))
    expect(FakeWebSocket.instances[0].url).toContain('/apps/42/console/ws?ticket=tix')
  })
})

describe('AppLogs', () => {
  it('renders the logs tail in a static TerminalPanel', async () => {
    const apiMock = vi.mocked((await import('../api/client')).api)
    apiMock.mockResolvedValue([{ stream: 'stdout', message: 'app started' }])
    const { AppLogs } = await import('../routes/apps')
    const qc = new QueryClient()
    render(<QueryClientProvider client={qc}><AppLogs appId={42} /></QueryClientProvider>)
    await waitFor(() => expect(screen.getByText('app started')).toBeInTheDocument())
  })

  it('shows an honest empty state instead of polling a dead endpoint forever', async () => {
    // Regression test for finding #1: the backend has no CT log-tailing
    // channel yet (GET /apps/{id}/logs answers 501), and the old `data ?? []`
    // fallback silently swallowed that error into a permanently-empty panel
    // while polling every 5s forever.
    const apiMock = vi.mocked((await import('../api/client')).api)
    apiMock.mockRejectedValueOnce(new Error('501'))
    const callsBefore = apiMock.mock.calls.length
    const { AppLogs } = await import('../routes/apps')
    const qc = new QueryClient()
    render(<QueryClientProvider client={qc}><AppLogs appId={42} /></QueryClientProvider>)
    await waitFor(() => expect(screen.getByText(/not available/i)).toBeInTheDocument())
    // Only the one call -- retry:false and the refetchInterval-on-error guard
    // both mean this must not still be polling.
    expect(apiMock.mock.calls.length - callsBefore).toBe(1)
  })
})
