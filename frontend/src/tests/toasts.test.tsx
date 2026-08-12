/** Toasts are the only in-app notification surface, so they carry their own
 *  controls: an x on each, and one way to clear the lot. */
import { render, screen, act, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { Toaster, toast } from 'sonner'
import { ClearAllToasts } from '../components/ClearAllToasts'
import { NotificationCard } from '../components/ui/notification-card'
import type { NotificationSeverity } from '../components/ui/notification-card'

const wrap = () => render(<><Toaster closeButton /><ClearAllToasts /></>)

afterEach(() => act(() => { toast.dismiss() }))

describe('toast controls', () => {
  it('offers no clear-all when nothing is showing', () => {
    wrap()
    expect(screen.queryByRole('button', { name: /clear all/i })).not.toBeInTheDocument()
  })

  // One toast already has its own x. A "clear all" beside a single item is
  // two controls for one action.
  it('offers no clear-all for a single toast', async () => {
    wrap()
    act(() => { toast('one') })
    expect(await screen.findByText('one')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /clear all/i })).not.toBeInTheDocument()
  })

  it('offers clear-all once a second toast arrives', async () => {
    wrap()
    act(() => { toast('one'); toast('two') })
    expect(await screen.findByRole('button', { name: /clear all/i })).toBeInTheDocument()
  })

  it('clears every toast when pressed', async () => {
    const { getByRole } = wrap()
    act(() => { toast('one'); toast('two') })
    await screen.findByRole('button', { name: /clear all/i })
    act(() => { getByRole('button', { name: /clear all/i }).click() })
    // sonner keeps a dismissed toast mounted for its 200ms exit animation
    // (TIME_BEFORE_UNMOUNT in node_modules/sonner/dist/index.mjs) before
    // removing it from the DOM, so the assertion has to wait rather than
    // check synchronously right after the click.
    await waitFor(() => {
      expect(screen.queryByText('one')).not.toBeInTheDocument()
      expect(screen.queryByText('two')).not.toBeInTheDocument()
    })
  })
})

/** The four severities LiveProvider's SSE `job`/`alert` handlers render via
 *  `toast.custom`, replacing the plain toast.success/toast.error calls those
 *  used to be. Each card is its own role="alert" with its own dismiss x. */
describe('NotificationCard', () => {
  const severities: NotificationSeverity[] = ['info', 'success', 'warning', 'destructive']

  it.each(severities)('renders the %s card with a title, description and a dismiss control', (severity) => {
    render(
      <NotificationCard severity={severity} title={`${severity} title`}
        description={`${severity} description`} onDismiss={() => {}} />,
    )
    const card = screen.getByRole('alert')
    expect(within(card).getByText(`${severity} title`)).toBeInTheDocument()
    expect(within(card).getByText(`${severity} description`)).toBeInTheDocument()
    expect(within(card).getByRole('button', { name: /dismiss/i })).toBeInTheDocument()
  })

  it('dismisses only the toast whose x was clicked', async () => {
    wrap()
    act(() => {
      toast.custom((id) => (
        <NotificationCard severity="destructive" title="job failed" description="job #1"
          onDismiss={() => toast.dismiss(id)} />
      ))
      toast.custom((id) => (
        <NotificationCard severity="success" title="job ok" description="job #2"
          onDismiss={() => toast.dismiss(id)} />
      ))
    })
    expect(await screen.findByText('job failed')).toBeInTheDocument()
    expect(screen.getByText('job ok')).toBeInTheDocument()

    const failedCard = screen.getByText('job failed').closest('[role="alert"]') as HTMLElement
    act(() => {
      within(failedCard).getByRole('button', { name: /dismiss/i }).click()
    })

    // sonner keeps a dismissed toast mounted for its 200ms exit animation
    // (TIME_BEFORE_UNMOUNT), so wait rather than assert synchronously.
    await waitFor(() => {
      expect(screen.queryByText('job failed')).not.toBeInTheDocument()
    })
    expect(screen.getByText('job ok')).toBeInTheDocument()
  })
})
