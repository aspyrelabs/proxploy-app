/** NotificationSurface is the answer to "how does a new notification get
 *  seen without the user clicking the bell": the newest arrivals appear
 *  briefly near the bell, then collapse into the tray (they stay in the
 *  store; only the transient banner card goes away). It renders nothing for
 *  whatever was already in the store when it mounted -- that is history, not
 *  an arrival -- and nothing while the tray itself is open, so it can never
 *  sit on top of the popover the user already has open.
 */
import { act, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { NotificationSurface } from '../components/NotificationSurface'
import {
  pushAction, resetNotificationStore, setTrayOpen,
} from '../lib/notificationStore'

beforeEach(() => {
  resetNotificationStore()
  vi.useRealTimers()
})

describe('NotificationSurface', () => {
  it('a new notification surfaces without the tray being opened by hand', async () => {
    render(<NotificationSurface />)
    act(() => { pushAction('success', 'Saved.') })
    expect(await screen.findByText('Saved.')).toBeInTheDocument()
  })

  it('does not show whatever was already in the store before it mounted', () => {
    pushAction('info', 'already here before mount')
    render(<NotificationSurface />)
    expect(screen.queryByText('already here before mount')).not.toBeInTheDocument()
  })

  it('renders nothing while the tray is already open, so it cannot cover the popover', async () => {
    render(<NotificationSurface />)
    act(() => { setTrayOpen(true) })
    act(() => { pushAction('destructive', 'Could not cancel that job.') })
    // Give any microtask a chance to run; the card must never appear.
    await new Promise((r) => setTimeout(r, 0))
    expect(screen.queryByText('Could not cancel that job.')).not.toBeInTheDocument()
  })

  it('a card queued while the tray was open still appears once the tray closes', async () => {
    render(<NotificationSurface />)
    act(() => { setTrayOpen(true) })
    act(() => { pushAction('info', 'queued while open') })
    act(() => { setTrayOpen(false) })
    expect(await screen.findByText('queued while open')).toBeInTheDocument()
  })

  it('an error card outlasts a success card', async () => {
    vi.useFakeTimers()
    render(<NotificationSurface />)
    act(() => {
      pushAction('success', 'Saved.')
      pushAction('destructive', 'Could not save.')
    })
    expect(screen.getByText('Saved.')).toBeInTheDocument()
    expect(screen.getByText('Could not save.')).toBeInTheDocument()

    // Past the success duration, before the error one.
    act(() => { vi.advanceTimersByTime(5000) })
    expect(screen.queryByText('Saved.')).not.toBeInTheDocument()
    expect(screen.getByText('Could not save.')).toBeInTheDocument()

    // Past the error duration too.
    act(() => { vi.advanceTimersByTime(5000) })
    expect(screen.queryByText('Could not save.')).not.toBeInTheDocument()
    vi.useRealTimers()
  })

  it('dismissing a surfaced card early hides it here without removing it from the tray', async () => {
    render(<NotificationSurface />)
    act(() => { pushAction('success', 'Saved.') })
    const card = await screen.findByText('Saved.')
    act(() => { card.closest('[role="alert"]')!.querySelector('button[aria-label="Dismiss"]')!.dispatchEvent(
      new MouseEvent('click', { bubbles: true })) })
    await waitFor(() => expect(screen.queryByText('Saved.')).not.toBeInTheDocument())
    const { getNotifications } = await import('../lib/notificationStore')
    expect(getNotifications().some((n) => n.title === 'Saved.')).toBe(true)
  })
})
