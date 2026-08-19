import { useQuery } from '@tanstack/react-query'
import { api } from '../../api/client'

export type StorageRow = {
  host_id: number; node: string; storage: string; content: string[]; status: string
  shared: boolean
  /** The cluster of the host whose poll produced this row, null when that host
   *  is standalone. GET /storage collapses a cluster's datastores to ONE row
   *  per (cluster, node, storage) and keeps whichever host polled first, so the
   *  row's host_id is NOT the only host that can serve it. This is how a
   *  caller tells "a sibling node of my cluster reported it" (usable) from
   *  "an unrelated host reported it" (not). */
  cluster_name: string | null
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
/**
 * Whether `row` was reported by a host that can actually serve it to `hostId`.
 *
 * NOT `row.host_id === hostId`, which is what this used to be and was wrong on
 * every cluster. GET /storage keys its dedupe on (cluster, node, storage) with
 * host_id deliberately absent, because both nodes of a cluster report the whole
 * cluster's storage and either can serve it; the surviving row carries
 * whichever host polled first. On a two-node cluster that meant the host which
 * lost the race saw NO pools at all, so Advanced install could not be
 * configured on it, and which host that was flipped on every backend restart.
 *
 * A standalone host keeps the strict identity check: its cluster_name is null,
 * and null means "not clustered" rather than "unknown", so two standalone hosts
 * must never match each other through it.
 */
export function servedTo(row: { host_id: number; cluster_name: string | null },
                         hostId: number | null,
                         clusterName: string | null | undefined): boolean {
  if (row.host_id === hostId) return true
  return row.cluster_name != null && row.cluster_name === clusterName
}

/** The pure computation behind useStoragePools, exported so the filtering can
 *  be tested without a query client. */
export function poolsFrom(rows: StorageRow[] | undefined, hostId: number | null,
                          node: string | null | undefined,
                          clusterName: string | null | undefined,
                          content: string): string[] {
  return [...new Set(
    (rows ?? [])
      .filter((r) => servedTo(r, hostId, clusterName)
        && (!node || r.node === node || r.shared)
        && r.status === 'available'
        && r.content.includes(content))
      .map((r) => r.storage))].sort()
}

export function useStoragePools(hostId: number | null,
                                node: string | null | undefined,
                                clusterName?: string | null): Pools {
  const q = useQuery({ queryKey: ['storage'], queryFn: () => api<StorageRow[]>('/storage') })
  return {
    rootdir: poolsFrom(q.data, hostId, node, clusterName, 'rootdir'),
    vztmpl: poolsFrom(q.data, hostId, node, clusterName, 'vztmpl'),
    state: q.isError ? 'error' : q.isPending ? 'loading' : 'ok',
  }
}

/**
 * The pool an install will use without asking: the sole candidate. Null
 * means there is a real choice to make (0 candidates is Default's "cannot
 * see the pools yet" / "host has none" case, handled elsewhere).
 *
 * PXP-86 decision: no remembering the last placement. This used to also
 * check a value remembered on Host.default_*_storage before falling back to
 * the sole-candidate case; that branch is gone, matching
 * resolve_storage_pools (backend/proxploy/services/appstore.py), which no
 * longer reads that column either. A host with two or more candidates is
 * asked every time, never silently answered from a prior install.
 */
export function knownPool(candidates: string[]): string | null {
  return candidates.length === 1 ? candidates[0] : null
}
