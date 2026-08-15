import { statusLabel } from '../lib/activityDisplay'

const STYLES: Record<string, string> = {
  running: 'bg-green-dim text-green',
  connected: 'bg-green-dim text-green',
  online: 'bg-green-dim text-green',
  stopped: 'bg-panel-2 text-text-3',
  paused: 'bg-amber-dim text-amber',
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
