/** NotificationCard is the one card design every notification surface in the
 *  app renders through: the tray (BellPopover), the brief under-the-bell
 *  banner (NotificationSurface), and -- for as long as the three files still
 *  mid-migration keep calling sonner's toast.success/error directly -- the
 *  legacy bottom-right stack too (see lib/notify.tsx's own comment on why
 *  that stack no longer exists here for anything else). This file proves the
 *  card itself: severities, description, dismiss, independent of who is
 *  hosting it. sonner's Toaster is only the rendering harness for
 *  toast.custom below, not a claim that this app still shows toasts. */
import { render, screen, act, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { Toaster, toast } from 'sonner'
import { NotificationCard } from '../components/ui/notification-card'
import type { NotificationSeverity } from '../components/ui/notification-card'

const wrap = () => render(<Toaster closeButton />)

afterEach(() => act(() => { toast.dismiss() }))

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
