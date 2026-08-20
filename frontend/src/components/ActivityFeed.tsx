import { ApiError } from '../api/client'
import { notify } from '../lib/notify'
import { TERMINAL, useActivity, useCancelJob } from '../api/jobs'
import type { ActivityRow, JobStatus } from '../api/jobs'
import { actionLabel, ago, statusLabel, TINT } from '../lib/activityDisplay'
import { QueryState } from './QueryState'
import { Button } from './ui/button'
import { Loading } from './ui/loading'
import { SkeletonAvatar, SkeletonGroup } from './ui/skeleton'

const BADGE: Record<string, string> = { job: 'JOB', audit: 'AUD', alert: 'ALT' }

/** Doc 05 `POST /jobs/{id}/cancel`: only a job row that hasn't reached a
 *  terminal state can be cancelled: an audit/alert row has no job to
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
        notify.error(detail)
      },
    })
  }

  return (
    <div className="flex w-full items-start gap-3 py-2 text-left">
      <span className={`mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-tile font-mono text-[10px] uppercase ${tint}`}>
        {BADGE[row.kind] ?? 'unknown'}
      </span>
      <span className="min-w-0 flex-1">
        {/* An alert's title is the rule's own name, already written for a
            person; only job kinds and audit actions are raw identifiers.
            The status goes in as well as under: a denied row reads "Blocked
            VM Delete", so the title says nothing happened without the reader
            having to check the line beneath it. */}
        <span className="block text-[12.5px] text-text">
          {row.kind === 'alert' ? row.title : actionLabel(row.title, row.status)}
        </span>
        <span className="block font-mono text-[11px] text-text-3">
          {statusLabel(row.status)}
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

/** Doc 06 `ActivityFeed`: dashboard row pattern.
 *
 *  CURRENTLY UNRENDERED. The Hosts page dropped its Recent activity section
 *  when Apps and Virtual machines were stacked in its place, and nothing
 *  else mounts this component either, so it has no page today.
 *
 *  Kept rather than deleted, following the same rule LivePulse in
 *  LiveProvider.tsx uses for the same situation: hide the surface, keep the
 *  code, say why. Deleting it along with its endpoint and the query
 *  invalidation call sites that feed it is a separate decision nobody has
 *  made yet. */
export function ActivityFeed({ limit = 8 }: { limit?: number }) {
  const activity = useActivity(limit)
  return (
    <QueryState query={activity}
                // `limit` rows, not a fixed number: this feed is 8 rows on
                // the dashboard and a longer one on the Hosts page, and a
                // placeholder of the wrong length moves whatever sits under
                // it when the real rows arrive.
                loading={<SkeletonGroup label="Loading activity" className="divide-y divide-line-soft">
                  {Array.from({ length: limit }, (_, i) => (
                    // The kind badge (JOB/AUD/ALT) is a 28px tile, then the
                    // title line and the quieter status line under it, which
                    // is the Avatar arrangement exactly.
                    <SkeletonAvatar key={i} className="py-2" tile="h-7 w-7 rounded-tile"
                                    lines={['w-2/5 text-[12.5px]', 'w-3/5 text-[11px]']} />
                  ))}
                </SkeletonGroup>}
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
