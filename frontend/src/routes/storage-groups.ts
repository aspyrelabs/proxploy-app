import type { StorageRow } from '../api/storage'

export type HostIdentity = {
  id: number
  name: string
  node_name: string | null
  cluster_name?: string | null
}

export type StorageGroup = {
  /** Stable key, since two clusters can both have a node called `pve`. */
  key: string
  label: string
  rows: StorageRow[]
}

/**
 * The Storage page's datastores, split into the groups it renders.
 *
 * NOT grouped on `row.host_id`, which is the obvious field and the wrong one.
 * GET /storage keys its dedupe on (cluster, node, storage) and deliberately
 * leaves host_id out, because both nodes of a cluster report the whole
 * cluster's storage and either can serve it. Every surviving row therefore
 * names whichever host polled FIRST, so grouping on it puts the entire cluster
 * under one host and leaves every other host empty. That is the same defect
 * that made the VM create wizard offer no datastores at all on one host
 * (see components/install/pools.ts::servedTo).
 *
 * So local datastores group on `row.node`, which is reliable for them, and
 * shared ones are lifted out entirely, into a group at the END: a shared
 * datastore is reported once per node and GET /storage keeps whichever row it
 * saw first, so the node on a shared row is arbitrary and changes when the
 * poller restarts. Grouping a shared pool by it would move the pool between
 * headings with nothing having changed on the cluster.
 *
 * A shared pool on a STANDALONE host stays with that host: `cluster_name` null
 * means not clustered rather than unknown, so it is shared with nobody and a
 * cluster heading would be a heading for one machine.
 *
 * Hosts with no datastores keep their (empty) group. A host that silently
 * disappears from this page reads exactly like the bug above, and "this host
 * has nothing attached" is worth saying out loud.
 *
 * A node nobody is enrolled at gets a group under its own name rather than
 * being dropped, since its datastores are real and the page is the only place
 * they would show.
 */
export function groupStorage(rows: StorageRow[], hosts: HostIdentity[]): StorageGroup[] {
  const hostByNode = new Map(
    hosts.filter((h) => h.node_name).map((h) => [h.node_name as string, h]))

  const shared = new Map<string, StorageGroup>()
  const byNode = new Map<string, StorageRow[]>()

  for (const r of rows) {
    const cluster = hostByNode.get(r.node)?.cluster_name ?? r.cluster_name
    if (r.shared && cluster) {
      const g = shared.get(cluster)
        ?? { key: `cluster:${cluster}`, label: 'Shared', rows: [] }
      // Deduped by name: a shared datastore should already arrive once, and if
      // it ever arrives twice it is still one datastore.
      if (!g.rows.some((x) => x.storage === r.storage)) g.rows.push(r)
      shared.set(cluster, g)
      continue
    }
    byNode.set(r.node, [...(byNode.get(r.node) ?? []), r])
  }

  const nodeGroups: StorageGroup[] = []
  for (const h of [...hosts].sort((a, b) => a.name.localeCompare(b.name))) {
    if (!h.node_name) continue
    nodeGroups.push({ key: `host:${h.id}`, label: h.name,
                      rows: byNode.get(h.node_name) ?? [] })
  }
  for (const node of [...byNode.keys()].sort()) {
    if (hostByNode.has(node)) continue
    nodeGroups.push({ key: `node:${node}`, label: node, rows: byNode.get(node) ?? [] })
  }

  // Hosts first, shared last: the per-host groups are what the page is for,
  // and a shared datastore is the exception to read after them.
  return [...nodeGroups,
          ...[...shared.values()].sort((a, b) => a.key.localeCompare(b.key))]
}
