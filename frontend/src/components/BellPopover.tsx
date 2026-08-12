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
        {/* No panel, no header: a bordered box titled "Activity" wrapping the
            cards read as an activity list, which is the one thing this was
            asked not to be. The Content is a transparent, borderless column
            and each card is its own floating surface — the cards ARE the
            popover. */}
        <PopoverPrimitive.Content
          align="end"
          sideOffset={8}
          className="z-30 flex max-h-[70vh] w-[372px] max-w-[92vw] flex-col gap-2 overflow-y-auto bg-transparent p-0"
        >
          <QueryState query={jobsQuery}
                      emptyTitle="Nothing to report."
                      emptyNote="Installs, lifecycle actions and backups show up here."
                      errorTitle="Notifications not readable"
                      errorNote="Proxploy could not reach the backend.">
            {(jobs) => (
              <>
                {jobs.filter((j) => !dismissed.includes(j.id)).map((j) => (
                  <NotificationCard
                    key={j.id}
                    severity={severityOf(j.status)}
                    title={`${j.kind} #${j.id}`}
                    description={describe(j)}
                    onDismiss={() => setDismissed((d) => [...d, j.id])}
                  />
                ))}
              </>
            )}
          </QueryState>
        </PopoverPrimitive.Content>
      </PopoverPrimitive.Portal>
    </PopoverPrimitive.Root>
  )
}
