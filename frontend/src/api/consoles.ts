import { useMutation } from '@tanstack/react-query'
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
