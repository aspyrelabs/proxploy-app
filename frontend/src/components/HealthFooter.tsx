import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { api } from '../api/client'
import { useFiringAlerts } from '../api/alerts'
import type { NodeRow } from '../api/hooks'

/** Doc 06 §(b) `HealthFooter`: `.side-foot`, "All systems healthy", green dot,
 *  "3 nodes · 0 alerts". Bound to `/alerts?state=firing` + host status; the dot
 *  turns `--red` when anything is firing.
 *
 *  Until Phase 7 this was three hard-coded lines in SidebarNav that always said
 *  "All systems healthy", the one piece of UI that must never lie. */
export function HealthFooter() {
  const alerts = useFiringAlerts()
  const nodes = useQuery({
    queryKey: ['cluster', 'nodes'],
    queryFn: () => api<NodeRow[]>('/cluster/nodes'),
    refetchInterval: 30_000,
  })

  // Don't say "healthy" before either query has answered, that's the exact
  // lie this footer used to tell unconditionally.
  if (alerts.isPending || nodes.isPending) return null

  // isPending goes false on error too (data stays undefined), so a 401/500/
  // dropped network would otherwise fall through to firing=0, down=0; 
  // "All systems healthy" while the backend is unreachable. Say so instead.
  if (alerts.isError || nodes.isError) {
    return (
      <Link to="/alerts"
            className="block border-t border-line-soft px-4 py-3 text-[12px] text-text-2 hover:bg-panel-2">
        <span className="mr-2 inline-block h-2 w-2 rounded-full bg-text-3" />
        Status unknown
        <span className="mt-0.5 block font-mono text-[11px] text-text-3">
          couldn't reach the API
        </span>
      </Link>
    )
  }

  const firing = alerts.data?.length ?? 0
  const rows = nodes.data ?? []
  const down = rows.filter((n) => n.status !== 'connected').length
  const critical = (alerts.data ?? []).some((a) => a.severity === 'critical')
  const unhealthy = firing > 0 || down > 0

  const headline = firing > 0
    ? `${firing} alert${firing === 1 ? '' : 's'} firing`
    : down > 0
      ? `${down} node${down === 1 ? '' : 's'} unreachable`
      : 'All systems healthy'

  const dot = !unhealthy ? 'bg-green shadow-[0_0_6px_rgba(63,207,142,.6)]'
    : critical || down > 0 ? 'bg-red shadow-[0_0_6px_rgba(232,90,90,.6)]'
    : 'bg-amber shadow-[0_0_6px_rgba(245,181,68,.6)]'

  return (
    <Link to={'/alerts' as never}
          className="block border-t border-line-soft px-4 py-3 text-[12px] text-text-2 hover:bg-panel-2">
      <span className={`mr-2 inline-block h-2 w-2 rounded-full ${dot}`} />
      {headline}
      <span className="mt-0.5 block font-mono text-[11px] text-text-3">
        {rows.length} node{rows.length === 1 ? '' : 's'} · {firing} alert{firing === 1 ? '' : 's'}
      </span>
    </Link>
  )
}
