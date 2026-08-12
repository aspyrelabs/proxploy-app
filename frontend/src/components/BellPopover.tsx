import { useLayoutEffect, useRef, useState, useSyncExternalStore } from 'react'
import * as PopoverPrimitive from '@radix-ui/react-popover'
import { useQuery } from '@tanstack/react-query'
import { Icon } from './ui/icon'
import { api } from '../api/client'
import { useJobs } from '../api/jobs'
import type { JobRow } from '../api/jobs'
import { ago } from './activityDisplay'
import { mergeNotifications } from '../lib/notificationMerge'
import type { TrayItem } from '../lib/notificationMerge'
import {
  clearNotifications, getLastSeenAt, getNotifications, removeNotification,
  setTrayOpen, subscribeNotifications,
} from '../lib/notificationStore'

/** How close the cards sit to the right edge of the window. */
const EDGE_GAP_PX = 5

/** Hard ceiling on cards, however tall the window is. */
const MAX_VISIBLE = 15

/** Rough height of the shortest possible card plus its gap. Only used for the
 *  first paint, before the real cards can be measured: see useFittingCount. */
const CARD_ESTIMATE_PX = 84

/** How much of the viewport the popover cannot use: the topbar it hangs from,
 *  its own sideOffset, and a margin so the last card is not flush to the edge. */
const CHROME_PX = 96

/** How many cards fit in the window, measured rather than guessed.
 *
 *  Card height is not constant (a failure's message wraps to however many
 *  lines its error needs), so dividing by a fixed constant either clips the
 *  last card or wastes a slot. This estimates on the first paint, then measures
 *  the cards actually rendered and settles on the real number.
 *
 *  It converges in one extra pass because a card's height does not depend on
 *  how many are shown; the guard against setting an unchanged value is what
 *  stops a resize from looping.
 *
 *  In jsdom every offsetHeight is 0, so the measurement is skipped entirely and
 *  the ceiling stands: tests assert on MAX_VISIBLE, not on layout. */
function useFittingCount(
  listRef: React.RefObject<HTMLDivElement | null>,
  open: boolean,
  total: number,
) {
  const [count, setCount] = useState(() =>
    Math.max(1, Math.min(MAX_VISIBLE, Math.floor((window.innerHeight - CHROME_PX) / CARD_ESTIMATE_PX))))

  /** The count that was tried and did not fit, at one particular window height.
   *  Without it, growth and shrink fight: adding a card that overflows shrinks
   *  back, leaving room that looks like space for another card, which gets
   *  added, which overflows. Forgotten as soon as the window resizes, because a
   *  different height deserves a fresh attempt. */
  const blocked = useRef<{ available: number; count: number } | null>(null)

  useLayoutEffect(() => {
    if (!open) return
    const fit = () => {
      const el = listRef.current
      if (!el) return
      const cards = Array.from(el.children) as HTMLElement[]
      const measured = cards.filter((c) => c.offsetHeight > 0)
      if (measured.length === 0) return   // jsdom, or not laid out yet
      const gap = 8
      const available = window.innerHeight - CHROME_PX

      let used = 0
      let n = 0
      for (const card of measured) {
        const next = used + card.offsetHeight + (n > 0 ? gap : 0)
        if (next > available) break
        used = next
        n += 1
      }

      if (n < measured.length) {
        // Overflowed. Shrink to what actually fits, and remember that one more
        // than that does not, so the growth branch cannot immediately undo it.
        blocked.current = { available, count: n + 1 }
        const fitted = Math.max(1, n)
        setCount((cur) => (cur === fitted ? cur : fitted))
        return
      }

      // Everything rendered fits, so the window may have grown. The loop above
      // can only count cards that are RENDERED, which is why shrinking used to
      // be a one-way ratchet: the measurement was bounded by its own previous
      // result, so a window that grew back had nothing new to measure.
      //
      // Growing one at a time re-renders, re-measures, and either keeps going
      // or trips the block above. That converges without guessing the next
      // card's height, which is unknowable in advance: a failure's message
      // wraps to however many lines its error needs.
      const isBlocked = blocked.current !== null
        && blocked.current.available === available
        && count + 1 >= blocked.current.count
      const room = available - used
      const shortest = Math.min(...measured.map((c) => c.offsetHeight))
      if (!isBlocked && count < MAX_VISIBLE && count < total && room >= shortest + gap) {
        setCount((cur) => Math.min(MAX_VISIBLE, total, cur + 1))
      }
    }
    fit()
    window.addEventListener('resize', fit)
    return () => window.removeEventListener('resize', fit)
  })

  return count
}
import { Dialog } from './ui/dialog'
import { JobLog } from './JobLog'
import { EmptyState } from './EmptyState'
import { LoadingBlock } from './ui/loading'
import { NotificationCard } from './ui/notification-card'
import type { NotificationSeverity } from './ui/notification-card'

/** One notification, as a card.
 *
 *  The user asked for notification cards rather than a list, so this renders
 *  the same NotificationCard the live toasts use (same four severities, same
 *  x) instead of the bespoke row this popover shipped with. Dismiss hides the
 *  card locally: /jobs is a server-side record, not an inbox, so there is
 *  nothing to mark read; the x clears it from view until the query refetches.
 */
function severityOf(status: string): NotificationSeverity {
  if (status === 'succeeded') return 'success'
  if (status === 'failed') return 'destructive'
  if (status === 'canceled' || status === 'interrupted') return 'warning'
  return 'info'
}

/** The message. A failure's reason is the message; anything else states what
 *  happened in a sentence rather than making the reader infer it from a kind
 *  string. */
function messageOf(job: JobRow): string {
  if (job.error) return job.error
  const where = job.target_type
    ? `${job.target_type}${job.target_id != null ? ` ${job.target_id}` : ''}`
    : 'this cluster'
  if (job.status === 'succeeded') return `Finished on ${where}.`
  if (job.status === 'canceled') return `Canceled before it finished on ${where}.`
  if (job.status === 'interrupted') return `Interrupted on ${where}; it may not have completed.`
  if (job.status === 'queued') return `Queued for ${where}, not started yet.`
  return `Running on ${where}.`
}

function duration(job: JobRow): string | null {
  if (!job.started_at || !job.finished_at) return null
  const ms = new Date(job.finished_at).getTime() - new Date(job.started_at).getTime()
  if (!Number.isFinite(ms) || ms < 0) return null
  return ms < 1000 ? `${ms}ms` : ms < 60_000 ? `${(ms / 1000).toFixed(1)}s`
                                             : `${Math.round(ms / 60_000)}m`
}

/** One line of context under the message. Trimmed from a label/value table
 *  that carried status, requester and schedule too: that much detail buried
 *  the message it was there to support. What survives is what you actually
 *  scan for: what it touched, how far along, and how long ago. */
function footerOf(job: JobRow): string {
  const bits: string[] = []
  if (job.target_type) {
    bits.push(`${job.target_type}${job.target_id != null ? ` ${job.target_id}` : ''}`)
  }
  // A running job's percent used to be folded in here as plain text; it now
  // renders as NotificationCard's own ring (see `progress` below) instead.
  const took = duration(job)
  if (took) bits.push(took)
  bits.push(ago(job.started_at ?? job.created_at))
  return bits.join(' · ')
}

/** 0..100 for a job still running with a real figure, or undefined: never a
 *  fake zero for a job that hasn't reported anything yet. */
function progressOf(job: JobRow): number | undefined {
  return job.status === 'running' && job.progress_pct != null ? job.progress_pct : undefined
}

/**
 * The bell's popover: what the activity drawer used to show, without the
 * full-height sheet. Reads GET /jobs (not /cluster/activity: ActivityRow
 * has no `error` field, and this is the one surface that has to show it).
 *
 * A popover rather than DropdownMenu: this list holds buttons (Cancel) and
 * an expandable log, and DropdownMenu's role="menu" semantics hijack arrow
 * keys and expect role="menuitem" children, neither of which fits.
 */
export function BellPopover() {
  const [open, setOpen] = useState(false)
  // Keyed by TrayItem.id ('job:<id>', 'action:...', 'alert:...'), not a
  // job's numeric id: the tray now holds more than jobs, and unifying the
  // key lets one dismiss handler (and one Clear all) cover all of it.
  const [dismissed, setDismissed] = useState<Set<string>>(new Set())
  // Which job's transcript is open. Deleting the drawer took the only path to
  // GET /jobs/{id}/events for a job you did not start in this session; this is
  // that path, without turning the cards back into a list.
  const [logJob, setLogJob] = useState<JobRow | null>(null)
  const listRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)

  function openChange(next: boolean) {
    setOpen(next)
    // Opening marks "now" as seen (the badge counts what arrived since),
    // and tells NotificationSurface to stay quiet while the tray itself is
    // showing the same information -- there is nothing the brief banner
    // could add, and it must never sit on top of the popover the user
    // already opened by hand.
    setTrayOpen(next)
  }

  /** align="end" pins the cards to the BELL's right edge, and the bell is not
   *  the rightmost control (the account menu is), so that left a wide gap.
   *
   *  alignOffset shifts along the alignment axis, and for align="end" it runs
   *  toward the START: a positive value moves the cards further LEFT, deeper
   *  into the window, which is the opposite of what is wanted here. Hence the
   *  negation. Measured, not hardcoded, so a longer display name in the
   *  account menu or a different tier pill cannot put it back out. */
  const [alignOffset, setAlignOffset] = useState(0)
  useLayoutEffect(() => {
    if (!open) return
    const place = () => {
      const el = triggerRef.current
      if (!el) return
      const { right } = el.getBoundingClientRect()
      const shift = Math.max(0, window.innerWidth - EDGE_GAP_PX - right)
      setAlignOffset((cur) => (cur === -shift ? cur : -shift))
    }
    place()
    window.addEventListener('resize', place)
    return () => window.removeEventListener('resize', place)
  })

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

  // The badge used to count only running jobs; the tray now also holds
  // action notifications and SSE-delivered job/alert events, and a badge
  // counting one thing while the tray shows another is the exact confusion
  // this change exists to remove. It now counts running jobs (still in
  // flight, still worth knowing about, and never absent from the tray while
  // true) plus whatever in the store arrived since the tray was last
  // opened -- an ordinary unread count, reset by opening the popover.
  const storeItems = useSyncExternalStore(subscribeNotifications, getNotifications, getNotifications)
  const unreadStoreCount = storeItems.filter((n) => n.createdAt > getLastSeenAt()).length
  const count = (running?.length ?? 0) + unreadStoreCount

  // GET /jobs already orders newest-first server-side. Do not re-sort here:
  // string-comparing ISO created_at timestamps client-side reproduces the
  // zero-microsecond tie bug the backend explicitly avoids (a bare 'Z' sorts
  // after a fractional-second suffix like '.123456Z', so a zero-microsecond
  // row would sort as newer than a genuinely later same-second row).
  const jobsQuery = useJobs({ enabled: open })

  const toJobItem = (j: JobRow): TrayItem => ({
    id: `job:${j.id}`,
    severity: severityOf(j.status),
    title: `${j.kind} #${j.id}`,
    description: messageOf(j),
    footer: footerOf(j),
    progress: progressOf(j),
    jobId: j.id,
    timestamp: new Date(j.created_at).getTime(),
  })

  // A job delivered once over SSE (LiveProvider pushes it into the store the
  // instant it lands) and again the next time GET /jobs is polled must
  // render once, not twice; see notificationMerge.ts.
  const merged = mergeNotifications(jobsQuery.data ?? [], storeItems, toJobItem)
  const undismissed = merged.filter((m) => !dismissed.has(m.id))
  // The fit loop needs to know how many cards COULD be shown, or it would keep
  // trying to grow past the end of the list on a tall window with few jobs.
  const visible = useFittingCount(listRef, open, undismissed.length)

  function dismissItem(item: TrayItem) {
    setDismissed((d) => new Set(d).add(item.id))
    removeNotification(item.id)
  }

  function clearAll() {
    setDismissed((d) => {
      const next = new Set(d)
      for (const item of merged) next.add(item.id)
      return next
    })
    clearNotifications()
  }

  return (
    <>
    <PopoverPrimitive.Root
      open={open}
      onOpenChange={openChange}
    >
      <PopoverPrimitive.Trigger
        ref={triggerRef}
        aria-label="Activity"
        className="relative grid h-8 w-8 place-items-center rounded-tile bg-panel-2 text-text-2 hover:bg-elev"
      >
        <Icon name="notifications" />
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
            and each card is its own floating surface: the cards ARE the
            popover. */}
        <PopoverPrimitive.Content
          ref={listRef}
          align="end"
          sideOffset={8}
          alignOffset={alignOffset}
          // Without this the shift above is clamped back by collision
          // detection to Radix's own padding, undoing it.
          collisionPadding={EDGE_GAP_PX}
          className="z-30 flex w-[400px] max-w-[92vw] flex-col gap-2 bg-transparent p-0"
        >
          {/* An action notification (nothing to do with /jobs) has to show up
              here even if /jobs itself is loading or failed to load: the two
              sources are independent, and a fetch error on one must not hide
              the other. The loading/error/empty states below are therefore
              about the MERGED list being empty, not about jobsQuery alone. */}
          {undismissed.length === 0 && jobsQuery.isError ? (
            <EmptyState title="Notifications not readable"
                        note="Proxploy could not reach the backend." />
          ) : undismissed.length === 0 && (jobsQuery.isPending || jobsQuery.data === undefined) ? (
            <LoadingBlock />
          ) : undismissed.length === 0 ? (
            <EmptyState title="Nothing to report."
                        note="Installs, lifecycle actions and backups show up here." />
          ) : (
            <>
              {/* Only shown from two cards up, mirroring the sonner-era
                  ClearAllToasts this replaces: one card already has its own
                  x, so a clear-all beside it would be two controls for one
                  action. */}
              {undismissed.length >= 2 && (
                <button type="button" onClick={clearAll}
                  className="self-end rounded-ctl border border-line bg-panel-2 px-2.5 py-1
                             text-[11px] text-text-2 shadow-lg transition hover:bg-elev hover:text-text">
                  Clear all ({undismissed.length})
                </button>
              )}
              {/* As many as fit, and no scrollbar: dismissing one is what
                  reveals the next, so the backlog drains through the x rather
                  than through a scroll nobody asked for. */}
              {undismissed.slice(0, visible).map((item) => {
                // Only a job the /jobs poll has actually confirmed has a log
                // to view; a store entry whose SSE delivery beat the next
                // poll has no server-confirmed row yet to fetch one from.
                const job = item.jobId != null
                  ? (jobsQuery.data ?? []).find((j) => j.id === item.jobId)
                  : undefined
                return (
                  <NotificationCard
                    key={item.id}
                    severity={item.severity}
                    title={item.title}
                    description={item.description}
                    footer={item.footer}
                    progress={item.progress}
                    onViewLog={job ? () => setLogJob(job) : undefined}
                    onDismiss={() => dismissItem(item)}
                  />
                )
              })}
            </>
          )}
        </PopoverPrimitive.Content>
      </PopoverPrimitive.Portal>
    </PopoverPrimitive.Root>
      {logJob && (
        <Dialog title={`${logJob.kind} #${logJob.id}`}
                description={logJob.error ?? undefined}
                width={720}
                onClose={() => setLogJob(null)}>
          <JobLog jobId={logJob.id} />
        </Dialog>
      )}
    </>
  )
}
