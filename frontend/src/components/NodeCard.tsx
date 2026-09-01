import { useQuery } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import { api } from '../api/client'
import type { NodeRow } from '../api/hooks'
import { fmtPct, fmtUptime } from '../lib/format'
import { StatusPill } from './StatusPill'
import { Skeleton, SkeletonLine, SkeletonMeterRow } from './ui/skeleton'
import { CPU_GRADIENT, RAM_GRADIENT, STORAGE_GRADIENT, UsageBar } from './UsageBar'
import { linkCls } from './ui/button'
import { pveWebUrl } from '../lib/utils'

/** The slice of GET /hosts this card needs: which endpoint answers for a node,
 *  and the address its "Open" shortcut points at. */
type HostRow = { id: number; address: string }

/** One NODE, not one host: a Host is a single Proxmox API endpoint and the
 *  cluster behind it has as many nodes as it has. */
export function NodeCard({ node }: {
  node: NodeRow & { endpoints?: { host_id: number; name: string; status: string }[] }
}) {
  const navigate = useNavigate()
  // GET /nodes doesn't carry the address; /hosts is already cached under the
  // shared ['hosts'] key, so a page of cards is one request, not one per node.
  const hosts = useQuery({ queryKey: ['hosts'], queryFn: () => api<HostRow[]>('/hosts') })
  // The ENDPOINT's address, not the node's: Proxmox's own UI is cluster-wide,
  // and a deep link preselecting one node has a URL shape that differs across
  // PVE versions, so it's not worth inventing here.
  const webUrl = (hosts.data ?? []).find((h) => h.id === node.host_id)?.address
  // A host with no snapshot yet has no node name to route on; /hosts/$hostId
  // still resolves (it redirects to the entry node once one is known).
  // `endpoints` is optional so the card still renders from a bare NodeRow;
  // absent, the card describes the one endpoint it came from, which is exactly
  // what an undeduped row means.
  const endpoints = node.endpoints ?? [
    { host_id: node.host_id, name: node.name, status: node.status },
  ]
  const unreachable = endpoints.filter((e) => e.status !== 'connected')
  // Named only when there is exactly ONE: with several endpoints they ALL see
  // every node, so a count describes Proxploy's plumbing, not the machine.
  // The case that matters is an endpoint being DOWN, which the amber line
  // below says in words.
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
          to={'/hosts/$hostId/$node' as never}
          params={{ hostId: String(node.host_id), node: node.node ?? '' } as never}
          onClick={(e) => e.stopPropagation()}
          className={`font-mono text-[13px] ${linkCls}`}
        >
          {node.node ?? 'node unknown'}
        </Link>
        <div className="flex items-center gap-2">
          {webUrl && (
            /* stopPropagation because the whole card is a click target that
               opens the node: following this link must not also navigate the
               page behind the new tab.

               rel="noopener": without it the opened page can steer this one
               through window.opener. */
            <a href={pveWebUrl(webUrl)} target="_blank" rel="noopener noreferrer"
              aria-label={`Open the Proxmox web UI for ${node.node ?? node.name}`}
              title="Open Proxmox web UI"
              onClick={(e) => e.stopPropagation()}
              className="text-[11px] text-text-3 transition hover:text-amber">
              Open ↗
            </a>
          )}
          <StatusPill status={node.status} />
        </div>
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-x-1.5 text-[11px] text-text-3">
        {/* Cluster name, not "in <name>": cards already sit under a
            "Cluster <name>" heading; standalone nodes have no heading. */}
        <span>{node.cluster ?? 'standalone'}</span>
        {via && <span>· {via}</span>}
      </div>
      {unreachable.length > 0 && (
        /* Dedup collapsed a dead endpoint's row into the surviving card, so
           its StatusPill vanished with it. A node can be healthy while one
           enrolled endpoint is down, so it's said in words. */
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
          <div className="flex flex-1 items-center gap-[3px]">
            <div className="flex-1"><UsageBar pct={node.cpu_pct} gradient={CPU_GRADIENT} /></div>
            <span className="w-9 text-right font-mono text-[11px] text-text-2">{fmtPct(node.cpu_pct)}</span>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className="w-8 text-[10.5px] uppercase text-text-3">RAM</span>
          <div className="flex flex-1 items-center gap-[3px]">
            <div className="flex-1"><UsageBar pct={node.mem_pct} gradient={RAM_GRADIENT} /></div>
            <span className="w-9 text-right font-mono text-[11px] text-text-2">{fmtPct(node.mem_pct)}</span>
          </div>
        </div>
        {/* Storage of THIS node, shared datastores included: they are storage
            this node can really use. Do not add these up across a cluster,
            that double-counts every shared pool (see api/cluster.py). */}
        <div className="flex items-center gap-2">
          <span className="w-8 text-[10.5px] uppercase text-text-3">Disk</span>
          <div className="flex flex-1 items-center gap-[3px]">
            <div className="flex-1"><UsageBar pct={node.disk_pct} gradient={STORAGE_GRADIENT} /></div>
            <span className="w-9 text-right font-mono text-[11px] text-text-2">{fmtPct(node.disk_pct)}</span>
          </div>
        </div>
      </div>
    </div>
  )
}

/**
 * NodeCard's placeholder. Classes copied from the card above so the two come
 * out the same height. The unreachable-endpoints line is not reproduced:
 * reserving space for it would make the layout settle downward when the good
 * case arrives.
 */
export function NodeCardSkeleton() {
  return (
    <div className="rounded-card border border-line-soft bg-panel p-4">
      <div className="flex items-center justify-between">
        <SkeletonLine className="w-24 text-[13px]" />
        {/* StatusPill: px-2 py-0.5 around a 10.5px line box. */}
        <Skeleton className="h-[19px] w-20 rounded-full" />
      </div>
      <SkeletonLine className="mt-1 w-28 text-[11px]" />
      <div className="mt-3 flex gap-4 text-[11px]">
        <SkeletonLine className="w-12" />
        <SkeletonLine className="w-12" />
        <SkeletonLine className="w-16" />
      </div>
      <div className="mt-3 space-y-2">
        <SkeletonMeterRow />
        <SkeletonMeterRow />
        <SkeletonMeterRow />
      </div>
    </div>
  )
}
