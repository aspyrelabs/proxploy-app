import { useEffect } from 'react'
import { createRoute, useParams } from '@tanstack/react-router'
import { ApiError } from '../api/client'
import { consoleWsUrl, useReconnectingTicket } from '../api/consoles'
import { Terminal } from '../components/terminal/Terminal'
import { rootRoute } from './shell'

/** The node shell in a window of its own.
 *
 *  Deliberately a child of rootRoute rather than shellRoute: this is opened
 *  with window.open from the host page, and a terminal in a popup does not
 *  want the sidebar and topbar chrome around it.
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
 *  refuses because the API token does not hold Sys.Console — which arrives as
 *  a 409 carrying the ProxmoxError text and is otherwise indistinguishable
 *  from the opt-in case unless we read it.
 */
export function shellFailure(e: unknown): { title: string; note: string } {
  const status = e instanceof ApiError ? e.status : 0
  const raw = e instanceof ApiError
    ? typeof e.body === 'string' ? e.body : JSON.stringify(e.body ?? '')
    : String(e)

  if (status === 403) {
    return {
      title: 'Node shells are not in this plan',
      note: 'Opening a shell on the node itself needs the Pro tier. Every '
          + 'other action on the host page works without it.',
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
  return { title: 'Could not open a shell', note: raw || 'No reason was given.' }
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

export function NodeShellWindow() {
  const { hostId } = useParams({ strict: false }) as { hostId: string }
  const id = Number(hostId)
  const { ticket, failed, start, reconnect, giveUp } = useReconnectingTicket('host', id)

  useEffect(() => { start() }, [start])

  if (ticket.isError) {
    const { title, note } = shellFailure(ticket.error)
    return <Failure title={title} note={note} />
  }
  if (failed) {
    return <Failure title="Shell connection lost"
      note="Gave up after repeated attempts. Close this window and open it again." />
  }
  if (!ticket.data) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-ink">
        <span className="text-[13px] text-text-3">Opening a shell…</span>
      </div>
    )
  }
  return (
    <div className="h-screen bg-ink p-2">
      <Terminal key={ticket.data.ticket}
        wsUrl={consoleWsUrl('host', id, ticket.data.ticket)}
        onDrop={({ fatal }) => (fatal ? giveUp() : reconnect())} />
    </div>
  )
}

export const nodeShellRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/shell/host/$hostId',
  component: NodeShellWindow,
})
