import { Link, useNavigate } from '@tanstack/react-router'
import type { NodeRow } from '../api/hooks'
import { fmtPct, fmtUptime } from '../lib/format'
import { StatusPill } from './StatusPill'
import { CPU_GRADIENT, RAM_GRADIENT, UsageBar } from './UsageBar'

export function NodeCard({ node }: { node: NodeRow }) {
  const navigate = useNavigate()
  return (
    <div
      className="cursor-pointer rounded-card border border-line-soft bg-panel p-4 transition-transform hover:-translate-y-0.5 motion-reduce:transform-none"
      // body click → apps filtered by host (doc 06 NodeCard)
      onClick={() => navigate({ to: '/apps' as never, search: { host: node.host_id } as never })}
    >
      <div className="flex items-center justify-between">
        <Link
          to={'/hosts/$hostId' as never} // node detail (plan decision 3)
          params={{ hostId: String(node.host_id) } as never}
          onClick={(e) => e.stopPropagation()}
          className="font-mono text-[13px] text-text hover:text-amber"
        >
          {node.name}
        </Link>
        <StatusPill status={node.status} />
      </div>
      <div className="mt-1 text-[11px] text-text-3">
        {node.cluster ? `cluster · ${node.cluster}` : 'standalone'} · {node.node}
      </div>
      <div className="mt-3 flex gap-4 font-mono text-[11px] text-text-2">
        <span>{node.vms} VMs</span>
        <span>{node.apps} Apps</span>
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
