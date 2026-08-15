import { FitAddon } from '@xterm/addon-fit'
import { Terminal as XTerm } from '@xterm/xterm'
import { useEffect, useRef } from 'react'

const THEME = {
  background: '#0a0e14', foreground: '#E8EDF4',
  red: '#F26D6D', green: '#3FCF8E', yellow: '#F5B544', blue: '#5B9DF9',
}

export type TerminalDropInfo = { fatal: boolean }

export function Terminal({ wsUrl, onDrop }:
  { wsUrl: string; onDrop?: (info: TerminalDropInfo) => void }) {
  const box = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!box.current) return
    const term = new XTerm({ theme: THEME, fontFamily: 'JetBrains Mono, monospace', fontSize: 12.5 })
    const fit = new FitAddon()
    term.loadAddon(fit)
    term.open(box.current)
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

    return () => {
      unmounting = true
      clearTimeout(openTimer)
      window.removeEventListener('resize', onWindowResize)
      sub.dispose()
      resizeSub.dispose()
      ws?.close()
      term.dispose()
    }
  }, [wsUrl])

  return <div ref={box} style={{ background: '#0a0e14' }} className="h-[420px] rounded-ctl border border-line-soft p-2" />
}
