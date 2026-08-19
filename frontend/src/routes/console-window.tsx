import { useEffect } from 'react'
import { createRoute, useParams } from '@tanstack/react-router'
import { ApiError } from '../api/client'
import type { ConsoleKind } from '../api/consoles'
import { consoleWsUrl, useReconnectingTicket } from '../api/consoles'
import { VncConsole } from '../components/console/VncConsole'
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
  const wsUrl = consoleWsUrl(target, id, ticket.data.ticket)
  return (
    <div className="h-screen">
      {target === 'vm'
        ? <VncConsole key={ticket.data.ticket} bare wsUrl={wsUrl}
            onDisconnect={reconnect} />
        : <Terminal key={ticket.data.ticket} bare wsUrl={wsUrl}
            onDrop={({ fatal }) => (fatal ? giveUp() : reconnect())} />}
    </div>
  )
}

export const consoleWindowRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/shell/$kind/$id',
  component: ConsoleWindow,
})
