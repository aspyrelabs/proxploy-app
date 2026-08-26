import { useMutation } from '@tanstack/react-query'
import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, api, apiErrorDetail } from './client'

/** `password` is the VM console's only: PVE generates a one-connection VNC
 *  password (api/consoles.py) because QEMU's RFB server offers VNC
 *  Authentication and the bridge relays bytes without answering challenges,
 *  so the browser is the only party that can. Absent for host and app
 *  consoles, whose bridge does authenticate upstream itself. */
export type ConsoleTicket = { ticket: string; expires_at: string; password?: string }
export type ConsoleKind = 'app' | 'host' | 'vm'

const PATH: Record<ConsoleKind, (id: number) => string> = {
  app: (id) => `/apps/${id}/console/tickets`,
  host: (id) => `/hosts/${id}/shell/tickets`,
  vm: (id) => `/vms/${id}/console/tickets`,
}

const WS_PATH: Record<ConsoleKind, (id: number, ticket: string) => string> = {
  app: (id, t) => `/apps/${id}/console/ws?ticket=${t}`,
  host: (id, t) => `/hosts/${id}/shell/ws?ticket=${t}`,
  vm: (id, t) => `/vms/${id}/vnc/ws?ticket=${t}`,
}

export function useConsoleTicket(kind: ConsoleKind, id: number) {
  return useMutation({
    mutationFn: () => api<ConsoleTicket>(PATH[kind](id), { method: 'POST' }),
  })
}

/** The websocket path, ticket included, rooted at the site rather than at
 *  whatever page is asking. Split out of consoleWsUrl so the vendored noVNC
 *  app and our own xterm bridge cannot end up describing two different
 *  sockets: noVNC builds its own URL from a path (it does `new URL(path,
 *  location.href)` in app/ui.js), and it is served from /novnc/, so a path
 *  relative to the caller would resolve under /novnc/ and hit nothing. */
export function consoleWsPath(kind: ConsoleKind, id: number, ticket: string): string {
  return `/api/v1${WS_PATH[kind](id, ticket)}`
}

export function consoleWsUrl(kind: ConsoleKind, id: number, ticket: string): string {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${location.host}${consoleWsPath(kind, id, ticket)}`
}

// A console drop with no visible cause (upstream flaked, PVE's own
// termproxy/vncproxy hiccuped) is worth a few automatic retries; a drop we
// already know is fatal (Terminal.tsx surfacing a PtyBridge error frame, 
// e.g. the PVE-version-vs-API-token limitation the plan documents) is not,
// and retrying it just spins real ticket/audit rows against Proxmox forever.
// Shared by all three console call sites (apps.tsx, vms.tsx, cluster.tsx)
// rather than duplicated three times.
const MAX_RECONNECT_ATTEMPTS = 3
const BACKOFF_MS = [1000, 2000, 4000]

/** Why a ticket request failed, in words.
 *
 *  `failed` only ever comes from a WebSocket drop, so it cannot describe a
 *  ticket POST that never succeeded (no socket opened to drop). The
 *  entitlement 403 is checked first because its body carries the reason in
 *  `error` and leaves `detail` generic. */
export function consoleFailure(e: unknown): { title: string; note: string } {
  if (e instanceof ApiError && (e.body as { error?: string } | null)?.error
      === 'entitlement_required') {
    return {
      title: 'Console is not included in your plan',
      note: 'Everything else on this page works without it.',
    }
  }
  return {
    title: 'Could not open the console',
    note: apiErrorDetail(e, 'No reason was given. Reload the page to try again.'),
  }
}


export function useReconnectingTicket(kind: ConsoleKind, id: number) {
  const ticket = useConsoleTicket(kind, id)
  const attempts = useRef(0)
  const [failed, setFailed] = useState(false)
  // The pending backoff timer, and whether this console still wants one.
  //
  // Both are needed, and neither alone is enough. Clearing the timer without
  // the flag still loses the race where the timer fires in the instant before
  // cleanup runs; the flag without the clear leaves a live timer behind for
  // every closed console. A timer that survives either way mints a real
  // Proxmox ticket and writes a `console.open` audit row for a console the
  // user already closed, which is an audit log describing a session that
  // never happened.
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const wanted = useRef(true)

  const stop = useCallback(() => {
    wanted.current = false
    clearTimeout(timer.current)
    timer.current = undefined
  }, [])

  // Unmount is the close signal all three call sites actually have: none of
  // apps.tsx, vms.tsx or nodeshell.tsx has a close button on the console
  // pane, they are left by navigating away (or, for the node shell popup,
  // by closing the window, which takes the whole page with it).
  useEffect(() => {
    wanted.current = true
    return stop
  }, [stop])

  // Fresh console (first open, or the id changed): reset the attempt count
  // and mint a ticket right away. Any backoff timer still pending belongs to
  // the console being replaced, so it goes with it.
  const start = useCallback(() => {
    clearTimeout(timer.current)
    timer.current = undefined
    wanted.current = true
    attempts.current = 0
    setFailed(false)
    ticket.mutate()
    // eslint-disable-next-line react-hooks/exhaustive-deps -- ticket.mutate is a stable ref
  }, [kind, id])

  // A transient drop: retry with backoff up to the cap, then give up for good.
  const reconnect = useCallback(() => {
    if (attempts.current >= MAX_RECONNECT_ATTEMPTS) {
      stop()
      setFailed(true)
      return
    }
    const delay = BACKOFF_MS[attempts.current]
    attempts.current += 1
    clearTimeout(timer.current)
    timer.current = setTimeout(() => {
      timer.current = undefined
      if (!wanted.current) return
      ticket.mutate()
    }, delay)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stop])

  // A drop we already know is terminal (Terminal.tsx saw an error frame),
  // skip straight to the cap-reached message instead of burning attempts.
  const giveUp = useCallback(() => { stop(); setFailed(true) }, [stop])

  return { ticket, failed, start, reconnect, giveUp }
}
