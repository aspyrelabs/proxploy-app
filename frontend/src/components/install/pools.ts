import { useQuery } from '@tanstack/react-query'
import { api } from '../../api/client'

export type StorageRow = {
  host_id: number; node: string; storage: string; content: string[]; status: string
}

export type Pools = {
  rootdir: string[]
  vztmpl: string[]
  /** 'ok' once the snapshot has been read. Anything else means the candidate
   *  lists below are not an answer, they are the absence of one. */
  state: 'ok' | 'loading' | 'error'
}

/**
 * The container (`rootdir`) and template (`vztmpl`) pool candidates for a
 * host, as the BACKEND sees them.
 *
 * The one authority on what an install can actually use is
 * backend/proxploy/services/appstore.py::_storage_pools, which runs the
 * API-side equivalent of `pvesm status -content <c>` against `host.node_name`
 * and drops anything not enabled and active. This recreates that same set from
 * GET /storage so the form and the job agree about how many candidates exist,
 * because that count is what decides whether there is a question to ask at
 * all. Three ways the raw rows disagree with it, all of them observed:
 *
 *  - GET /storage keys non-shared datastores by (host, node, storage), so a
 *    3-node cluster with the usual identical local names answers `local-lvm`
 *    three times. Unfiltered that reads as three candidates (a question where
 *    there is no choice, duplicate React keys) where the backend sees one.
 *    Hence the node filter plus the dedupe, matching VmCreateWizard.tsx's
 *    storeOpts, which filters on `s.node === f.node`.
 *  - the list is not status-filtered, so an inactive pool would be offered,
 *    chosen, remembered on the Host, and every later Default install would
 *    fail on it.
 *  - it is served from the poller snapshot, which is EMPTY until the first
 *    poll after a backend restart, and absent entirely on a 403. Empty is
 *    indistinguishable from "this host has no storage" unless the load state
 *    is carried out with the lists, which is what `state` is for.
 *
 * `node` falls back to no node filter when the host has no node_name recorded;
 * such a host cannot install at all (_storage_pools raises on it), so there is
 * nothing better to show than the deduped host-wide set.
 */
export function useStoragePools(hostId: number | null,
                                node: string | null | undefined): Pools {
  const q = useQuery({ queryKey: ['storage'], queryFn: () => api<StorageRow[]>('/storage') })
  const names = (content: string) => [...new Set(
    (q.data ?? [])
      .filter((r) => r.host_id === hostId
        && (!node || r.node === node)
        && r.status === 'available'
        && r.content.includes(content))
      .map((r) => r.storage))].sort()
  return {
    rootdir: names('rootdir'),
    vztmpl: names('vztmpl'),
    state: q.isError ? 'error' : q.isPending ? 'loading' : 'ok',
  }
}

/**
 * The pool an install will use without asking: a remembered choice
 * (Host.default_*_storage) that is STILL a candidate, else the sole candidate.
 * Null means there is either nothing to use or a real choice to make.
 *
 * A remembered value that has dropped out of `candidates` (renamed, detached,
 * or gone inactive) deliberately resolves to null rather than being shown as
 * fact: the install would fail on it with "no longer available", and the only
 * place that can be corrected is the question this un-answers.
 */
export function knownPool(remembered: string | null | undefined,
                          candidates: string[]): string | null {
  if (remembered && candidates.includes(remembered)) return remembered
  return candidates.length === 1 ? candidates[0] : null
}
