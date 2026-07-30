import { render, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const rfbInstances: any[] = []
// NOTE: the installed @novnc/novnc@1.7.0 package's package.json "exports"
// field only maps the root specifier "." -> "./core/rfb.js" — there is no
// "./core/rfb" subpath export, so `@novnc/novnc/core/rfb` fails to resolve
// under Vite/Node's ESM resolver (verified: "is not exported under the
// conditions" error). The real import is the bare `@novnc/novnc` specifier;
// mock that instead of the brief's assumed deep import path.
vi.mock('@novnc/novnc', () => ({
  default: class FakeRFB {
    target: HTMLElement
    url: string
    addEventListener = vi.fn()
    disconnect = vi.fn()
    sendCtrlAltDel = vi.fn()
    constructor(target: HTMLElement, url: string) {
      this.target = target
      this.url = url
      rfbInstances.push(this)
    }
  },
}))

// Tests share one module registry within this file (vitest isolates per
// file, not per test) — reset the instances list so each test only sees
// the RFB it constructed, mirroring terminal.test.tsx's FakeWebSocket reset.
beforeEach(() => { rfbInstances.length = 0 })

describe('VncConsole', () => {
  it('constructs an RFB instance against the given websocket url', async () => {
    const { VncConsole } = await import('../components/console/VncConsole')
    render(<VncConsole wsUrl="wss://test/vnc" />)
    await waitFor(() => expect(rfbInstances).toHaveLength(1))
    expect(rfbInstances[0].url).toBe('wss://test/vnc')
  })

  it('disconnects the RFB session on unmount', async () => {
    const { VncConsole } = await import('../components/console/VncConsole')
    const { unmount } = render(<VncConsole wsUrl="wss://test/vnc" />)
    await waitFor(() => expect(rfbInstances).toHaveLength(1))
    unmount()
    expect(rfbInstances[0].disconnect).toHaveBeenCalled()
  })

  it('calls onDisconnect when RFB fires its own disconnect event (not on unmount)', async () => {
    const onDisconnect = vi.fn()
    const { VncConsole } = await import('../components/console/VncConsole')
    const { unmount } = render(<VncConsole wsUrl="wss://test/vnc" onDisconnect={onDisconnect} />)
    await waitFor(() => expect(rfbInstances).toHaveLength(1))
    const rfb = rfbInstances[0]
    // addEventListener is a vi.fn() mock — grab the handler it was registered
    // with and invoke it directly, exactly as the real RFB would on a drop.
    const [, handler] = rfb.addEventListener.mock.calls.find((c: any[]) => c[0] === 'disconnect')
    handler()
    expect(onDisconnect).toHaveBeenCalledTimes(1)
    onDisconnect.mockClear()
    unmount()
    expect(onDisconnect).not.toHaveBeenCalled()
  })
})
