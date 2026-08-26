import type { HostThroughput } from '../api/network'

/**
 * One combined in/out series for the whole fleet, out of the per-host series
 * GET /network/throughput answers with.
 *
 * DEDUPED BY CLUSTER FIRST, and that is the entire reason this function
 * exists rather than a `.reduce()` at the call site. A Host record in Proxploy
 * is one Proxmox API endpoint, and pollers/__init__.py records that host's
 * `net_in_bps` as the SUM OVER EVERY NODE the endpoint can see. So on a
 * cluster with two hosts enrolled, both rows carry the same whole-cluster
 * series, and adding them reports twice the traffic that exists. The rings
 * beside this tile already dedupe the same way (api/cluster.py sums over nodes
 * keyed by (cluster, node)), so a summed tile would have contradicted the row
 * it sits in. routes/network.tsx's ThroughputCard still adds them up.
 *
 * A host with no cluster is standalone and always counts: two standalone
 * machines are two machines, however they were named.
 *
 * A BUCKET IS null UNLESS EVERY COUNTED HOST MEASURED IT. The poller applies
 * exactly this rule one level down, and its comment says why: throughput is a
 * rate, not a level, so a missing member does not carry forward, it halves the
 * number. A partial sum drawn as a real sample is a dip that never happened.
 */
export function combineThroughput(
  hosts: HostThroughput[],
  /** The cluster a host belongs to, or null when it stands alone. */
  clusterOf: (hostId: number) => string | null,
): { ts: number[]; inValues: (number | null)[]; outValues: (number | null)[] } {
  const seen = new Set<string>()
  const counted = [...hosts]
    // Sorted so which host stands for a cluster does not depend on the order
    // the API happened to answer in, which would reshuffle the chart on a
    // refetch that changed nothing.
    .sort((a, b) => a.host_id - b.host_id)
    .filter((h) => {
      const cluster = clusterOf(h.host_id)
      if (cluster == null) return true
      if (seen.has(cluster)) return false
      seen.add(cluster)
      return true
    })

  // Keyed by timestamp rather than by index: two hosts polled a beat apart can
  // return different bucket counts, and zipping those by position would add
  // one host's 09:00 to another's 09:05.
  const ts = [...new Set(counted.flatMap((h) => h.in.ts))].sort((a, b) => a - b)
  const sum = (pick: (h: HostThroughput) => { ts: number[]; value: (number | null)[] }) =>
    ts.map((t) => {
      let total = 0
      for (const h of counted) {
        const series = pick(h)
        const v = series.value[series.ts.indexOf(t)]
        if (v == null) return null
        total += v
      }
      return total
    })

  return { ts, inValues: sum((h) => h.in), outValues: sum((h) => h.out) }
}
