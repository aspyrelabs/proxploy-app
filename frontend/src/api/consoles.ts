import { useMutation } from '@tanstack/react-query'
import { useCallback, useRef, useState } from 'react'
import { api } from './client'

export type ConsoleTicket = { ticket: string; expires_at: string }
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

export function consoleWsUrl(kind: ConsoleKind, id: number, ticket: string): string {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${location.host}/api/v1${WS_PATH[kind](id, ticket)}`
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

export function useReconnectingTicket(kind: ConsoleKind, id: number) {
  const ticket = useConsoleTicket(kind, id)
  const attempts = useRef(0)
  const [failed, setFailed] = useState(false)

  // Fresh console (first open, or the id changed): reset the attempt count
  // and mint a ticket right away.
  const start = useCallback(() => {
    attempts.current = 0
    setFailed(false)
    ticket.mutate()
    // eslint-disable-next-line react-hooks/exhaustive-deps -- ticket.mutate is a stable ref
  }, [kind, id])

  // A transient drop: retry with backoff up to the cap, then give up for good.
  const reconnect = useCallback(() => {
    if (attempts.current >= MAX_RECONNECT_ATTEMPTS) {
      setFailed(true)
      return
    }
    const delay = BACKOFF_MS[attempts.current]
    attempts.current += 1
    setTimeout(() => ticket.mutate(), delay)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // A drop we already know is terminal (Terminal.tsx saw an error frame), 
  // skip straight to the cap-reached message instead of burning attempts.
  const giveUp = useCallback(() => setFailed(true), [])

  return { ticket, failed, start, reconnect, giveUp }
}
