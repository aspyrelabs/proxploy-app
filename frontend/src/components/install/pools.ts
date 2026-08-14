import { useQuery } from '@tanstack/react-query'
import { api } from '../../api/client'

export type StorageRow = {
  host_id: number; node: string; storage: string; content: string[]; status: string
  shared: boolean
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
 * all. Ways the raw rows disagree with it, all of them observed:
 *
 *  - GET /storage keys non-shared datastores by (host, node, storage), so a
 *    3-node cluster with the usual identical local names answers `local-lvm`
 *    three times. Unfiltered that reads as three candidates (a question where
 *    there is no choice, duplicate React keys) where the backend sees one.
 *    Hence the node filter plus the dedupe, matching VmCreateWizard.tsx's
 *    storeOpts, which filters on `s.node === f.node`.
 *  - a SHARED datastore is the opposite case: backend/proxploy/api/storage.py
 *    ::list_storage keys it by (host_id, storage) with no node component,
 *    because a shared datastore reported once per node is ONE datastore, and
 *    keeps whichever row the poller snapshot happened to see first, which may
 *    legitimately name a node other than this host's own. A shared row is
 *    therefore a candidate for every node of this host, and the node filter
 *    below exempts it, else a host with real shared pools could see one
 *    reported under a foreign node and lose it, reintroducing the exact
 *    "question Default never rendered" failure the node filter exists to
 *    prevent. The dedupe still applies to shared rows, in case one somehow
 *    appears more than once.
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
        && (!node || r.node === node || r.shared)
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
 * place that can be corrected is the question this un-answers. This holds no
 * matter how many candidates remain, including exactly one: matching
 * resolve_storage_pools (backend/proxploy/services/appstore.py), a remembered
 * choice is NEVER quietly swapped for another pool, sole survivor or not.
 * Re-ask instead.
 */
export function knownPool(remembered: string | null | undefined,
                          candidates: string[]): string | null {
  if (remembered) return candidates.includes(remembered) ? remembered : null
  return candidates.length === 1 ? candidates[0] : null
}
