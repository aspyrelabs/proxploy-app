import { statusLabel } from '../lib/activityDisplay'
import { Spinner } from './ui/spinner'

// `unknown` (grey) = could not determine; `stopped` (red) = not running. Kept
// visually distinct on purpose.
const STYLES: Record<string, string> = {
  running: 'bg-green-dim text-green',
  connected: 'bg-green-dim text-green',
  online: 'bg-green-dim text-green',
  stopped: 'bg-red-dim text-red',
  paused: 'bg-amber-dim text-amber',
  pending: 'bg-amber-dim text-amber',
  removing: 'bg-red-dim text-red',
  unreachable: 'bg-red-dim text-red',
  error: 'bg-red-dim text-red',
  unknown: 'bg-panel-2 text-text-3',
}

export function StatusPill({ status }: { status: string }) {
  const working = status === 'pending' || status === 'removing'
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 font-mono text-[10.5px] uppercase ${STYLES[status] ?? STYLES.unknown}`}>
      {working
        ? <Spinner className="size-2.5" />
        : <span className="h-1.5 w-1.5 rounded-full bg-current" />}
      {statusLabel(status)}
    </span>
  )
}
