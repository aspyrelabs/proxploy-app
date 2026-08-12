/** lib/notify.ts is the one place every toast in the app goes through, so the
 *  bottom-right corner renders one card design (NotificationCard) rather than
 *  sonner's plain text toast in some places and a card in others. This covers
 *  the helper itself; the 26-odd call sites that now go through it keep their
 *  own tests, which assert on notify.<method> having been called with the
 *  right title/description rather than re-proving the render here.
 */
import { render, screen, act, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { Toaster, toast } from 'sonner'
import { notify } from '../lib/notify'

const wrap = () => render(<Toaster />)

afterEach(() => act(() => { toast.dismiss() }))

// severity -> the Material Symbols glyph name NotificationCard renders for it
// (components/ui/notification-card.tsx's ICON map). The glyph's text content
// is the readable proof a card actually carries the severity it claims,
// short of reading a Tailwind class name out of the DOM.
const GLYPH = {
  success: 'check_circle',
  error: 'cancel',
  info: 'info',
  warning: 'warning',
} as const

describe('notify', () => {
  it.each(Object.keys(GLYPH) as (keyof typeof GLYPH)[])(
    'notify.%s renders a card with that severity, a title and a dismiss control', async (method) => {
      wrap()
      act(() => { notify[method](`${method} title`) })
      const card = await screen.findByRole('alert')
      expect(within(card).getByText(`${method} title`)).toBeInTheDocument()
      expect(card.querySelector('.material-symbols-outlined')?.textContent).toBe(GLYPH[method])
      expect(within(card).getByRole('button', { name: /dismiss/i })).toBeInTheDocument()
    },
  )

  // The card's description is never clamped (notification-card.tsx's own
  // comment on the prop): a long reason has to read in full, not get a title
  // treatment that would cut it off.
  it('a long message passed as the description renders in full, not a clamped title', async () => {
    const long = 'Rolling back discards every change made since the snapshot was taken, '
      + 'including any disks attached after it, and there is no way to undo a rollback '
      + 'once it starts.'
    wrap()
    act(() => { notify.error('Could not roll back', { description: long }) })
    const card = await screen.findByRole('alert')
    expect(within(card).getByText(long)).toBeInTheDocument()
  })

  // Mirrors toasts.test.tsx's NotificationCard coverage, through the helper
  // this time: each call is its own toast with its own dismiss.
  it('dismissing one card dismisses only that toast', async () => {
    wrap()
    act(() => {
      notify.error('first', { description: 'one' })
      notify.success('second', { description: 'two' })
    })
    expect(await screen.findByText('first')).toBeInTheDocument()
    expect(screen.getByText('second')).toBeInTheDocument()

    const firstCard = screen.getByText('first').closest('[role="alert"]') as HTMLElement
    act(() => {
      within(firstCard).getByRole('button', { name: /dismiss/i }).click()
    })

    // sonner keeps a dismissed toast mounted for its 200ms exit animation
    // (TIME_BEFORE_UNMOUNT), so wait rather than assert synchronously.
    await waitFor(() => {
      expect(screen.queryByText('first')).not.toBeInTheDocument()
    })
    expect(screen.getByText('second')).toBeInTheDocument()
  })
})
