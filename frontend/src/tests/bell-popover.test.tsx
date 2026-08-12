/** The activity drawer was deleted in favour of toasts, but that also deleted
 *  the only UI path to an arbitrary job's log and its error text. This is
 *  the replacement: a popover anchored to the topbar bell, reading /jobs
 *  (not /cluster/activity, whose ActivityRow has no `error` field). */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { JobRow } from '../api/jobs'

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
    return Promise.resolve(null)
  }),
}))

import { BellPopover } from '../components/BellPopover'

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
    toastError.mockClear()
  })

  it('still shows the running-job count badge on the bell', async () => {
    wrap()
    expect(await screen.findByText('1')).toBeInTheDocument()
  })

  it('opens from the bell and lists recent jobs', async () => {
    wrap()
    await openBell()
    expect(await screen.findByText(/app\.start/)).toBeInTheDocument()
    expect(screen.getByText(/app\.stop/)).toBeInTheDocument()
    expect(screen.getByText(/vm\.backup/)).toBeInTheDocument()
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
    const running = cards.find((c) => c.textContent?.includes('app.start'))!
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
    const finished = cards.find((c) => c.textContent?.includes('app.stop'))!
    expect(within(finished).queryByRole('status')).toBeNull()
  })

  // JOBS[2] (vm.backup) failed with progress_pct: null, no figure, no ring.
  it('shows no ring on a job with no progress figure', async () => {
    wrap()
    await openBell()
    const cards = await screen.findAllByRole('alert')
    const failed = cards.find((c) => c.textContent?.includes('vm.backup'))!
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
    await screen.findByText('bulk.job0 #100')
    expect(screen.getAllByRole('alert')).toHaveLength(15)
    // #115 is the 16th, so it is queued behind the visible fifteen.
    expect(screen.queryByText('bulk.job15 #115')).not.toBeInTheDocument()

    fireEvent.click(screen.getAllByRole('button', { name: 'Dismiss' })[0])

    await waitFor(() => expect(screen.getByText('bulk.job15 #115')).toBeInTheDocument())
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
    const failed = cards.find((c) => c.textContent?.includes('vm.backup'))!
    fireEvent.click(within(failed).getByRole('button', { name: /view log/i }))

    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText('vm.backup #12')).toBeInTheDocument()
    // The archived transcript is fetched for THAT job, not whichever was first.
    await waitFor(() => expect(screen.getByText(/reading superblock/)).toBeInTheDocument())
  })

  // Icon-only controls: the aria-label is the accessible name whether or not
  // the tooltip opens, and the tooltip is what a sighted pointer user gets.
  it('names both card controls on focus', async () => {
    wrap()
    await openBell()
    const cards = await screen.findAllByRole('alert')
    const first = within(cards[0])

    fireEvent.focus(first.getByRole('button', { name: 'View log' }))
    expect(await screen.findAllByText('View log')).not.toHaveLength(0)

    fireEvent.focus(first.getByRole('button', { name: 'Dismiss' }))
    expect(await screen.findAllByText('Dismiss')).not.toHaveLength(0)
  })

  it('closes on Escape', async () => {
    wrap()
    await openBell()
    await screen.findByText(/app\.start/)
    fireEvent.keyDown(document, { key: 'Escape' })
    await waitFor(() => expect(screen.queryByText(/app\.start/)).not.toBeInTheDocument())
  })

  it('closes on an outside click', async () => {
    wrap()
    await openBell()
    await screen.findByText(/app\.start/)
    // Radix's DismissableLayer defers a left-button pointerdown outside until
    // the matching click fires (so a drag-selection that starts outside and
    // ends inside doesn't dismiss the layer); both events are needed here.
    fireEvent.pointerDown(document.body, { button: 0 })
    fireEvent.click(document.body)
    await waitFor(() => expect(screen.queryByText(/app\.start/)).not.toBeInTheDocument())
  })
})
