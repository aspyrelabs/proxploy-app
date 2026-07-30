import { render, waitFor } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { Terminal } from '../components/terminal/Terminal'

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
    onDrop.mockClear()
    unmount()  // cleanup also calls ws.close(), which must NOT re-fire onDrop
    expect(onDrop).not.toHaveBeenCalled()
  })
})
