import { useMutation } from '@tanstack/react-query'

import { api, type ApiError } from './client'

/** One thing the container was listening on when we looked. */
export type PortCandidate = {
  port: number
  /** The process holding the socket, when ss named one. */
  process: string | null
  /** What it was bound to. `*` or an address, never loopback: those are
   *  dropped before they get here, since a browser cannot reach them. */
  address: string
}

/**
 * Ask a container what it is listening on.
 *
 * A GET behind a mutation, deliberately: it changes nothing, but it runs a
 * command on the host and takes a moment, so it belongs to a button rather
 * than to a query that refetches on its own.
 *
 * `accurate` is always false and the UI is expected to say so. This is a
 * snapshot ranked by a heuristic: a container can serve two UIs, can be
 * mid-restart, or can listen on something the ranking has never heard of.
 */
export function useDetectPorts(appId: number) {
  return useMutation<{ ports: PortCandidate[]; accurate: boolean }, ApiError, void>({
    mutationFn: () => api(`/apps/${appId}/ports`),
  })
}
