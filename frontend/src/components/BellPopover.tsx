import { useLayoutEffect, useRef, useState, useSyncExternalStore } from 'react'
import * as PopoverPrimitive from '@radix-ui/react-popover'
import { Icon } from './ui/icon'
import { useJobs } from '../api/jobs'
import { useFiringAlerts } from '../api/alerts'
import { alertToastSeverity } from '../api/live'
import type { JobRow } from '../api/jobs'
import { actionLabel, ago, gerundFor, targetLabel } from '../lib/activityDisplay'
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

/** Rough height of the shortest possible card plus its gap, used only for the
 *  first paint, before the real cards can be measured. */
const CARD_ESTIMATE_PX = 84

/** How much of the viewport the popover cannot use: the topbar it hangs from,
 *  its sideOffset, and a margin below the last card. */
const CHROME_PX = 96

/** How many cards fit in the window, measured rather than guessed.
 *
 *  Card height is not constant (a failure's message wraps to however many
 *  lines its error needs), so a fixed divisor either clips the last card or
 *  wastes a slot. The guard against setting an unchanged value is what stops a
 *  resize from looping.
 *
 *  In jsdom every offsetHeight is 0, so the measurement is skipped and the
 *  ceiling stands. */
function useFittingCount(
  listRef: React.RefObject<HTMLDivElement | null>,
  open: boolean,
  total: number,
) {
  const [count, setCount] = useState(() =>
    Math.max(1, Math.min(MAX_VISIBLE, Math.floor((window.innerHeight - CHROME_PX) / CARD_ESTIMATE_PX))))

  /** The count that was tried and did not fit, at one particular window height.
   *  Without it, growth and shrink fight: a card that overflows shrinks back,
   *  leaving room that looks like space for another. Forgotten on resize. */
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
        // Overflowed. Shrink to what fits, and remember that one more does
        // not, so the growth branch cannot immediately undo it.
        blocked.current = { available, count: n + 1 }
        const fitted = Math.max(1, n)
        setCount((cur) => (cur === fitted ? cur : fitted))
        return
      }

      // Everything rendered fits, so the window may have grown. The loop above
      // can only count cards that are RENDERED, so growing one at a time is
      // what gives it something new to measure. The next card's height cannot
      // be guessed in advance.
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
import { Button } from './ui/button'
import { Dialog } from './ui/dialog'
import { JobLog } from './JobLog'
import { LoadingBlock } from './ui/loading'
import { NotificationCard } from './ui/notification-card'
import type { NotificationSeverity } from './ui/notification-card'

/** The tray's own empty/error placeholder, sized to sit alongside the
 *  NotificationCards it stands in for rather than EmptyState's page-level
 *  `py-20`, which read as a mostly blank rectangle inside a 400px popover.
 *  Borrows NotificationCard's chrome so it reads as a card. */
function TrayEmptyState({ title, note }: { title: string; note: string }) {
  return (
    <div className="rounded-ctl border border-line bg-panel px-3 py-2.5 text-center shadow-lg">
      <h2 className="font-display text-[16px] text-text-2">{title}</h2>
      <p className="mt-1 text-[12.5px] text-text-3">{note}</p>
    </div>
  )
}

/** Card severity from a job's status. Dismiss hides the card locally: /jobs is
 *  a server-side record, not an inbox, so there is nothing to mark read. */
function severityOf(status: string): NotificationSeverity {
  if (status === 'succeeded') return 'success'
  if (status === 'failed') return 'destructive'
  if (status === 'canceled' || status === 'interrupted') return 'warning'
  return 'info'
}

/** The message. A failure's reason is the message; anything else states what
 *  happened in a sentence. Every branch names the ACTION as well as the target,
 *  or the row reads "Finished on anytype-server on node1", which doubles the
 *  "on" now that target_name carries "<guest> on <node>". `verb` is null for a
 *  kind nobody has written a gerund for, and new kinds arrive regularly: the
 *  plainer fallback beats invented English. */
function messageOf(job: JobRow): string {
  if (job.error) return job.error
  const where = targetLabel(job) ?? 'this cluster'
  const verb = gerundFor(job.kind)
  if (job.status === 'succeeded') {
    return verb ? `Finished ${verb} ${where}.` : `Finished on ${where}.`
  }
  if (job.status === 'canceled') {
    return verb ? `Canceled before it finished ${verb} ${where}.`
                : `Canceled before it finished on ${where}.`
  }
  if (job.status === 'interrupted') {
    return verb ? `Interrupted while ${verb} ${where}; it may not have completed.`
                : `Interrupted on ${where}; it may not have completed.`
  }
  if (job.status === 'queued') {
    return verb ? `Queued to start ${verb} ${where}, not started yet.`
                : `Queued for ${where}, not started yet.`
  }
  // Sentence-cased rather than a template, because the verb IS the first word
  // here: "Installing anytype-server on node1."
  return verb ? `${verb[0].toUpperCase()}${verb.slice(1)} ${where}.`
              : `Running on ${where}.`
}

function duration(job: JobRow): string | null {
  if (!job.started_at || !job.finished_at) return null
  const ms = new Date(job.finished_at).getTime() - new Date(job.started_at).getTime()
  if (!Number.isFinite(ms) || ms < 0) return null
  return ms < 1000 ? `${ms}ms` : ms < 60_000 ? `${(ms / 1000).toFixed(1)}s`
                                             : `${Math.round(ms / 60_000)}m`
}

/** One line of context under the message: what it touched, how far along, and
 *  how long ago. More detail than that buried the message it supports. */
function footerOf(job: JobRow): string {
  const bits: string[] = []
  const where = targetLabel(job)
  if (where) bits.push(where)
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
 *  individually dismissed ids above it. `state` is undefined before the first
 *  load: nothing is hidden yet rather than everything. */
function isPersistedDismissed(state: DismissedState | undefined, jobId: number): boolean {
  if (!state) return false
  if (state.cleared_through_job_id != null && jobId <= state.cleared_through_job_id) return true
  return (state.dismissed_job_ids ?? []).includes(jobId)
}

/**
 * The bell's popover, over GET /jobs, the one source carrying the `error` field
 * this surface has to show.
 *
 * A popover rather than DropdownMenu: this list holds buttons and an expandable
 * log, and DropdownMenu's role="menu" semantics hijack arrow keys and expect
 * role="menuitem" children.
 */
export function BellPopover() {
  const [open, setOpen] = useState(false)
  // Keyed by TrayItem.id ('job:<id>', 'action:...', 'alert:...'), not a job's
  // numeric id: the tray holds more than jobs, and one key lets one dismiss
  // handler and one Clear all cover all of it.
  const [dismissed, setDismissed] = useState<Set<string>>(new Set())
  // Which job's transcript is open. This is the only path to
  // GET /jobs/{id}/events for a job you did not start in this session.
  const [logJob, setLogJob] = useState<JobRow | null>(null)
  const listRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)

  function openChange(next: boolean) {
    setOpen(next)
    // Opening marks "now" as seen (the badge counts what arrived since) and
    // tells NotificationSurface to stay quiet: a banner must never sit on top
    // of the popover the user opened by hand.
    setTrayOpen(next)
  }

  /** align="end" pins the cards to the BELL's right edge, and the bell is not
   *  the rightmost control, so that left a wide gap. alignOffset runs toward
   *  the START for align="end", so a positive value moves the cards LEFT: hence
   *  the negation. Measured, not hardcoded. */
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


  // The badge counts exactly what the tray holds, nothing cleverer. An unread
  // tally instead read as broken, because a quiet page with no jobs in flight
  // sat at zero while the tray plainly had items in it.
  const storeItems = useSyncExternalStore(subscribeNotifications, getNotifications, getNotifications)

  // GET /jobs already orders newest-first server-side. Do not re-sort here:
  // string-comparing ISO created_at reproduces the zero-microsecond tie bug the
  // backend explicitly avoids, since a bare 'Z' sorts after a fractional suffix
  // like '.123456Z'. Always enabled, not only while open, because the badge
  // counts what the tray holds.
  const jobsQuery = useJobs()
  const firingAlerts = useFiringAlerts()

  // Server-side memory of what THIS user already cleared, so a clear survives
  // a reload, a reboot, and a login from another browser, which component state
  // alone cannot do. Only job-backed items are covered.
  const dismissedQuery = useDismissedState()
  const dismissJobMutation = useDismissJob()
  const clearAllMutation = useClearAllDismissed()

  const toJobItem = (j: JobRow): TrayItem => ({
    id: `job:${j.id}`,
    severity: severityOf(j.status),
    // Status in the title, not only in severityOf's colour: a card headed
    // "App Uninstall" over a red icon leaves the reader working out whether the
    // container is gone. actionLabel spells it out. No "#12" after it: that is
    // the jobs table's primary key and means nothing to the reader.
    title: actionLabel(j.kind, j.status),
    description: messageOf(j),
    footer: footerOf(j),
    progress: progressOf(j),
    jobId: j.id,
    timestamp: new Date(j.created_at).getTime(),
  })

  // Firing alerts read from the server, not only from SSE: otherwise an
  // unreachable host or a lost quorum reached the tray only if the tab was open
  // when the event fired, and vanished on reload. `alertToastSeverity` is the
  // same mapping LiveProvider uses, so an alert cannot look different before
  // and after a refresh.
  const alertItems: TrayItem[] = (firingAlerts.data ?? []).map((a) => ({
    // Prefixed `alert:<id>` so notificationMerge can drop the SSE copy of the
    // same alert; the shape matches notificationStore's own ids.
    id: `alert:${a.id}`,
    severity: alertToastSeverity('err', a.severity),
    title: a.rule_name ?? 'Alert',
    description: a.message ?? undefined,
    footer: a.target_label ?? undefined,
    timestamp: a.fired_at ? new Date(a.fired_at).getTime() : Date.now(),
  }))

  // A job delivered once over SSE and again on the next GET /jobs poll must
  // render once, not twice; see notificationMerge.ts.
  const merged = mergeNotifications(jobsQuery.data ?? [], storeItems, toJobItem,
                                    alertItems)
  const undismissed = merged.filter((m) => !dismissed.has(m.id)
    && !(m.jobId != null && isPersistedDismissed(dismissedQuery.data, m.jobId)))
  // Fail open on the LIST, hold on the FILTER. isPersistedDismissed answers
  // false for every id until GET /dismissed lands, which is right for a request
  // that FAILED and wrong while one is in flight: for that moment the tray and
  // the badge bring back everything the operator already cleared. Incomplete
  // beats wrong, so the count waits, but only on `isPending`: an ERRORED
  // dismissal query keeps fail-open, because then the state is not coming.
  const dismissalsUnknown = dismissedQuery.isPending
  const count = dismissalsUnknown ? 0 : undismissed.length
  // The fit loop needs to know how many cards COULD be shown, or it grows past
  // the end of the list on a tall window with few jobs.
  const visible = useFittingCount(listRef, open, undismissed.length)

  // `dismissed` hides the card the instant it is clicked: the round trip must
  // never be what the user waits on. It is never rolled back if that write
  // fails, since a card that vanished and reappeared unexplained is worse than
  // one that stays gone. notify.error surfaces the failure instead.
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
        {/* Red, and only when there is something to see: a badge showing 0
            has stopped meaning anything. text-ink keeps the number legible on
            --red in both themes. */}
        {count > 0 && (
          <span className="absolute -right-1 -top-1 min-w-4 rounded-full bg-red px-1 text-center font-mono text-[9px] leading-4 text-ink">
            {count > 99 ? '99+' : count}
          </span>
        )}
      </PopoverPrimitive.Trigger>

      <PopoverPrimitive.Portal>
        {/* No panel, no header: a bordered box titled "Activity" around the
            cards read as an activity list, the one thing this was asked not to
            be. The cards ARE the popover. */}
        <PopoverPrimitive.Content
          ref={listRef}
          align="end"
          sideOffset={8}
          alignOffset={alignOffset}
          // Without this the shift above is clamped back by collision
          // detection to Radix's own padding, undoing it.
          collisionPadding={EDGE_GAP_PX}
          // Radix moves focus to the first TABBABLE element of the content on
          // open, and a NotificationCard's icon-only controls open their tooltip
          // on FOCUS as well as hover, so clicking the bell popped a tooltip
          // with the pointer nowhere near it. Focusing the content ITSELF
          // avoids that: FocusScope already puts tabIndex={-1} here, and a
          // container precedes its children in tab order, so one Tab still
          // walks into the cards. Focus must stay INSIDE the popover; on the
          // bell it would tab into the topbar.
          onOpenAutoFocus={(event) => {
            event.preventDefault()
            listRef.current?.focus()
          }}
          className="z-30 flex w-[400px] max-w-[92vw] flex-col gap-2 bg-transparent p-0"
        >
          {/* An action notification (nothing to do with /jobs) has to show up
              here even if /jobs is loading or failed: the two sources are
              independent. The states below are about the MERGED list. */}
          {undismissed.length === 0 && jobsQuery.isError ? (
            <TrayEmptyState title="Notifications not readable"
                            note="Proxploy could not reach the backend." />
          ) : (undismissed.length === 0 || dismissalsUnknown)
              && (dismissalsUnknown || jobsQuery.isPending || jobsQuery.data === undefined) ? (
            <LoadingBlock />
          ) : undismissed.length === 0 ? (
            <TrayEmptyState title="Nothing to report."
                            note="Installs, lifecycle actions and backups show up here." />
          ) : (
            <>
              {/* Only from two cards up: one card already has its own x, so
                  a clear-all beside it would be two controls for one
                  action. */}
              {undismissed.length >= 2 && (
                <Button type="button" variant="ghost" size="sm"
                  onClick={clearAll} className="self-end shadow-lg">
                  Clear all ({undismissed.length})
                </Button>
              )}
              {/* As many as fit, and no scrollbar: dismissing one reveals the
                  next, so the backlog drains through the x. */}
              {undismissed.slice(0, visible).map((item) => {
                // Only a job the /jobs poll has confirmed has a log to view;
                // a store entry whose SSE delivery beat the next poll has no
                // server row to fetch one from.
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
      {/* `fit` instead of a width: the transcript decides how big it wants to
          be, up to 80vw/80vh. The Close button is the same ghost button every
          other JobLog dialog ends with; without it a log opened from the tray
          had no visible way out. shrink-0 keeps it out of the flexbox shrinking
          the transcript absorbs. */}
      {logJob && (
        <Dialog title={actionLabel(logJob.kind, logJob.status)}
                description={logJob.error ?? undefined}
                fit
                onClose={() => setLogJob(null)}>
          <JobLog jobId={logJob.id} height="fill" />
          <Button className="mt-3 shrink-0" variant="ghost"
                  onClick={() => setLogJob(null)}>Close</Button>
        </Dialog>
      )}
    </>
  )
}
