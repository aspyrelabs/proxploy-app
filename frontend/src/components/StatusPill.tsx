import { statusLabel } from '../lib/activityDisplay'

// Stopped is RED, not grey. Grey said "no information" while red says "this
// is not running", and those are different claims: `unknown` below is the one
// that means we could not tell. An operator scanning a grid needs the two
// separable at a glance.
//
// Pending is amber, the same as paused: both mean "in between", and the pill
// is the only place that distinction is drawn.
const STYLES: Record<string, string> = {
  running: 'bg-green-dim text-green',
  connected: 'bg-green-dim text-green',
  online: 'bg-green-dim text-green',
  stopped: 'bg-red-dim text-red',
  paused: 'bg-amber-dim text-amber',
  pending: 'bg-amber-dim text-amber',
  unreachable: 'bg-red-dim text-red',
  error: 'bg-red-dim text-red',
  unknown: 'bg-panel-2 text-text-3',
}

export function StatusPill({ status }: { status: string }) {
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 font-mono text-[10.5px] uppercase ${STYLES[status] ?? STYLES.unknown}`}>
      <span className="h-1.5 w-1.5 rounded-full bg-current" />
      {statusLabel(status)}
    </span>
  )
}
