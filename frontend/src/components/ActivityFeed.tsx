import { toast } from 'sonner'
import { ApiError } from '../api/client'
import { TERMINAL, useActivity, useCancelJob } from '../api/jobs'
import type { ActivityRow, JobStatus } from '../api/jobs'
import { ago, TINT } from './activityDisplay'
import { QueryState } from './QueryState'
import { Button } from './ui/button'
import { Loading } from './ui/loading'

const BADGE: Record<string, string> = { job: 'JOB', audit: 'AUD', alert: 'ALT' }

/** Doc 05 `POST /jobs/{id}/cancel`: only a job row that hasn't reached a
 *  terminal state can be cancelled — an audit/alert row has no job to
 *  cancel, and a finished job has nothing left to stop. `TERMINAL` already
 *  encodes "still active" as its inverse in one place, so this reads off
 *  that rather than re-listing 'running' | 'queued' locally and risking the
 *  two definitions drifting apart. */
function isCancellable(row: ActivityRow): boolean {
  return row.kind === 'job' && row.status != null
    && !TERMINAL.includes(row.status as JobStatus)
}

function Item({ row }: { row: ActivityRow }) {
  const tint = TINT[row.status ?? ''] ?? 'bg-panel-2 text-text-3'
  const cancel = useCancelJob()

  const onCancel = (e: React.MouseEvent) => {
    e.stopPropagation()
    cancel.mutate(row.job_id ?? row.id, {
      onError: (err) => {
        const detail = err instanceof ApiError && typeof (err.body as Record<string, unknown>)?.detail === 'string'
          ? (err.body as Record<string, unknown>).detail as string
          : 'Could not cancel that job.'
        toast.error(detail)
      },
    })
  }

  return (
    <div className="flex w-full items-start gap-3 py-2 text-left">
      <span className={`mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-tile font-mono text-[10px] uppercase ${tint}`}>
        {BADGE[row.kind] ?? 'unknown'}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block font-mono text-[12.5px] text-text">{row.title}</span>
        <span className="block font-mono text-[11px] text-text-3">
          {row.status ?? 'unknown'}
          {row.target_type ? ` · ${row.target_type}${row.target_id != null ? ` ${row.target_id}` : ''}` : ''}
          {row.actor ? ` · ${row.actor}` : ''} · {ago(row.at)}
        </span>
      </span>
      {/* Only a job still running gets a determinate ring: a finished job's
          progress_pct (backfilled to 100 on success) is history, not a live
          figure, and a null one has no real value to show. */}
      {row.status === 'running' && row.progress_pct != null && (
        <Loading value={row.progress_pct} label="Progress" size={20} className="mt-0.5 shrink-0" />
      )}
      {isCancellable(row) && (
        <Button variant="ghost" className="shrink-0 self-center px-2 py-1 text-[11px]"
                disabled={cancel.isPending} onClick={onCancel}>
          Cancel
        </Button>
      )}
    </div>
  )
}

/** Doc 06 `ActivityFeed`: dashboard row pattern, also used on the Hosts page
 *  as the app's activity history now that the drawer is gone. */
export function ActivityFeed({ limit = 8 }: { limit?: number }) {
  const activity = useActivity(limit)
  return (
    <QueryState query={activity}
                emptyTitle="Nothing has happened yet."
                emptyNote="Lifecycle actions, installs and backups land here."
                errorTitle="Activity not readable"
                errorNote="Proxploy could not reach the backend to list recent activity.">
      {(data) => (
        <div className="divide-y divide-line-soft">
          {data.slice(0, limit).map((row) => (
            <Item key={`${row.kind}:${row.id}`} row={row} />
          ))}
        </div>
      )}
    </QueryState>
  )
}
