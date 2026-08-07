import { useActivity } from '../api/jobs'
import type { ActivityRow } from '../api/jobs'
import { useActivityDrawer } from './ActivityDrawer'
import { QueryState } from './QueryState'

const TINT: Record<string, string> = {
  succeeded: 'bg-green-dim text-green',
  ok: 'bg-green-dim text-green',
  resolved: 'bg-green-dim text-green',
  failed: 'bg-red-dim text-red',
  error: 'bg-red-dim text-red',
  denied: 'bg-red-dim text-red',
  firing: 'bg-red-dim text-red',
  running: 'bg-blue-dim text-blue',
  queued: 'bg-blue-dim text-blue',
  canceled: 'bg-panel-2 text-text-3',
  interrupted: 'bg-amber-dim text-amber',
}

const BADGE: Record<string, string> = { job: 'JOB', audit: 'AUD', alert: 'ALT' }

function ago(iso: string): string {
  const s = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000))
  if (s < 60) return `${s}s ago`
  if (s < 3600) return `${Math.round(s / 60)}m ago`
  if (s < 86400) return `${Math.round(s / 3600)}h ago`
  return `${Math.round(s / 86400)}d ago`
}

function Item({ row, onOpen }: { row: ActivityRow; onOpen: () => void }) {
  const tint = TINT[row.status ?? ''] ?? 'bg-panel-2 text-text-3'
  const clickable = row.job_id != null
  const Wrapper = clickable ? 'button' : 'div'
  return (
    <Wrapper
      {...(clickable ? { onClick: onOpen, type: 'button' as const } : {})}
      className={`flex w-full items-start gap-3 py-2 text-left ${clickable ? 'hover:bg-panel-2' : ''}`}
    >
      <span className={`mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-tile font-mono text-[10px] uppercase ${tint}`}>
        {BADGE[row.kind] ?? ', '}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block font-mono text-[12.5px] text-text">{row.title}</span>
        <span className="block font-mono text-[11px] text-text-3">
          {row.status ?? ', '}
          {row.target_type ? ` · ${row.target_type}${row.target_id != null ? ` ${row.target_id}` : ''}` : ''}
          {row.actor ? ` · ${row.actor}` : ''} · {ago(row.at)}
        </span>
      </span>
    </Wrapper>
  )
}

/** Doc 06 `ActivityFeed`: dashboard + activity drawer share this row pattern. */
export function ActivityFeed({ limit = 8 }: { limit?: number }) {
  const activity = useActivity(limit)
  const drawer = useActivityDrawer()
  return (
    <QueryState query={activity}
                emptyTitle="Nothing has happened yet."
                emptyNote="Lifecycle actions, installs and backups land here."
                errorTitle="Activity not readable"
                errorNote="Proxploy could not reach the backend to list recent activity.">
      {(data) => (
        <div className="divide-y divide-line-soft">
          {data.slice(0, limit).map((row) => (
            <Item key={`${row.kind}:${row.id}`} row={row}
                  onOpen={() => row.job_id != null && drawer.openJob(row.job_id)} />
          ))}
        </div>
      )}
    </QueryState>
  )
}
