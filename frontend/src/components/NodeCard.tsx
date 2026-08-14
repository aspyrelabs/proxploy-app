import { Link, useNavigate } from '@tanstack/react-router'
import type { NodeRow } from '../api/hooks'
import { fmtPct, fmtUptime } from '../lib/format'
import { StatusPill } from './StatusPill'
import { CPU_GRADIENT, RAM_GRADIENT, STORAGE_GRADIENT, UsageBar } from './UsageBar'

/** One NODE, not one host: a Host is a single Proxmox API endpoint and the
 *  cluster behind it has as many nodes as it has.
 *
 *  Card click opens the node, deliberately diverging from doc 06's original
 *  "NodeCard click -> /apps?host=..." (the doc row is updated to match): this
 *  was the only card in the product that opened something other than the thing
 *  it depicts. The apps filter survives as its own affordance on the "N Apps"
 *  meta item. */
export function NodeCard({ node }: {
  node: NodeRow & { endpoints?: { host_id: number; name: string; status: string }[] }
}) {
  const navigate = useNavigate()
  // A host with no snapshot yet has no node name to route on; /hosts/$hostId
  // still resolves (it redirects to the entry node once one is known).
  // `endpoints` is optional so the card still renders from a bare NodeRow;
  // absent, the card describes the one endpoint it came from, which is exactly
  // what an undeduped row means.
  const endpoints = node.endpoints ?? [
    { host_id: node.host_id, name: node.name, status: node.status },
  ]
  const unreachable = endpoints.filter((e) => e.status !== 'connected')
  // Named only when there is exactly ONE, because only then is "the endpoint
  // this node is reached through" a fact about the node. Once a cluster is
  // enrolled through several endpoints they ALL see every node, so a count
  // ("via 2 endpoints") described Proxploy's own plumbing rather than
  // anything about the machine on the card -- unreadable to the person
  // looking at it, and the same jargon failure as the old bare "entry" badge.
  // The case where it genuinely matters is an endpoint being DOWN, and the
  // amber line below says that in words.
  const via = endpoints.length === 1 ? endpoints[0].name : null
  const open = () => (node.node
    ? navigate({ to: '/hosts/$hostId/$node' as never,
                 params: { hostId: String(node.host_id), node: node.node } as never })
    : navigate({ to: '/hosts/$hostId' as never,
                 params: { hostId: String(node.host_id) } as never }))
  return (
    <div
      role="link" tabIndex={0}
      className="cursor-pointer rounded-card border border-line-soft bg-panel p-4 transition-transform hover:-translate-y-0.5 motion-reduce:transform-none"
      onClick={open}
      // The card is the primary navigation now, so it has to work without a
      // mouse. Space is prevented so the page does not scroll under the press.
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open() }
      }}
    >
      <div className="flex items-center justify-between">
        <Link
          to={'/hosts/$hostId/$node' as never} // node detail, keyed on (host, node)
          params={{ hostId: String(node.host_id), node: node.node ?? '' } as never}
          onClick={(e) => e.stopPropagation()}
          className="font-mono text-[13px] text-text hover:text-amber"
        >
          {/* The NODE leads, not the host. This card depicts one node, and
              titling it with the host name meant a cluster drew several cards
              under the same title, each with a different node in the subline
              -- so the card that showed node2's gauges was headed
              "node1.example.com". The endpoint moved to the meta row below,
              which is where "how do we reach this" belongs. */}
          {node.node ?? 'node unknown'}
        </Link>
        <StatusPill status={node.status} />
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-x-1.5 text-[11px] text-text-3">
        {/* The cluster's own name, not "in <name>": these cards already sit
            under a "Cluster <name>" heading, so the preposition just said the
            same thing twice. Standalone nodes have no heading above them,
            which is why they still say so here. */}
        <span>{node.cluster ?? 'standalone'}</span>
        {via && <span>· {via}</span>}
      </div>
      {unreachable.length > 0 && (
        /* Deduping the cards removed the only place a dead endpoint used to be
           visible: its rows collapsed into the surviving node's card and its
           StatusPill went with them. The node itself may be perfectly healthy
           and still be one enrolled endpoint down, so it is said in words. */
        <div className="mt-1 text-[11px] text-amber">
          {unreachable.length === 1
            ? `${unreachable[0].name} cannot be reached`
            : `${unreachable.length} endpoints cannot be reached`}
        </div>
      )}
      <div className="mt-3 flex gap-4 font-mono text-[11px] text-text-2">
        {/* Plain text, not a link: /vms takes no host filter (unlike /apps),
            and inventing one here would be a link to a page that ignores it. */}
        <span>{node.vms} VMs</span>
        <Link to={'/apps' as never} search={{ host: node.host_id } as never}
          onClick={(e) => e.stopPropagation()} className="hover:text-amber">
          {node.apps} Apps
        </Link>
        <span>{fmtUptime(node.uptime_s)}</span>
      </div>
      <div className="mt-3 space-y-2">
        <div className="flex items-center gap-2">
          <span className="w-8 text-[10.5px] uppercase text-text-3">CPU</span>
          <div className="flex-1"><UsageBar pct={node.cpu_pct} gradient={CPU_GRADIENT} /></div>
          <span className="w-9 text-right font-mono text-[11px] text-text-2">{fmtPct(node.cpu_pct)}</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="w-8 text-[10.5px] uppercase text-text-3">RAM</span>
          <div className="flex-1"><UsageBar pct={node.mem_pct} gradient={RAM_GRADIENT} /></div>
          <span className="w-9 text-right font-mono text-[11px] text-text-2">{fmtPct(node.mem_pct)}</span>
        </div>
        {/* Storage of THIS node, shared datastores included: they are storage
            this node can really use. Do not add these up across a cluster,
            that double-counts every shared pool (see api/cluster.py). */}
        <div className="flex items-center gap-2">
          <span className="w-8 text-[10.5px] uppercase text-text-3">Disk</span>
          <div className="flex-1"><UsageBar pct={node.disk_pct} gradient={STORAGE_GRADIENT} /></div>
          <span className="w-9 text-right font-mono text-[11px] text-text-2">{fmtPct(node.disk_pct)}</span>
        </div>
      </div>
    </div>
  )
}
