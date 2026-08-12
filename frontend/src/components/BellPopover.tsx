import { useLayoutEffect, useRef, useState, useSyncExternalStore } from 'react'
import * as PopoverPrimitive from '@radix-ui/react-popover'
import { Icon } from './ui/icon'
import { useJobs } from '../api/jobs'
import type { JobRow } from '../api/jobs'
import { ago } from './activityDisplay'
import { mergeNotifications } from '../lib/notificationMerge'
import type { TrayItem } from '../lib/notificationMerge'
import {
  clearNotifications, getNotifications, removeNotification,
  setTrayOpen, subscribeNotifications,
} from '../lib/notificationStore'
import { notify } from '../lib/notify'
import { useClearAllDismissed, useDismissedState, useDismissJob } from '../api/notificationDismissals'
import type { DismissedState } from '../api/notificationDismissals'

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

/** A job's id counts as already cleared if it is at or below the watermark
 *  ("clear all" as of some earlier moment) or sits in the small list of
 *  individually dismissed ids above it. `state` is undefined before the
 *  first load: nothing is hidden yet rather than everything, the same
 *  fail-open-to-visible choice jobsQuery.data ?? [] makes elsewhere in this
 *  file. */
function isPersistedDismissed(state: DismissedState | undefined, jobId: number): boolean {
  if (!state) return false
  if (state.cleared_through_job_id != null && jobId <= state.cleared_through_job_id) return true
  return (state.dismissed_job_ids ?? []).includes(jobId)
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


  // The badge counts exactly what the tray holds, nothing cleverer. It has
  // been two other things: running jobs only, then running jobs plus an unread
  // tally. Both meant the number on the icon described something other than the
  // list behind it, which is the confusion this tray exists to remove, and the
  // unread version read as broken because a quiet page with no jobs in flight
  // sat at zero while the tray plainly had items in it.
  const storeItems = useSyncExternalStore(subscribeNotifications, getNotifications, getNotifications)

  // GET /jobs already orders newest-first server-side. Do not re-sort here:
  // string-comparing ISO created_at timestamps client-side reproduces the
  // zero-microsecond tie bug the backend explicitly avoids (a bare 'Z' sorts
  // after a fractional-second suffix like '.123456Z', so a zero-microsecond
  // row would sort as newer than a genuinely later same-second row).
  // Always enabled, not only while open: the badge counts what the tray holds,
  // and it cannot know that if the list is only fetched on opening.
  const jobsQuery = useJobs()

  // Server-side memory of what THIS user already cleared, so a clear
  // survives a reload, a reboot, and a login from a different browser (the
  // requirement `dismissed` alone -- component state -- cannot meet; see
  // .superpowers/sdd/persist-cleared-notifications-report.md). Only job-
  // backed items are covered: a store item is already gone on reload, see
  // isPersistedDismissed and dismissItem/clearAll below.
  const dismissedQuery = useDismissedState()
  const dismissJobMutation = useDismissJob()
  const clearAllMutation = useClearAllDismissed()

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
  const undismissed = merged.filter((m) => !dismissed.has(m.id)
    && !(m.jobId != null && isPersistedDismissed(dismissedQuery.data, m.jobId)))
  const count = undismissed.length
  // The fit loop needs to know how many cards COULD be shown, or it would keep
  // trying to grow past the end of the list on a tall window with few jobs.
  const visible = useFittingCount(listRef, open, undismissed.length)

  // `dismissed` hides the card the instant it is clicked, before the write
  // below has landed -- the round trip must never be what the user waits on.
  // It is also never rolled back if that write fails: a card that vanished
  // and then reappeared moments later, unexplained, would be worse than one
  // that stays gone but risks not surviving a reload. notify.error is the
  // "not silently" half of that: the failure is surfaced, the hide is not.
  function dismissItem(item: TrayItem) {
    setDismissed((d) => new Set(d).add(item.id))
    removeNotification(item.id)
    if (item.jobId != null) {
      dismissJobMutation.mutate(item.jobId, {
        onError: () => notify.error('Could not save that notification as cleared.',
          { description: 'It may come back after a reload.' }),
      })
    }
  }

  function clearAll() {
    setDismissed((d) => {
      const next = new Set(d)
      for (const item of merged) next.add(item.id)
      return next
    })
    clearNotifications()
    clearAllMutation.mutate(undefined, {
      onError: () => notify.error('Could not save that the tray was cleared.',
        { description: 'Some notifications may come back after a reload.' }),
    })
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
        {/* Red, and only when there is something to see: a badge showing 0 is
            a badge that has stopped meaning anything. text-ink rather than a
            literal, so the number stays legible on --red in both themes (ink is
            near black on dark, near white on light). */}
        {count > 0 && (
          <span className="absolute -right-1 -top-1 min-w-4 rounded-full bg-red px-1 text-center font-mono text-[9px] leading-4 text-ink">
            {count > 99 ? '99+' : count}
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
