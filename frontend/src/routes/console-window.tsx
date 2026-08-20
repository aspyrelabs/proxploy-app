import { useEffect } from 'react'
import { createRoute, useParams } from '@tanstack/react-router'
import { ApiError } from '../api/client'
import type { ConsoleKind } from '../api/consoles'
import { consoleWsPath, consoleWsUrl, useReconnectingTicket } from '../api/consoles'
import { Terminal } from '../components/terminal/Terminal'
import { rootRoute } from './shell'

const KINDS: readonly ConsoleKind[] = ['host', 'app', 'vm']

/** What the thing on the other end is called, for the failure copy. Telling
 *  someone to enable node shells when they clicked Console on an app is worse
 *  than saying nothing. */
const NOUN: Record<ConsoleKind, string> = {
  host: 'node shell', app: 'app console', vm: 'VM console',
}

/** Any console in a window of its own: node shell, app console, VM console.
 *
 *  One route rather than three near-copies. useReconnectingTicket and
 *  consoleWsUrl are already keyed on the kind, so the only things that branch
 *  are which renderer to mount (VNC for a VM, xterm for the other two) and the
 *  noun the failure copy uses.
 *
 *  Deliberately a child of rootRoute rather than shellRoute: this is opened
 *  with window.open, and a console in a popup does not want the sidebar and
 *  topbar chrome around it.
 *
 *  Every way this can fail is spelled out on screen. The control that opens
 *  this window used to be a grey button with a tooltip, and "nothing happened"
 *  is precisely the complaint that removed it; a blank popup would be the same
 *  bug in a new place.
 */

/** Turn a ticket-mint failure into something an operator can act on.
 *
 *  The three that actually happen: the per-host opt-in is off (409 from
 *  api/consoles.py), the entitlement is missing (403), or Proxmox itself
 *  refuses because the API token does not hold Sys.Console, which arrives as
 *  a 409 carrying the ProxmoxError text and is otherwise indistinguishable
 *  from the opt-in case unless we read it.
 */
export function shellFailure(e: unknown, kind: ConsoleKind = 'host'):
    { title: string; note: string } {
  const status = e instanceof ApiError ? e.status : 0
  const raw = e instanceof ApiError
    ? typeof e.body === 'string' ? e.body : JSON.stringify(e.body ?? '')
    : String(e)

  if (status === 403) {
    return kind === 'host' ? {
      title: 'Node shells are not in this plan',
      note: 'Opening a shell on the node itself needs the Pro tier. Every '
          + 'other action on the host page works without it.',
    } : {
      title: `The ${NOUN[kind]} is not in this plan`,
      note: `Opening a ${NOUN[kind]} needs the Pro tier. Every other action `
          + 'on the page you came from works without it.',
    }
  }
  if (/not enabled for this host/i.test(raw)) {
    return {
      title: 'Node shells are not enabled for this host',
      note: 'Proxploy keeps a second, deliberate switch on top of your role: '
          + 'a root shell on the hypervisor is not something to inherit by '
          + 'accident. Turn it on in Settings → Hosts, then reopen this window.',
    }
  }
  if (status === 409 || status === 502) {
    return {
      title: 'Proxmox refused to open a shell',
      note: 'Opening a node shell needs the API token to hold Sys.Console on '
          + `/nodes. An audit-only token cannot do it. Proxmox said: ${raw}`,
    }
  }
  if (status === 401) {
    return { title: 'Not signed in', note: 'Sign in to Proxploy in the main window, then reopen this one.' }
  }
  return { title: `Could not open a ${NOUN[kind]}`, note: raw || 'No reason was given.' }
}

/** The address of the vendored noVNC application, configured for one VM
 *  console session.
 *
 *  We render noVNC's own UI rather than a wrapper of our own, because the
 *  sidebar it ships with (quality, compression, scaling, view only, clipboard,
 *  the on-screen keyboard, Ctrl+Alt+Del, fullscreen) is the console people
 *  already know from Proxmox, and rebuilding a worse version of it was not
 *  worth the code. It lives in public/novnc, see its VENDORED.md.
 *
 *  Only `path` and `password` change per session. Everything else here is
 *  fixed, and each one is fixed for a reason:
 *
 *  - `host` and `port` are empty on purpose. That is the switch that puts
 *    noVNC on the branch of app/ui.js's connect() which builds the socket URL
 *    with `new URL(path, location.href)` instead of dialling a VNC host
 *    itself. Our websocket is on our own origin behind our own auth, so there
 *    is no host for it to dial.
 *  - `path` is rooted at the site, not relative, because that `new URL` call
 *    resolves against /novnc/vnc.html; a relative path would land on
 *    /novnc/api/v1/... and hit the SPA fallback instead of the socket.
 *  - `encrypt` is inert on this branch (the protocol is taken from
 *    location.protocol) but is sent anyway so the control shows the truth and
 *    is greyed out rather than inviting a toggle that does nothing.
 *  - `reconnect` is off, and this is the one that would cost somebody an
 *    evening. Console tickets are single use: services/consoletickets.py's
 *    redeem_ticket stamps redeemed_at under an UPDATE ... WHERE redeemed_at
 *    IS NULL, so the second redemption of a ticket gets nothing back and the
 *    socket is closed 4401. An automatic reconnect would therefore never
 *    reconnect; it would spend five seconds on a countdown and then report a
 *    refused ticket, which reads as the console being broken rather than as
 *    the session having ended. Reopening the window mints a fresh ticket and
 *    is the only thing that can work.
 *
 *  The password goes in the fragment rather than the query string, which is
 *  what noVNC's own webutil.js recommends and getConfigVar supports: a
 *  fragment is not sent to the server, so a one-shot VNC password does not
 *  land in our access log on the way to a page we serve ourselves.
 */
function vncAppUrl(id: number, ticket: string, password?: string): string {
  const q = new URLSearchParams({
    host: '', port: '',
    encrypt: String(location.protocol === 'https:'),
    path: consoleWsPath('vm', id, ticket),
    autoconnect: 'true',
    reconnect: 'false',
  })
  const hash = password ? `#password=${encodeURIComponent(password)}` : ''
  return `/novnc/vnc.html?${q}${hash}`
}

function Failure({ title, note }: { title: string; note: string }) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-ink p-8">
      <div className="max-w-md rounded-card border border-line-soft bg-panel p-6">
        <h1 className="mb-2 font-display text-[16px] font-semibold text-text">{title}</h1>
        <p className="text-[13px] leading-relaxed text-text-2">{note}</p>
      </div>
    </div>
  )
}

export function ConsoleWindow() {
  const { kind, id: rawId } = useParams({ strict: false }) as
    { kind: string; id: string }
  const id = Number(rawId)
  const valid = (KINDS as readonly string[]).includes(kind)
  const target = (valid ? kind : 'host') as ConsoleKind
  const { ticket, failed, start, reconnect, giveUp } = useReconnectingTicket(target, id)

  // Hooks run unconditionally above; the bad-kind bail is below them, because
  // a URL somebody typed must not change how many hooks this renders.
  useEffect(() => { if (valid) start() }, [start, valid])

  if (!valid) {
    return <Failure title="No such console"
      note={`This window opens a console for ${KINDS.join(', ')}. The address `
          + `asked for "${kind}", which is none of them.`} />
  }
  if (ticket.isError) {
    const { title, note } = shellFailure(ticket.error, target)
    return <Failure title={title} note={note} />
  }
  if (failed) {
    return <Failure title="Console connection lost"
      note="Gave up after repeated attempts. Close this window and open it again." />
  }
  if (!ticket.data) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-ink">
        <span className="text-[13px] text-text-3">Opening a {NOUN[target]}…</span>
      </div>
    )
  }
  // Full bleed: no padding, no chrome, the console's own background edge to
  // edge. This window has no sidebar or topbar for the same reason, and a
  // bordered box floating inside it reads as an app panel rather than as a
  // console on the machine.
  return (
    <div className="h-screen">
      {target === 'vm'
        // noVNC reports its own failures inside its own UI, so unlike the
        // terminal there is no onDrop to route back into <Failure>: the
        // status bar and the disconnect screen in the iframe are the ones
        // that know what happened.
        ? <iframe key={ticket.data.ticket} title="VM console"
            src={vncAppUrl(id, ticket.data.ticket, ticket.data.password)}
            // noVNC's own fullscreen button and its clipboard panel are the
            // point of using its UI, and both are permission-gated inside an
            // iframe. Without this allow list they are present and dead.
            allow="fullscreen; clipboard-read; clipboard-write"
            className="block h-full w-full border-0" />
        : <Terminal key={ticket.data.ticket} bare
            wsUrl={consoleWsUrl(target, id, ticket.data.ticket)}
            onDrop={({ fatal }) => (fatal ? giveUp() : reconnect())} />}
    </div>
  )
}

export const consoleWindowRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/shell/$kind/$id',
  component: ConsoleWindow,
})
