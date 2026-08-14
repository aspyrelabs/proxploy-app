/** The activity drawer was deleted in favour of toasts, but that also deleted
 *  the only UI path to an arbitrary job's log and its error text. This is
 *  the replacement: a popover anchored to the topbar bell, reading /jobs
 *  (not /cluster/activity, whose ActivityRow has no `error` field). */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { JobRow } from '../api/jobs'
import {
  getNotifications, pushAction, pushJobEvent, resetNotificationStore,
} from '../lib/notificationStore'

const { toastError } = vi.hoisted(() => ({ toastError: vi.fn() }))
vi.mock('sonner', () => ({ toast: { error: toastError, success: vi.fn() } }))

const { ApiError } = vi.hoisted(() => ({
  ApiError: class extends Error {
    status: number; body: unknown
    constructor(status: number, body: unknown) { super(`API ${status}`); this.status = status; this.body = body }
  },
}))

const JOBS: JobRow[] = [
  {
    id: 10, kind: 'app.start', status: 'running', target_type: 'app', target_id: 1,
    params: null, result: null, error: null, progress_pct: 40,
    requested_by: null, schedule_id: null, started_at: '2026-08-12T08:59:00Z',
    finished_at: null, created_at: '2026-08-12T08:59:00Z',
  },
  {
    id: 11, kind: 'app.stop', status: 'succeeded', target_type: 'app', target_id: 2,
    params: null, result: null, error: null, progress_pct: 100,
    requested_by: null, schedule_id: null, started_at: '2026-08-12T08:00:00Z',
    finished_at: '2026-08-12T08:01:00Z', created_at: '2026-08-12T08:00:00Z',
  },
  {
    id: 12, kind: 'vm.backup', status: 'failed', target_type: 'vm', target_id: 3,
    params: null, result: null, error: 'disk full: retry failed', progress_pct: null,
    requested_by: null, schedule_id: null, started_at: '2026-08-12T07:00:00Z',
    finished_at: '2026-08-12T07:05:00Z', created_at: '2026-08-12T07:00:00Z',
  },
]

let jobsResult: 'ok' | 'empty' | 'error' | 'many' = 'ok'
let cancelResult: 'ok' | 'forbidden' | 'conflict' = 'ok'
let jobEventsError = false
const cancelCalls: Array<{ path: string; method?: string }> = []

// Server-side "already cleared" state (see api/notificationDismissals.ts).
// Defaults to nothing cleared: the persisted-state checks below are inert
// unless a test sets this, so every pre-existing test above keeps its
// original meaning untouched.
let dismissedState: { cleared_through_job_id: number | null; dismissed_job_ids: number[] } =
  { cleared_through_job_id: null, dismissed_job_ids: [] }
let dismissWriteFails = false
const dismissCalls: Array<{ path: string; method?: string }> = []

vi.mock('../api/client', () => ({
  ApiError,
  api: vi.fn((path: string, opts?: RequestInit) => {
    const method = opts?.method
    if (path.startsWith('/jobs/') && path.endsWith('/cancel') && method === 'POST') {
      cancelCalls.push({ path, method })
      if (cancelResult === 'forbidden') return Promise.reject(new ApiError(403, { detail: 'forbidden' }))
      if (cancelResult === 'conflict') return Promise.reject(new ApiError(409, { detail: 'job is already succeeded' }))
      return Promise.resolve({ id: 10, status: 'canceled' })
    }
    if (path === '/jobs/12/events') {
      if (jobEventsError) return Promise.reject(new Error('boom'))
      return Promise.resolve([{ seq: 1, ts: '2026-08-12T07:00:01Z', stream: 'stderr', message: 'reading superblock' }])
    }
    if (path === '/jobs/10/events') {
      return Promise.resolve([{ seq: 1, ts: '2026-08-12T08:59:01Z', stream: 'stdout', message: 'copying rootfs' }])
    }
    if (path === '/jobs?status=running') {
      return Promise.resolve(JOBS.filter((j) => j.status === 'running'))
    }
    if (path === '/jobs') {
      if (jobsResult === 'error') return Promise.reject(new Error('boom'))
      if (jobsResult === 'empty') return Promise.resolve([])
      if (jobsResult === 'many') {
        return Promise.resolve(Array.from({ length: 17 }, (_, i) => ({
          ...JOBS[1], id: 100 + i, kind: `bulk.job${i}`,
        })))
      }
      return Promise.resolve(JOBS)
    }
    if (path === '/notifications/dismissed/clear-all' && method === 'POST') {
      dismissCalls.push({ path, method })
      if (dismissWriteFails) return Promise.reject(new ApiError(500, { detail: 'boom' }))
      return Promise.resolve(dismissedState)
    }
    if (path.startsWith('/notifications/dismissed/') && method === 'POST') {
      dismissCalls.push({ path, method })
      if (dismissWriteFails) return Promise.reject(new ApiError(500, { detail: 'boom' }))
      return Promise.resolve(dismissedState)
    }
    if (path === '/notifications/dismissed') {
      return Promise.resolve(dismissedState)
    }
    return Promise.resolve(null)
  }),
}))

import { BellPopover } from '../components/BellPopover'

/** Holds GET /notifications/dismissed open so the pending window can be
 *  observed. Everything else answers normally. */
const withDismissedPending = async () => {
  const { api } = await import('../api/client')
  const real = vi.mocked(api).getMockImplementation()!
  let release: () => void = () => {}
  const gate = new Promise<void>((r) => { release = r })
  vi.mocked(api).mockImplementation((path: string, opts?: RequestInit) =>
    path === '/notifications/dismissed' && (opts?.method ?? 'GET') === 'GET'
      ? gate.then(() => real(path, opts)) as never
      : real(path, opts) as never)
  return { release: () => { release(); vi.mocked(api).mockImplementation(real as never) } }
}

const wrap = () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}><BellPopover /></QueryClientProvider>)
}

const openBell = async () => {
  const trigger = await screen.findByRole('button', { name: 'Activity' })
  fireEvent.click(trigger)
  return trigger
}

describe('BellPopover', () => {
  beforeEach(() => {
    jobsResult = 'ok'
    cancelResult = 'ok'
    jobEventsError = false
    cancelCalls.length = 0
    dismissedState = { cleared_through_job_id: null, dismissed_job_ids: [] }
    dismissWriteFails = false
    dismissCalls.length = 0
    toastError.mockClear()
    resetNotificationStore()
  })

  // The badge used to count only running jobs; the tray now also shows
  // action notifications and SSE-delivered job/alert events, so a badge that
  // still only counted running jobs would drift from what the tray actually
  // holds -- the exact confusion this change exists to remove. It now counts
  // running jobs (still in flight, still worth knowing about) plus whatever
  // in the store has arrived since the tray was last opened.
  // The badge counts exactly what the tray holds. It has been two other things
  // (running jobs only, then running jobs plus an unread tally) and both meant
  // the number described something other than the list behind it.
  it('counts what the tray holds, not something else', async () => {
    wrap()
    // The fixture has three jobs, so the closed bell says three.
    expect(await screen.findByText('3')).toBeInTheDocument()
  })

  it('grows when a notification arrives and shrinks when one is dismissed', async () => {
    wrap()
    await screen.findByText('3')
    act(() => { pushAction('success', 'Saved.') })
    expect(await screen.findByText('4')).toBeInTheDocument()

    await openBell()
    fireEvent.click(screen.getAllByRole('button', { name: 'Dismiss' })[0])
    await waitFor(() => expect(screen.getByText('3')).toBeInTheDocument())
  })

  // A badge showing 0 has stopped meaning anything.
  it('shows no badge at all when the tray is empty', async () => {
    jobsResult = 'empty'
    wrap()
    await openBell()
    await screen.findByText(/nothing to report/i)
    expect(screen.queryByText('0')).not.toBeInTheDocument()
  })

  it('opens from the bell and lists recent jobs', async () => {
    wrap()
    await openBell()
    expect(await screen.findByText(/App Start #/)).toBeInTheDocument()
    expect(screen.getByText(/App Stopped/)).toBeInTheDocument()
    expect(screen.getByText(/VM Backup/)).toBeInTheDocument()
  })

  it('says jobs could not be read rather than showing an empty list', async () => {
    jobsResult = 'error'
    wrap()
    await openBell()
    expect(await screen.findByText(/notifications not readable/i)).toBeInTheDocument()
  })

  it('shows the real empty copy when there genuinely are no jobs', async () => {
    jobsResult = 'empty'
    wrap()
    await openBell()
    expect(await screen.findByText(/nothing to report/i)).toBeInTheDocument()
  })

  // The user asked for notification cards rather than a list, so each row is
  // the same NotificationCard the live toasts use: role="alert", a severity,
  // and its own dismiss. Cancel and the expandable job log went with the list.
  it('renders each job as a notification card, not a list row', async () => {
    wrap()
    await openBell()
    const cards = await screen.findAllByRole('alert')
    expect(cards.length).toBeGreaterThan(0)
    expect(cards[0].querySelector('button[aria-label="Dismiss"]')).not.toBeNull()
  })

  // A failure's reason is the whole point of surfacing it: the drawer showed
  // it, the feed cannot (ActivityRow carries no error field), so this card is
  // the only place it appears.
  it("carries a failed job's error text in the card", async () => {
    wrap()
    await openBell()
    expect(await screen.findByText(/disk full/i)).toBeInTheDocument()
  })

  // JOBS[0] (app.start) is 'running' with progress_pct: 40. footerOf used to
  // fold that into the plain-text footer line as "40%"; it now renders as
  // the shared ring instead.
  it("shows a progress ring on a running job's card instead of plain percent text", async () => {
    wrap()
    await openBell()
    const cards = await screen.findAllByRole('alert')
    const running = cards.find((c) => c.textContent?.includes('App Start #'))!
    expect(within(running).getByRole('status')).toHaveAttribute(
      'aria-label', expect.stringContaining('40 percent'))
    expect(within(running).queryByText('40%')).toBeNull()
  })

  // JOBS[1] (app.stop) already succeeded, even though it carries
  // progress_pct: 100. A determinate ring is for a job still running.
  it('shows no ring on a finished job, even one with a progress figure', async () => {
    wrap()
    await openBell()
    const cards = await screen.findAllByRole('alert')
    const finished = cards.find((c) => c.textContent?.includes('App Stopped'))!
    expect(within(finished).queryByRole('status')).toBeNull()
  })

  // JOBS[2] (vm.backup) failed with progress_pct: null, no figure, no ring.
  it('shows no ring on a job with no progress figure', async () => {
    wrap()
    await openBell()
    const cards = await screen.findAllByRole('alert')
    const failed = cards.find((c) => c.textContent?.includes('VM Backup'))!
    expect(within(failed).queryByRole('status')).toBeNull()
  })

  it('dismissing a card removes only that one', async () => {
    wrap()
    await openBell()
    const before = (await screen.findAllByRole('alert')).length
    fireEvent.click(screen.getAllByRole('button', { name: 'Dismiss' })[0])
    await waitFor(() =>
      expect(screen.getAllByRole('alert')).toHaveLength(before - 1))
  })

  /** jsdom reports every offsetHeight as 0, so the popover's measure pass is
   *  skipped and its viewport-height estimate is what decides the count. That
   *  makes innerHeight the lever these tests pull. */
  const setViewportHeight = (px: number) => {
    Object.defineProperty(window, 'innerHeight', { value: px, configurable: true })
  }

  // Capped at 15 however tall the window is, with no scrollbar: the backlog
  // drains through the x, so dismissing one is what reveals the next.
  it('shows at most 15 cards, and reveals the next when one is dismissed', async () => {
    setViewportHeight(2000)
    jobsResult = 'many'
    wrap()
    await openBell()
    await screen.findByText('Bulk Job0 #100')
    expect(screen.getAllByRole('alert')).toHaveLength(15)
    // #115 is the 16th, so it is queued behind the visible fifteen.
    expect(screen.queryByText('Bulk Job15 #115')).not.toBeInTheDocument()

    fireEvent.click(screen.getAllByRole('button', { name: 'Dismiss' })[0])

    await waitFor(() => expect(screen.getByText('Bulk Job15 #115')).toBeInTheDocument())
    expect(screen.getAllByRole('alert')).toHaveLength(15)
  })

  // The count follows the window rather than a constant: a laptop should not
  // get a column of cards running off the bottom with no way to scroll to them.
  it('shows fewer cards in a short window than a tall one', async () => {
    jobsResult = 'many'
    setViewportHeight(600)
    const short = render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <BellPopover />
      </QueryClientProvider>)
    await openBell()
    const shortCount = (await screen.findAllByRole('alert')).length
    short.unmount()

    setViewportHeight(2000)
    wrap()
    await openBell()
    const tallCount = (await screen.findAllByRole('alert')).length

    expect(shortCount).toBeLessThan(tallCount)
    expect(shortCount).toBeGreaterThanOrEqual(1)
  })

  // A failure's reason is the message, and must not be clamped away.
  it('shows the full error text and a line of context, not just a heading', async () => {
    wrap()
    await openBell()
    expect(await screen.findByText('disk full: retry failed')).toBeInTheDocument()
    // One muted context line per card, not a label/value table: what it
    // touched and how long ago.
    expect(screen.getByText(/vm 3 ·/)).toBeInTheDocument()
  })

  // Deleting the activity drawer took the only UI path to GET /jobs/{id}/events
  // for a job you did not start in this session: an endpoint sold behind the
  // jobs.history / jobs.stream entitlements. This is that path. It was lost
  // once already, so it gets a test.
  it('opens any job\'s transcript from its card', async () => {
    wrap()
    await openBell()
    const cards = await screen.findAllByRole('alert')
    const failed = cards.find((c) => c.textContent?.includes('VM Backup'))!
    fireEvent.click(within(failed).getByRole('button', { name: /view log/i }))

    const dialog = await screen.findByRole('dialog')
    // "Failed", because JOBS[2] failed: the title states the outcome rather
    // than only naming the kind (see actionLabel).
    expect(within(dialog).getByText('VM Backup Failed #12')).toBeInTheDocument()
    // The archived transcript is fetched for THAT job, not whichever was first.
    await waitFor(() => expect(screen.getByText(/reading superblock/)).toBeInTheDocument())

    // It shipped with Escape and the scrim and nothing to click, unlike every
    // other dialog that mounts a JobLog. A visible way out is not optional.
    fireEvent.click(within(dialog).getByRole('button', { name: 'Close' }))
    await waitFor(() => expect(screen.queryByText('VM Backup Failed #12')).not.toBeInTheDocument())
  })

  // Icon-only controls: the aria-label is the accessible name whether or not
  // the tooltip opens, and the tooltip is what a sighted pointer user gets.
  //
  // Real .focus() rather than fireEvent.focus: the point of this test is that
  // a keyboard user landing on the button gets its name, and only a genuine
  // DOM focus (which is what Tab produces) proves that. A synthetic focus
  // event would pass even if the button had stopped being focusable at all.
  it('names both card controls on focus', async () => {
    wrap()
    await openBell()
    const cards = await screen.findAllByRole('alert')
    const first = within(cards[0])

    first.getByRole('button', { name: 'View log' }).focus()
    expect(await screen.findAllByText('View log')).not.toHaveLength(0)

    first.getByRole('button', { name: 'Dismiss' }).focus()
    expect(await screen.findAllByText('Dismiss')).not.toHaveLength(0)
  })

  /** Everything inside `root` that a Tab press can land on, in tab order. */
  const tabbables = (root: HTMLElement) =>
    Array.from(root.querySelectorAll<HTMLElement>('button, [href], input, select, textarea, [tabindex]'))
      .filter((el) => el.tabIndex >= 0 && !el.hasAttribute('disabled'))

  // Radix's Tooltip opens on FOCUS as well as on hover (deliberately: that is
  // how a keyboard user reads an icon-only button's name), and Radix's Popover
  // moves focus to the first TABBABLE element of its content when it opens.
  // With a single card in the tray that element is the card's "View log", so
  // clicking the bell used to pop that card's tooltip with the pointer nowhere
  // near it. Two or more cards hid the bug, because then "Clear all" is first
  // and it has no tooltip -- hence the one-card fixture here.
  it('opening the tray with the pointer pops no tooltip, tabbing to a control does', async () => {
    // Everything up to job 11 already cleared, leaving exactly one card.
    dismissedState = { cleared_through_job_id: 11, dismissed_job_ids: [] }
    wrap()
    await screen.findByText('1')
    const trigger = screen.getByRole('button', { name: 'Activity' })
    fireEvent.pointerDown(trigger, { button: 0 })
    fireEvent.click(trigger)

    const card = (await screen.findAllByRole('alert'))[0]
    expect(within(card).getByRole('button', { name: 'View log' })).toBeInTheDocument()

    // The labels exist as aria-labels either way; an OPEN tooltip is a
    // rendered text node, and there must not be one.
    expect(screen.queryByText('View log')).not.toBeInTheDocument()
    expect(screen.queryByText('Dismiss')).not.toBeInTheDocument()

    // Focus went to the popover itself rather than onto a control inside it,
    // and the button is still the very next thing Tab reaches: the keyboard
    // path to the tooltip above is one keystroke, not gone.
    const content = screen.getByRole('dialog')
    expect(document.activeElement).toBe(content)
    const viewLog = within(card).getByRole('button', { name: 'View log' })
    expect(tabbables(content)[0]).toBe(viewLog)

    // ...and taking that Tab does pop it. Same card, same button, same open
    // popover: the tooltip was deferred to the keyboard user, not suppressed.
    viewLog.focus()
    expect(await screen.findByText('View log')).toBeInTheDocument()
  })

  // The other half of "focus is not left somewhere unusable": closing must put
  // it back on the bell, not drop it on <body>.
  it('returns focus to the bell when the tray closes', async () => {
    wrap()
    const trigger = await screen.findByRole('button', { name: 'Activity' })
    fireEvent.click(trigger)
    await screen.findByText(/App Start #/)
    fireEvent.keyDown(document, { key: 'Escape' })
    await waitFor(() => expect(document.activeElement).toBe(trigger))
  })

  it('closes on Escape', async () => {
    wrap()
    await openBell()
    await screen.findByText(/App Start #/)
    fireEvent.keyDown(document, { key: 'Escape' })
    await waitFor(() => expect(screen.queryByText(/App Start #/)).not.toBeInTheDocument())
  })

  it('closes on an outside click', async () => {
    wrap()
    await openBell()
    await screen.findByText(/App Start #/)
    // Radix's DismissableLayer defers a left-button pointerdown outside until
    // the matching click fires (so a drag-selection that starts outside and
    // ends inside doesn't dismiss the layer); both events are needed here.
    fireEvent.pointerDown(document.body, { button: 0 })
    fireEvent.click(document.body)
    await waitFor(() => expect(screen.queryByText(/App Start #/)).not.toBeInTheDocument())
  })

  // Radix's Popover.Content legitimately carries role="dialog" (a non-modal
  // dialog is still a dialog, per the ARIA spec); what makes it NOT a modal,
  // and what this locks down, is the absence of aria-modal, plus outside
  // clicks and Escape (proved above) working exactly like any other popover
  // rather than being swallowed by a focus trap.
  it('renders no scrim and no aria-modal', async () => {
    wrap()
    await openBell()
    await screen.findByText(/App Start #/)
    expect(document.querySelector('[aria-modal]')).toBeNull()
  })

  // The real risk in collapsing two surfaces into one: a job delivered once
  // over SSE (LiveProvider pushes it into the store the instant it lands)
  // and again the next time GET /jobs is polled must never render twice.
  it('a job present in both the SSE-fed store and GET /jobs appears once, not twice', async () => {
    pushJobEvent(11, 'success', 'app.stop succeeded')
    wrap()
    await openBell()
    const cards = await screen.findAllByRole('alert')
    const forJob11 = cards.filter((c) => c.textContent?.includes('App Stopped'))
    expect(forJob11).toHaveLength(1)
  })

  // Action notifications ("Saved.", "Could not cancel that job.") live only
  // in the client-side store, so they must show up in the tray the instant
  // they are pushed, with nothing to reload or refetch.
  it('an action notification appears in the tray without a reload', async () => {
    wrap()
    act(() => { pushAction('destructive', 'Could not cancel that job.') })
    await openBell()
    expect(await screen.findByText('Could not cancel that job.')).toBeInTheDocument()
  })

  it('clear all empties the tray, jobs and action notifications alike', async () => {
    wrap()
    act(() => { pushAction('success', 'Saved.') })
    await openBell()
    await screen.findByText('Saved.')
    expect((await screen.findAllByRole('alert')).length).toBeGreaterThan(1)

    fireEvent.click(screen.getByRole('button', { name: /clear all/i }))

    await waitFor(() => expect(screen.queryAllByRole('alert')).toHaveLength(0))
    // The action notification is forgotten outright (nothing server-side
    // owns it); a job card would reappear on the next /jobs poll, which
    // this test does not wait for.
    expect(getNotifications()).toHaveLength(0)
  })

  // --- server-side persistence (persist-cleared-notifications) -----------

  // The tray must consult the persisted state on load, not only its own
  // component state: a watermark that already covers a job's id has to hide
  // that job's card the very first time it is fetched, before anyone has
  // clicked anything in this session.
  it('hides a job at or below the persisted watermark, on first load', async () => {
    dismissedState = { cleared_through_job_id: 11, dismissed_job_ids: [] }
    wrap()
    // JOBS 10 and 11 are covered by the watermark; only 12 remains.
    expect(await screen.findByText('1')).toBeInTheDocument()
    await openBell()
    expect(await screen.findByText(/VM Backup/)).toBeInTheDocument()
    expect(screen.queryByText(/App Start #/)).not.toBeInTheDocument()
    expect(screen.queryByText(/App Stopped/)).not.toBeInTheDocument()
  })

  // The watermark only covers ids at or below it; an id dismissed on its
  // own above the watermark is what dismissed_job_ids is for.
  it('hides an individually dismissed job id above the watermark', async () => {
    dismissedState = { cleared_through_job_id: null, dismissed_job_ids: [11] }
    wrap()
    await openBell()
    expect(await screen.findByText(/App Start #/)).toBeInTheDocument()
    expect(screen.queryByText(/App Stopped/)).not.toBeInTheDocument()
    expect(await screen.findByText(/VM Backup/)).toBeInTheDocument()
  })

  it('clear all writes through to the server', async () => {
    wrap()
    await openBell()
    await screen.findByText(/App Start #/)
    fireEvent.click(screen.getByRole('button', { name: /clear all/i }))
    await waitFor(() => expect(
      dismissCalls.some((c) => c.path === '/notifications/dismissed/clear-all'),
    ).toBe(true))
  })

  it('dismissing a job-backed card writes that job id through to the server', async () => {
    wrap()
    await openBell()
    const cards = await screen.findAllByRole('alert')
    const jobCard = cards.find((c) => c.textContent?.includes('App Start #'))!
    fireEvent.click(within(jobCard).getByRole('button', { name: 'Dismiss' }))
    await waitFor(() => expect(
      dismissCalls.some((c) => c.path === '/notifications/dismissed/10'),
    ).toBe(true))
  })

  // notify.tsx's action notifications have no server record to persist:
  // dismissing one must not hit the network at all.
  it('dismissing a client-side action notification writes nothing through', async () => {
    wrap()
    act(() => { pushAction('success', 'Saved.') })
    await openBell()
    const cards = await screen.findAllByRole('alert')
    const savedCard = cards.find((c) => c.textContent?.includes('Saved.'))!
    fireEvent.click(within(savedCard).getByRole('button', { name: 'Dismiss' }))
    await waitFor(() => expect(screen.queryByText('Saved.')).not.toBeInTheDocument())
    expect(dismissCalls).toHaveLength(0)
  })

  // The trap this exists to avoid: reverting the optimistic hide on a
  // failed write would make the card reappear a moment after the user
  // dismissed it, unexplained. It must stay hidden, and the failure must
  // be surfaced rather than swallowed.
  it('a failed dismiss write keeps the card hidden and surfaces the failure', async () => {
    dismissWriteFails = true
    wrap()
    await openBell()
    const cards = await screen.findAllByRole('alert')
    const jobCard = cards.find((c) => c.textContent?.includes('App Start #'))!
    fireEvent.click(within(jobCard).getByRole('button', { name: 'Dismiss' }))
    await waitFor(() => expect(screen.queryByText(/App Start #/)).not.toBeInTheDocument())
    await waitFor(() => expect(
      dismissCalls.some((c) => c.path === '/notifications/dismissed/10'),
    ).toBe(true))
    // Gave the rejected mutation a full turn to settle; it did not come back.
    expect(screen.queryByText(/App Start #/)).not.toBeInTheDocument()
    expect(await screen.findByText(/could not save/i)).toBeInTheDocument()
  })

  // Same trap, for clear all: a failed write must not repopulate the tray
  // it just emptied. The one card left standing afterwards is the failure
  // notification itself (an ordinary action notification, by design), not
  // any of the three jobs that were cleared.
  it('a failed clear-all write keeps the cleared jobs gone and surfaces the failure', async () => {
    dismissWriteFails = true
    wrap()
    await openBell()
    await screen.findByText(/App Start #/)
    fireEvent.click(screen.getByRole('button', { name: /clear all/i }))
    await waitFor(() => expect(screen.queryByText(/App Start #/)).not.toBeInTheDocument())
    await waitFor(() => expect(
      dismissCalls.some((c) => c.path === '/notifications/dismissed/clear-all'),
    ).toBe(true))
    expect(screen.queryByText(/App Start #/)).not.toBeInTheDocument()
    expect(screen.queryByText(/App Stopped/)).not.toBeInTheDocument()
    expect(screen.queryByText(/VM Backup/)).not.toBeInTheDocument()
    expect(await screen.findByText(/could not save/i)).toBeInTheDocument()
  })

  // Cleared notifications used to come BACK for the length of the
  // GET /notifications/dismissed fetch, badge included, because
  // isPersistedDismissed answers false for every id until that state lands.
  // Fail open on a failed read is right; fail open while it is merely in
  // flight showed the operator news they had already dealt with.
  it('does not resurrect cleared notifications while the dismissal state loads', async () => {
    dismissedState = { cleared_through_job_id: 99, dismissed_job_ids: [] }
    const gate = await withDismissedPending()
    wrap()
    // Every fixture job is at or below the watermark, so once the state lands
    // the tray is empty. While it is pending the badge must not claim
    // otherwise.
    const bell = await screen.findByRole('button', { name: 'Activity' })
    fireEvent.click(bell)

    // The job list resolves while the dismissal state is still held, which is
    // the exact window this is about: jobs are KNOWN, what has been cleared is
    // NOT. Every fixture job is at or below the watermark, so once both have
    // landed the tray is empty. Before the fix, this window listed all of them
    // and badged the count, then took them away on the next paint.
    //
    // Asserting through a job title rather than the badge, because the badge
    // reads zero while jobs are loading too, which made an earlier version of
    // this test pass with the fix reverted.
    await waitFor(() => expect(screen.getByRole('status')).toBeInTheDocument())
    expect(screen.queryByText(/App Start/)).not.toBeInTheDocument()
    expect(within(bell).queryByText(/^[0-9]+$/)).not.toBeInTheDocument()

    gate.release()
    // and once it lands they are still gone, because they really were cleared
    await waitFor(() => expect(screen.getByText(/Nothing to report/i)).toBeInTheDocument())
    expect(within(bell).queryByText(/^[0-9]+$/)).not.toBeInTheDocument()
  })
})
