import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import * as Tooltip from '@radix-ui/react-tooltip'
import { api } from '../api/client'
import { useFiringAlerts } from '../api/alerts'
import type { NodeRow } from '../api/hooks'
import { dedupeNodes } from '../lib/nodes'

/** Doc 06 §(b) `HealthFooter`: `.side-foot`, "All systems healthy", green dot,
 *  "3 nodes · 0 alerts". Bound to `/alerts?state=firing` + host status; the dot
 *  turns `--red` when anything is firing.
 *
 *  Until Phase 7 this was three hard-coded lines in SidebarNav that always said
 *  "All systems healthy", the one piece of UI that must never lie.
 *
 *  `collapsed` (the 64px icon rail): there is no room here for even one word
 *  of the two-line body ("systems"/"healthy" alone are each wider than the
 *  32px of content the rail leaves), so they'd overflow past the aside's
 *  border rather than wrap cleanly, and a `truncate` would just leave a
 *  meaningless sliver of a word. So collapsed renders the dot alone, carries
 *  the headline as its accessible name, and repeats it in a Radix tooltip,
 *  the same pattern the collapsed nav items already use. */
export function HealthFooter({ collapsed = false }: { collapsed?: boolean }) {
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
    const headline = 'Status unknown'
    const dot = 'bg-text-3'
    if (collapsed) return <CollapsedStatus headline={headline} dot={dot} />
    return (
      <Link to="/alerts"
            className="block border-t border-line-soft px-4 py-3 text-[12px] text-text-2 hover:bg-panel-2">
        <span className={`mr-2 inline-block h-2 w-2 rounded-full ${dot}`} />
        {headline}
        <span className="mt-0.5 block font-mono text-[11px] text-text-3">
          couldn't reach the API
        </span>
      </Link>
    )
  }

  const firing = alerts.data?.length ?? 0
  // Deduped for the same reason the Hosts page is: /cluster/nodes answers one
  // row per (host, node), so two endpoints enrolled into one cluster made this
  // footer count every node once per endpoint and report "4 nodes" for a
  // two-node cluster. `down` was inflated the same way, which mattered more:
  // one unreachable endpoint counted once per node behind it.
  const rows = dedupeNodes(nodes.data ?? [])
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

  if (collapsed) return <CollapsedStatus headline={headline} dot={dot} />

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

// Self-contained Tooltip.Provider rather than relying on SidebarNav's: this
// component is tested (and could be reused) outside that tree, and a nested
// Provider is harmless where one already exists.
function CollapsedStatus({ headline, dot }: { headline: string; dot: string }) {
  return (
    <Tooltip.Provider delayDuration={200}>
      <Tooltip.Root>
        <Tooltip.Trigger asChild>
          <Link to={'/alerts' as never} aria-label={headline}
                className="grid place-items-center border-t border-line-soft py-3 hover:bg-panel-2">
            <span className={`h-2 w-2 rounded-full ${dot}`} />
          </Link>
        </Tooltip.Trigger>
        <Tooltip.Portal>
          <Tooltip.Content side="right" sideOffset={6}
            className="z-50 rounded-tile border border-line bg-elev px-2 py-1 text-[12px] text-text shadow-lg">
            {headline}
          </Tooltip.Content>
        </Tooltip.Portal>
      </Tooltip.Root>
    </Tooltip.Provider>
  )
}
