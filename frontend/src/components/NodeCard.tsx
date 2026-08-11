import { Link, useNavigate } from '@tanstack/react-router'
import type { NodeRow } from '../api/hooks'
import { fmtPct, fmtUptime } from '../lib/format'
import { StatusPill } from './StatusPill'
import { CPU_GRADIENT, RAM_GRADIENT, UsageBar } from './UsageBar'

/** One NODE, not one host: a Host is a single Proxmox API endpoint and the
 *  cluster behind it has as many nodes as it has.
 *
 *  Card click opens the node, deliberately diverging from doc 06's original
 *  "NodeCard click -> /apps?host=..." (the doc row is updated to match): this
 *  was the only card in the product that opened something other than the thing
 *  it depicts. The apps filter survives as its own affordance on the "N Apps"
 *  meta item. */
export function NodeCard({ node }: { node: NodeRow }) {
  const navigate = useNavigate()
  // A host with no snapshot yet has no node name to route on; /hosts/$hostId
  // still resolves (it redirects to the entry node once one is known).
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
          {node.name}
        </Link>
        <StatusPill status={node.status} />
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-x-1.5 text-[11px] text-text-3">
        <span className="font-mono">{node.node ?? 'node unknown'}</span>
        {node.is_entry && (
          <span title="The node Proxploy connects through for this host">entry</span>
        )}
        <span>· {node.cluster ?? 'standalone'}</span>
      </div>
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
      </div>
    </div>
  )
}
