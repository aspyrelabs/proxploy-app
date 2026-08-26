import type { NodeRow } from '../api/hooks'

/** GET /cluster/nodes answers one row per (host, node), because a Host is one
 *  API ENDPOINT and each endpoint reports every node of the cluster behind it.
 *  Enrol two endpoints into the same cluster and a two-node cluster arrives as
 *  four rows: each physical node once per endpoint that can see it.
 *
 *  Collapsing them is not cosmetic: undeduped, a node is drawn once per
 *  endpoint, its gauges repeat, and the group's "N nodes" count reports
 *  endpoints-times-nodes rather than nodes.
 *
 *  Two rows are the SAME physical node only when they agree on the node name
 *  AND sit in the same cluster: outside a cluster, `node1` behind one endpoint
 *  and `node1` behind another are two unrelated machines that merely share the
 *  usual default hostname, so standalone rows stay keyed by host.
 *
 *  The surviving row is the `is_entry` one where there is one, because that is
 *  the endpoint whose connection actually reaches this node, and every link on
 *  the card is keyed on (host, node).
 *
 *  What deduping would otherwise HIDE is carried out in `endpoints`: the page
 *  still has to answer "is each endpoint I enrolled reachable", and once the
 *  duplicate cards are gone there is nowhere else that question lives. */
export type MergedNode = NodeRow & {
  endpoints: { host_id: number; name: string; status: string }[]
}

export function dedupeNodes(rows: NodeRow[]): MergedNode[] {
  const byNode = new Map<string, NodeRow[]>()
  rows.forEach((n, i) => {
    // A row with no node name cannot be PROVEN to describe the same machine as
    // any other, so it never merges. The backend emits exactly that for a host
    // whose first poll has not landed (api/cluster.py falls back to
    // `h.node_name`, which is NULL until then), and two such hosts enrolled
    // into one cluster would otherwise collapse into a single card and hide
    // one of them. `i` keeps those rows unique without special-casing further.
    const key = !n.node ? `i:${i}`
      : n.cluster ? `c:${n.cluster}:${n.node}`
      : `h:${n.host_id}:${n.node}`
    const seen = byNode.get(key)
    if (seen) seen.push(n)
    else byNode.set(key, [n])
  })
  return [...byNode.values()].map((group) => {
    const base = group.find((n) => n.is_entry) ?? group[0]
    return {
      ...base,
      endpoints: group.map((n) => ({
        host_id: n.host_id, name: n.name, status: n.status,
      })),
    }
  })
}
