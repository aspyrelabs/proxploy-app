/** Every console opens in a window of its own, the way the node shell always
 *  has. A console is a working surface you keep beside the page, not a place
 *  you navigate to and lose by clicking a tab. */
import { describe, expect, it, vi } from 'vitest'
import { consoleWindowName, openConsoleWindow } from '../lib/console-window'

describe('opening a console window', () => {
  it('names the window per target, so a second click focuses the first one', () => {
    // Without a stable name every click opens ANOTHER window, and each one
    // redeems its own single-use ticket and starts its own PTY against one
    // guest. The name is what makes removing the embedded tab safe.
    expect(consoleWindowName('vm', 7)).toBe('proxploy-console-vm-7')
    expect(consoleWindowName('vm', 7)).toBe(consoleWindowName('vm', 7))
    expect(consoleWindowName('app', 7)).not.toBe(consoleWindowName('vm', 7))
  })

  it('opens the shared console route for each kind', () => {
    const open = vi.fn()
    vi.stubGlobal('open', open)
    openConsoleWindow('host', 3)
    openConsoleWindow('app', 4)
    openConsoleWindow('vm', 5)
    expect(open.mock.calls.map((c) => c[0]))
      .toEqual(['/shell/host/3', '/shell/app/4', '/shell/vm/5'])
    expect(open.mock.calls.map((c) => c[1]))
      .toEqual(['proxploy-console-host-3', 'proxploy-console-app-4',
                'proxploy-console-vm-5'])
    // noopener/noreferrer: the console window must not get a handle on the app
    // window through window.opener.
    for (const call of open.mock.calls) {
      expect(call[2]).toContain('noopener')
      expect(call[2]).toContain('noreferrer')
    }
    vi.unstubAllGlobals()
  })
})

describe('console window size', () => {
  it('gives a VM console more room than a terminal', () => {
    // A terminal is text. A VM console is a desktop arriving at whatever
    // resolution the guest booted at, and a 1080p guest in a terminal-sized
    // window is scaled or scrolling before the operator touches anything.
    const open = vi.fn()
    vi.stubGlobal('open', open)
    openConsoleWindow('host', 1)
    openConsoleWindow('vm', 1)
    const [term, vnc] = open.mock.calls.map((c) => String(c[2]))
    expect(term).toContain('width=1040')
    expect(vnc).toContain('width=1280')
    expect(vnc).toContain('height=800')
    vi.unstubAllGlobals()
  })
})
