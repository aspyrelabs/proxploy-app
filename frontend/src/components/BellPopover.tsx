import { useState } from 'react'
import * as PopoverPrimitive from '@radix-ui/react-popover'
import { useQuery } from '@tanstack/react-query'
import { BellIcon } from '@heroicons/react/24/outline'
import { toast } from 'sonner'
import { ApiError, api } from '../api/client'
import { TERMINAL, useCancelJob, useJobs } from '../api/jobs'
import type { JobRow } from '../api/jobs'
import { ago, TINT } from './activityDisplay'
import { JobLog } from './JobLog'
import { QueryState } from './QueryState'
import { Button } from './ui/button'

/** Doc 05 `POST /jobs/{id}/cancel`: only a job that hasn't reached a terminal
 *  state can be cancelled. Same rule ActivityFeed's isCancellable encodes,
 *  against TERMINAL rather than a locally re-listed 'running' | 'queued'. */
function isCancellable(job: JobRow): boolean {
  return !TERMINAL.includes(job.status)
}

function JobItem({ job, expanded, onToggle }: {
  job: JobRow
  expanded: boolean
  onToggle: () => void
}) {
  const cancel = useCancelJob()
  const tint = TINT[job.status] ?? 'bg-panel-2 text-text-3'

  const onCancel = (e: React.MouseEvent) => {
    e.stopPropagation()
    cancel.mutate(job.id, {
      onError: (err) => {
        const detail = err instanceof ApiError && typeof (err.body as Record<string, unknown>)?.detail === 'string'
          ? (err.body as Record<string, unknown>).detail as string
          : 'Could not cancel that job.'
        toast.error(detail)
      },
    })
  }

  return (
    <div data-testid="bell-job" className="border-b border-line-soft px-3 py-2.5 last:border-b-0">
      <div className="flex items-start gap-2">
        <button className="min-w-0 flex-1 text-left" onClick={onToggle}>
          <span className={`inline-block rounded-tile px-1.5 py-0.5 font-mono text-[10px] uppercase ${tint}`}>
            {job.status}
          </span>
          <div className="mt-1 truncate font-mono text-[12.5px] text-text">
            {job.kind} #{job.id}
          </div>
          <div className="truncate font-mono text-[11px] text-text-3">
            {job.target_type ?? 'system'}{job.target_id != null ? ` ${job.target_id}` : ''} · {ago(job.created_at)}
          </div>
        </button>
        {isCancellable(job) && (
          <Button variant="ghost" className="shrink-0 px-2 py-1 text-[11px]"
                  disabled={cancel.isPending} onClick={onCancel}>
            Cancel
          </Button>
        )}
      </div>
      {job.error && <div className="mt-1.5 text-[11.5px] text-red">{job.error}</div>}
      {expanded && <div className="mt-2"><JobLog jobId={job.id} /></div>}
    </div>
  )
}

/**
 * The bell's popover: what the activity drawer used to show, without the
 * full-height sheet. Reads GET /jobs (not /cluster/activity — ActivityRow
 * has no `error` field, and this is the one surface that has to show it).
 *
 * A popover rather than DropdownMenu: this list holds buttons (Cancel) and
 * an expandable log, and DropdownMenu's role="menu" semantics hijack arrow
 * keys and expect role="menuitem" children, neither of which fits.
 */
export function BellPopover() {
  const [open, setOpen] = useState(false)
  const [expandedId, setExpandedId] = useState<number | null>(null)

  // GET /cluster/activity applies LIMIT 20 to its jobs subquery ordered by
  // created_at desc, so a long-running job older (by creation time) than the
  // 20 most-recently-created jobs would silently drop out of that feed while
  // still running. The bell's count needs to be unbounded, so it runs its own
  // one-shot query against /jobs?status=running instead of riding useJobs,
  // which would coincidentally couple this always-mounted badge to whatever
  // poll interval the popover's own list carries.
  const { data: running } = useQuery({
    queryKey: ['jobs', 'running-count'],
    queryFn: () => api<JobRow[]>('/jobs?status=running'),
    refetchInterval: 30_000,
  })
  const count = running?.length ?? 0

  // GET /jobs already orders newest-first server-side. Do not re-sort here:
  // string-comparing ISO created_at timestamps client-side reproduces the
  // zero-microsecond tie bug the backend explicitly avoids (a bare 'Z' sorts
  // after a fractional-second suffix like '.123456Z', so a zero-microsecond
  // row would sort as newer than a genuinely later same-second row).
  const jobsQuery = useJobs({ enabled: open })

  return (
    <PopoverPrimitive.Root
      open={open}
      onOpenChange={(next) => { setOpen(next); if (!next) setExpandedId(null) }}
    >
      <PopoverPrimitive.Trigger
        aria-label="Activity"
        className="relative grid h-8 w-8 place-items-center rounded-tile bg-panel-2 text-text-2 hover:bg-elev"
      >
        <BellIcon aria-hidden className="h-[18px] w-[18px]" />
        {count > 0 && (
          // --amber-ink is not a token in tokens.css; this literal predates
          // this change and is left as-is rather than inventing one.
          <span className="absolute -right-1 -top-1 rounded-full bg-amber px-1 font-mono text-[9px] text-[#20160a]">
            {count}
          </span>
        )}
      </PopoverPrimitive.Trigger>

      <PopoverPrimitive.Portal>
        <PopoverPrimitive.Content
          align="end"
          sideOffset={8}
          className="z-30 w-96 max-w-[92vw] overflow-hidden rounded-card border border-line bg-panel shadow-[0_12px_32px_rgba(0,0,0,.35)]"
        >
          <div className="border-b border-line-soft px-3 py-2.5">
            <p className="font-display text-[13px] font-semibold text-text">Activity</p>
          </div>
          {/* Scrolls rather than growing past the viewport: a busy cluster can
              easily have 50+ jobs, and the popover is not a full-height sheet. */}
          <div className="max-h-[60vh] overflow-y-auto">
            <QueryState query={jobsQuery}
                        emptyTitle="No jobs yet."
                        emptyNote="Lifecycle actions, installs and backups show up here."
                        errorTitle="Activity not readable"
                        errorNote="Proxploy could not reach the backend to list recent jobs.">
              {(jobs) => (
                <>
                  {jobs.map((j) => (
                    <JobItem
                      key={j.id}
                      job={j}
                      expanded={expandedId === j.id}
                      onToggle={() => setExpandedId((cur) => (cur === j.id ? null : j.id))}
                    />
                  ))}
                </>
              )}
            </QueryState>
          </div>
        </PopoverPrimitive.Content>
      </PopoverPrimitive.Portal>
    </PopoverPrimitive.Root>
  )
}
