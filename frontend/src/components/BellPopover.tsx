import { useLayoutEffect, useRef, useState } from 'react'
import * as PopoverPrimitive from '@radix-ui/react-popover'
import { useQuery } from '@tanstack/react-query'
import { BellIcon } from '@heroicons/react/24/outline'
import { api } from '../api/client'
import { useJobs } from '../api/jobs'
import type { JobRow } from '../api/jobs'
import { ago } from './activityDisplay'

/** How close the cards sit to the right edge of the window. */
const EDGE_GAP_PX = 5

/** Hard ceiling on cards, however tall the window is. */
const MAX_VISIBLE = 15

/** Rough height of the shortest possible card plus its gap. Only used for the
 *  first paint, before the real cards can be measured — see useFittingCount. */
const CARD_ESTIMATE_PX = 84

/** How much of the viewport the popover cannot use: the topbar it hangs from,
 *  its own sideOffset, and a margin so the last card is not flush to the edge. */
const CHROME_PX = 96

/** How many cards fit in the window, measured rather than guessed.
 *
 *  Card height is not constant — a failure's message wraps to however many
 *  lines its error needs — so dividing by a fixed constant either clips the
 *  last card or wastes a slot. This estimates on the first paint, then measures
 *  the cards actually rendered and settles on the real number.
 *
 *  It converges in one extra pass because a card's height does not depend on
 *  how many are shown; the guard against setting an unchanged value is what
 *  stops a resize from looping.
 *
 *  In jsdom every offsetHeight is 0, so the measurement is skipped entirely and
 *  the ceiling stands — tests assert on MAX_VISIBLE, not on layout. */
function useFittingCount(listRef: React.RefObject<HTMLDivElement | null>, open: boolean) {
  const [count, setCount] = useState(() =>
    Math.max(1, Math.min(MAX_VISIBLE, Math.floor((window.innerHeight - CHROME_PX) / CARD_ESTIMATE_PX))))

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
      // At least one, even on a window too short for it: a clipped card beats
      // a popover that opens empty and looks broken.
      const fitted = Math.max(1, Math.min(MAX_VISIBLE, n))
      setCount((cur) => (cur === fitted ? cur : fitted))
    }
    fit()
    window.addEventListener('resize', fit)
    return () => window.removeEventListener('resize', fit)
  })

  return count
}
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
 *  that carried status, requester and schedule too — that much detail buried
 *  the message it was there to support. What survives is what you actually
 *  scan for: what it touched, how far along, and how long ago. */
function footerOf(job: JobRow): string {
  const bits: string[] = []
  if (job.target_type) {
    bits.push(`${job.target_type}${job.target_id != null ? ` ${job.target_id}` : ''}`)
  }
  if (job.progress_pct != null && job.status === 'running') bits.push(`${job.progress_pct}%`)
  const took = duration(job)
  if (took) bits.push(took)
  bits.push(ago(job.started_at ?? job.created_at))
  return bits.join(' · ')
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
  const listRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)

  /** align="end" pins the cards to the BELL's right edge, and the bell is not
   *  the rightmost control — the account menu is — so that left a wide gap.
   *  Radix's alignOffset is a crossAxis offset (positive = right for a
   *  bottom-side popover), so this measures how far the bell sits from the
   *  window edge and shifts by exactly that, less the gap we want to keep. */
  const [alignOffset, setAlignOffset] = useState(0)
  useLayoutEffect(() => {
    if (!open) return
    const place = () => {
      const el = triggerRef.current
      if (!el) return
      const { right } = el.getBoundingClientRect()
      const shift = Math.max(0, window.innerWidth - EDGE_GAP_PX - right)
      setAlignOffset((cur) => (cur === shift ? cur : shift))
    }
    place()
    window.addEventListener('resize', place)
    return () => window.removeEventListener('resize', place)
  })
  const visible = useFittingCount(listRef, open)

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
        ref={triggerRef}
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
          ref={listRef}
          align="end"
          sideOffset={8}
          alignOffset={alignOffset}
          // Without this the shift above is clamped back by collision
          // detection to Radix's own padding, undoing it.
          collisionPadding={EDGE_GAP_PX}
          className="z-30 flex w-[400px] max-w-[92vw] flex-col gap-2 bg-transparent p-0"
        >
          <QueryState query={jobsQuery}
                      emptyTitle="Nothing to report."
                      emptyNote="Installs, lifecycle actions and backups show up here."
                      errorTitle="Notifications not readable"
                      errorNote="Proxploy could not reach the backend.">
            {(jobs) => (
              <>
                {/* As many as fit, and no scrollbar: dismissing one is what
                    reveals the next, so the backlog drains through the x rather
                    than through a scroll nobody asked for. */}
                {jobs.filter((j) => !dismissed.includes(j.id)).slice(0, visible).map((j) => (
                  <NotificationCard
                    key={j.id}
                    severity={severityOf(j.status)}
                    title={`${j.kind} #${j.id}`}
                    description={messageOf(j)}
                    footer={footerOf(j)}
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
