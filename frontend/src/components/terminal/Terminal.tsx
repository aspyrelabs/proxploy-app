import { ClipboardAddon } from '@xterm/addon-clipboard'
import { FitAddon } from '@xterm/addon-fit'
import { SearchAddon } from '@xterm/addon-search'
import { SerializeAddon } from '@xterm/addon-serialize'
import { WebLinksAddon } from '@xterm/addon-web-links'
import { WebglAddon } from '@xterm/addon-webgl'
import { Terminal as XTerm } from '@xterm/xterm'
// xterm ships its layout as a stylesheet, not inline styles, and nothing is
// positioned without it. Colocated here rather than in main.tsx so it travels
// with the only component that opens a terminal.
//
// The rule that made this a bug report rather than a cosmetic gap is
// `.xterm-helper-textarea`, which the stylesheet parks at `left: -9999em`,
// `opacity: 0`. That textarea is where keystrokes actually land, so without
// the stylesheet it is a visible, in-flow textarea and what the operator types
// renders OUTSIDE the black box. `.xterm` also stops being `position:
// relative`, so the absolutely positioned viewport and the render canvases,
// which are meant to overlay, stack in normal flow instead.
import '@xterm/xterm/css/xterm.css'
import { useEffect, useRef } from 'react'
import { CONSOLE_THEMES, readConsolePrefs } from '../../lib/console-prefs'

export type TerminalDropInfo = { fatal: boolean }

export function Terminal({ wsUrl, onDrop, bare = false }:
  { wsUrl: string; onDrop?: (info: TerminalDropInfo) => void
    /** Full bleed: no border, no rounding, no inset, no fixed height, for the
     *  node shell, which owns a window of its own and should read like a
     *  terminal on the operator's own machine. The app console is an in-page
     *  tab and keeps the card chrome. */
    bare?: boolean }) {
  const box = useRef<HTMLDivElement>(null)
  // Read once, at mount. An already-open console keeps the settings it started
  // with: the node shell is a fresh popup every time and the app console tab
  // remounts on navigation, so there is no case where a stale console is the
  // only one an operator has.
  const prefs = readConsolePrefs()
  const theme = CONSOLE_THEMES[prefs.theme].theme

  useEffect(() => {
    if (!box.current) return
    const term = new XTerm({ theme, fontFamily: 'JetBrains Mono, monospace',
                             fontSize: prefs.fontSize })
    const fit = new FitAddon()
    term.loadAddon(fit)
    // Addons that cannot fail: no context to acquire, no work at load time.
    // NOT addon-attach, deliberately. It pipes the socket straight into the
    // terminal, and this socket is not raw: the bridge sends JSON control
    // frames for `exit` (carrying the code and the actionable error the
    // reconnect logic reads). Attaching would print those frames as visible
    // text and take the drop handling with them.
    term.loadAddon(new ClipboardAddon())
    term.loadAddon(new SearchAddon())
    term.loadAddon(new SerializeAddon())
    // A shell prints URLs constantly (apt, installers, community-scripts).
    // Opened with noopener + noreferrer: the destination has no handle on this
    // window and is not told the URL it came from, which carries host ids.
    term.loadAddon(new WebLinksAddon((event, uri) => {
      event.preventDefault()
      window.open(uri, '_blank', 'noopener,noreferrer')
    }))
    term.open(box.current)

    // WebGL last, and guarded twice. Its constructor throws where there is no
    // context (a locked-down browser, a VM with no GPU, and jsdom in the
    // tests), and a live context can be lost afterwards, at which point the
    // addon must be disposed or the canvas stays blank. Either way the canvas
    // renderer takes over: a slower console beats no console.
    let webgl: WebglAddon | null = null
    try {
      webgl = new WebglAddon()
      webgl.onContextLoss(() => { webgl?.dispose(); webgl = null })
      term.loadAddon(webgl)
    } catch {
      webgl = null
    }
    fit.fit()

    if (typeof WebSocket === 'undefined') return  // jsdom without a WS stub
    let unmounting = false
    // Set when an exit control frame carries an `error` (the actionable
    // PtyBridge/PVE-rejection message, e.g. the token-vs-termproxy PVE
    // limitation the plan documents), that drop is terminal, not transient,
    // so the caller should stop retrying instead of burning its reconnect
    // budget on a connection that will fail the same way every time.
    let fatal = false
    let ws: WebSocket | null = null

    // wsUrl carries a single-use ticket: a second socket opened against it
    // is refused by the server, and that refusal used to tear down the
    // first (working) socket as if it had dropped. StrictMode replays this
    // effect (mount, cleanup, mount) synchronously in dev to surface exactly
    // this kind of non-idempotent effect, so opening the socket is deferred
    // a tick and cancelled below; the cleanup of the first, throwaway
    // invocation runs before that tick and cancels it, so only the
    // surviving invocation ever redeems the ticket.
    const openTimer = setTimeout(() => {
      ws = new WebSocket(wsUrl)
      ws.onopen = () => {
        ws!.send(JSON.stringify({ type: 'resize', cols: term.cols, rows: term.rows }))
      }
      ws.onmessage = (e) => {
        let data = e.data as string
        try {
          const control = JSON.parse(data)
          if (control?.type === 'exit') {
            term.write(`\r\n[session ended: ${control.code}${control.error ? ': ' + control.error : ''}]\r\n`)
            if (control.error) fatal = true
            return
          }
        } catch { /* not a control frame, raw terminal text */ }
        term.write(data)
      }
      // The bridge (backend PtyBridge/ConsoleProxy) or the upstream Proxmox
      // socket can drop independently of anything the user did, doc 06's
      // "Reconnect = new ticket" / DoD "survive reconnect" means the CALLER
      // re-mints a ticket and remounts with a fresh wsUrl; this component only
      // has to tell them a drop happened, and not confuse its own teardown
      // (which also closes the socket) for one.
      ws.onclose = () => { if (!unmounting) onDrop?.({ fatal }) }
    }, 0)
    const sub = term.onData((data) => ws?.readyState === WebSocket.OPEN && ws.send(data))
    const resizeSub = term.onResize(({ cols, rows }) => {
      if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'resize', cols, rows }))
    })

    const onWindowResize = () => fit.fit()
    window.addEventListener('resize', onWindowResize)
    // A window resize is not the only thing that changes this box. The console
    // sits inside the app shell, and collapsing the sidebar re-lays it out with
    // no window event, after which xterm is still using the column count it
    // computed at the old width and the text wraps where the box no longer
    // ends. Same guard and same shape as charts/TimeChart.tsx, which watches
    // its own element for the same reason.
    const ro = typeof ResizeObserver === 'undefined' ? null
      : new ResizeObserver(() => fit.fit())
    if (ro && box.current) ro.observe(box.current)

    return () => {
      unmounting = true
      clearTimeout(openTimer)
      window.removeEventListener('resize', onWindowResize)
      ro?.disconnect()
      sub.dispose()
      resizeSub.dispose()
      webgl?.dispose()
      ws?.close()
      term.dispose()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- prefs are read
    // once at mount on purpose (see above); re-running on them would tear down
    // a live session and its single-use ticket.
  }, [wsUrl])

  // The element carries the terminal's own background, not a page token: in
  // bare mode it fills the window, and any other colour shows as a strip
  // before xterm paints.
  return <div ref={box} style={{ background: theme.background }}
    className={bare ? 'h-full' : 'h-[420px] rounded-ctl border border-line-soft p-2'} />
}
