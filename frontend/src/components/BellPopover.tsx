import { useState } from 'react'
import * as PopoverPrimitive from '@radix-ui/react-popover'
import { useQuery } from '@tanstack/react-query'
import { BellIcon } from '@heroicons/react/24/outline'
import { api } from '../api/client'
import { useJobs } from '../api/jobs'
import type { JobRow } from '../api/jobs'
import { ago } from './activityDisplay'
import { QueryState } from './QueryState'
import { NotificationCard } from './ui/notification-card'
import type { NotificationSeverity } from './ui/notification-card'

/** One notification, as a card.
 *
 *  The user asked for notification cards rather than a list, so this renders
 *  the same NotificationCard the live toasts use — same four severities, same
 *  x — instead of the bespoke row this popover shipped with. Dismiss hides the
 *  card locally: /jobs is a server-side record, not an inbox, so there is
 *  nothing to mark read; the x clears it from view until the query refetches.
 */
function severityOf(status: string): NotificationSeverity {
  if (status === 'succeeded') return 'success'
  if (status === 'failed') return 'destructive'
  if (status === 'canceled' || status === 'interrupted') return 'warning'
  return 'info'
}

function describe(job: JobRow): string {
  const where = `${job.target_type ?? 'system'}${job.target_id != null ? ` ${job.target_id}` : ''}`
  // A failure's reason is the whole point of showing it; the target and age
  // are context that follows it.
  return job.error ? `${job.error} — ${where} · ${ago(job.created_at)}`
                   : `${where} · ${ago(job.created_at)}`
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
  const [dismissed, setDismissed] = useState<number[]>([])

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
      onOpenChange={setOpen}
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
                  {jobs.filter((j) => !dismissed.includes(j.id)).map((j) => (
                    <div key={j.id} className="px-2 py-1.5">
                      <NotificationCard
                        severity={severityOf(j.status)}
                        title={`${j.kind} #${j.id}`}
                        description={describe(j)}
                        onDismiss={() => setDismissed((d) => [...d, j.id])}
                      />
                    </div>
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
