import { useState } from 'react'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { AlertDialog, AlertDialogAction, AlertDialogCancel } from '../components/ui/alert-dialog'
import { Dialog } from '../components/ui/dialog'

/**
 * The four defects this primitive exists to fix, asserted rather than assumed:
 * Escape does nothing, focus is not trapped, focus is not restored to whatever
 * opened the dialog, and nothing is marked aria-modal. Every one of the 18
 * hand-rolled dialogs had all four.
 *
 * These are behaviour tests against real Radix, not mocks. If Radix is swapped
 * out or misconfigured, these fail.
 */

function DialogHarness({ onClose = () => {} }: { onClose?: () => void }) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>Open dialog</button>
      <button type="button">Outside button</button>
      {open && (
        <Dialog title="Remove host" onClose={() => { setOpen(false); onClose() }}>
          <input aria-label="Host name" />
          <button type="button">Inside action</button>
        </Dialog>
      )}
    </>
  )
}

describe('Dialog', () => {
  it('marks the panel as a modal dialog with an accessible name', async () => {
    render(<DialogHarness />)
    fireEvent.click(screen.getByRole('button', { name: 'Open dialog' }))

    const panel = await screen.findByRole('dialog', { name: 'Remove host' })
    expect(panel).toHaveAttribute('aria-modal', 'true')
  })

  it('closes on Escape', async () => {
    const onClose = vi.fn()
    render(<DialogHarness onClose={onClose} />)
    fireEvent.click(screen.getByRole('button', { name: 'Open dialog' }))
    await screen.findByRole('dialog')

    fireEvent.keyDown(document.activeElement ?? document.body, { key: 'Escape' })

    await waitFor(() => expect(onClose).toHaveBeenCalled())
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  // The bug this whole change exists for: a click on something outside the
  // app entirely (the reported case was a browser password manager's save
  // prompt) used to dismiss the dialog and lose whatever had been typed.
  it('does not close on an outside pointer interaction', async () => {
    const onClose = vi.fn()
    render(<DialogHarness onClose={onClose} />)
    // Grabbed before opening: Radix aria-hides the rest of the tree once the
    // dialog is up, so a role query could not find this afterwards.
    const outside = screen.getByRole('button', { name: 'Outside button' })
    fireEvent.click(screen.getByRole('button', { name: 'Open dialog' }))
    await screen.findByRole('dialog')

    // Dialog defers a left-button pointerdown outside until the matching
    // click (so a drag-selection that starts outside and ends inside does
    // not dismiss it), same as the popover in bell-popover.test.tsx: both
    // events are needed to reach the code path this test is guarding.
    fireEvent.pointerDown(outside, { button: 0 })
    fireEvent.click(outside)

    expect(onClose).not.toHaveBeenCalled()
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })

  it('closes when the X is clicked, and the X has an accessible name', async () => {
    const onClose = vi.fn()
    render(<DialogHarness onClose={onClose} />)
    fireEvent.click(screen.getByRole('button', { name: 'Open dialog' }))
    await screen.findByRole('dialog')

    fireEvent.click(screen.getByRole('button', { name: 'Close dialog' }))

    await waitFor(() => expect(onClose).toHaveBeenCalled())
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('renders the X alongside headerRight, replacing neither', async () => {
    render(
      <Dialog title="Create VM" headerRight={<span>Step 2 of 4</span>} onClose={vi.fn()}>
        <p>body</p>
      </Dialog>,
    )
    const panel = screen.getByRole('dialog')
    expect(within(panel).getByText('Step 2 of 4')).toBeInTheDocument()
    expect(within(panel).getByRole('button', { name: 'Close dialog' })).toBeInTheDocument()
    expect(within(panel).getByText('Create VM')).toBeInTheDocument()
  })

  it('moves focus into the panel when it opens', async () => {
    render(<DialogHarness />)
    fireEvent.click(screen.getByRole('button', { name: 'Open dialog' }))

    const panel = await screen.findByRole('dialog')
    await waitFor(() => expect(panel.contains(document.activeElement)).toBe(true))
  })

  it('hides the rest of the page from assistive tech while it is open', async () => {
    render(<DialogHarness />)
    const outside = screen.getByRole('button', { name: 'Outside button' })
    fireEvent.click(screen.getByRole('button', { name: 'Open dialog' }))
    await screen.findByRole('dialog')

    // Grabbed by role BEFORE opening on purpose: once the dialog is up, the
    // same query cannot find it, which is the behaviour we want.
    expect(screen.queryByRole('button', { name: 'Outside button' })).toBeNull()
    expect(outside.closest('[aria-hidden="true"]')).not.toBeNull()
  })

  it('keeps focus inside the panel while it is open', async () => {
    render(<DialogHarness />)
    // Captured before opening: Radix aria-hides the rest of the tree, so a
    // role query cannot reach this button once the dialog is up.
    const outside = screen.getByRole('button', { name: 'Outside button' })
    fireEvent.click(screen.getByRole('button', { name: 'Open dialog' }))
    const panel = await screen.findByRole('dialog')
    await waitFor(() => expect(panel.contains(document.activeElement)).toBe(true))

    // What the hand-rolled dialogs allowed: tab straight out into the page
    // behind the scrim, and keep operating it.
    outside.focus()

    await waitFor(() => expect(panel.contains(document.activeElement)).toBe(true))
  })

  it('returns focus to whatever opened it', async () => {
    render(<DialogHarness />)
    const trigger = screen.getByRole('button', { name: 'Open dialog' })
    trigger.focus()
    fireEvent.click(trigger)
    await screen.findByRole('dialog')

    fireEvent.keyDown(document.activeElement ?? document.body, { key: 'Escape' })

    await waitFor(() => expect(document.activeElement).toBe(trigger))
  })
})

function PaletteHarness({ onClose = () => {} }: { onClose?: () => void }) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>Open palette</button>
      <button type="button">Outside button</button>
      {open && (
        <Dialog title="Command palette" variant="palette" onClose={() => { setOpen(false); onClose() }}>
          <input aria-label="Search" />
        </Dialog>
      )}
    </>
  )
}

describe('Dialog palette variant', () => {
  // The one deliberate exception to "no outside close": a command palette
  // conventionally dismisses on an outside click, and this one always has.
  // Locked down so the exception stays a decision, not a silent regression.
  it('still closes on an outside interaction, unlike a standard dialog', async () => {
    const onClose = vi.fn()
    render(<PaletteHarness onClose={onClose} />)
    const outside = screen.getByRole('button', { name: 'Outside button' })
    fireEvent.click(screen.getByRole('button', { name: 'Open palette' }))
    await screen.findByRole('dialog')

    fireEvent.pointerDown(outside, { button: 0 })
    fireEvent.click(outside)

    await waitFor(() => expect(onClose).toHaveBeenCalled())
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('has no X, because it has no header row to hang one on', async () => {
    render(<PaletteHarness />)
    fireEvent.click(screen.getByRole('button', { name: 'Open palette' }))
    const panel = await screen.findByRole('dialog')
    expect(within(panel).queryByRole('button', { name: 'Close dialog' })).not.toBeInTheDocument()
  })
})

function AlertHarness({ onConfirm = () => {} }: { onConfirm?: () => void }) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>Open alert</button>
      {open && (
        <AlertDialog
          title="Remove pve1?"
          description="This cannot be undone."
          onCancel={() => setOpen(false)}
        >
          <AlertDialogCancel onClick={() => setOpen(false)}>Cancel</AlertDialogCancel>
          <AlertDialogAction onClick={onConfirm}>Confirm</AlertDialogAction>
        </AlertDialog>
      )}
    </>
  )
}

describe('Dialog scrollBody', () => {
  // jsdom has no layout engine, so it cannot tell whether a panel is capped or
  // whether a body scrolls. What it CAN do is prove the opt-in works: that a
  // dialog which does not ask for scrolling emits exactly the classes it
  // always did. The geometry itself is measured in a real browser by
  // `npm run harness:dialog` (e2e/harness/dialog-main.tsx).
  const panelOf = () => screen.getByRole('dialog')

  it('leaves a dialog that does not opt in completely untouched', () => {
    // The regression that would matter: capping every dialog in the app to fix
    // one of them. InstallDialog, the VM wizard and the schedule dialogs all
    // share this component.
    render(<Dialog title="Plain" onClose={vi.fn()}><p>body</p></Dialog>)
    const panel = panelOf()
    expect(panel.className).toBe('max-w-[92vw] rounded-card border border-line bg-panel p-5')
    expect(panel.querySelector('.overflow-y-auto')).toBeNull()
    // the heading is a direct child, not wrapped in a scroll container
    expect(screen.getByText('body').parentElement).toBe(panel)
  })

  it('caps and wraps the body only when asked', () => {
    render(<Dialog title="Long" scrollBody onClose={vi.fn()}><p>body</p></Dialog>)
    const panel = panelOf()
    expect(panel.className).toContain('max-h-[70vh]')
    expect(panel.className).toContain('flex-col')
    // the cap still rides on the shared class, so 92vw cannot be forgotten
    expect(panel.className).toContain('max-w-[92vw]')

    const scroller = panel.querySelector('.overflow-y-auto')!
    expect(scroller).not.toBeNull()
    // min-h-0 is what actually lets a flex child shrink and scroll
    expect(scroller.className).toContain('min-h-0')
    expect(screen.getByText('body').parentElement).toBe(scroller)
    // and the heading is OUTSIDE the scroller, so it cannot scroll away
    expect(scroller.contains(screen.getByText('Long'))).toBe(false)
  })
})

describe('Dialog fit', () => {
  // Same limitation as above: jsdom has no layout engine, so it cannot tell
  // how wide the panel came out. What it can hold is the contract that makes
  // the width content-driven and bounded -- both caps present, no stated width
  // to beat w-fit -- which is exactly what a regression here would break.
  it('sizes to its content and caps at 80% of the window in both axes', () => {
    render(<Dialog title="app.install #7" fit onClose={vi.fn()}><p>body</p></Dialog>)
    const panel = screen.getByRole('dialog')
    expect(panel.className).toContain('w-fit')
    expect(panel.className).toContain('max-w-[80vw]')
    expect(panel.className).toContain('max-h-[80vh]')
    // an inline width would win over w-fit and there would be nothing left for
    // the content to decide
    expect(panel.style.width).toBe('')
    // the 92vw default must not ride along: two max-widths on one element is a
    // coin toss decided by stylesheet order, not by the call site
    expect(panel.className).not.toContain('92vw')
  })

  it('leaves the body unwrapped, because the body owns the scrolling', () => {
    render(<Dialog title="app.install #7" fit onClose={vi.fn()}><p>body</p></Dialog>)
    const panel = screen.getByRole('dialog')
    // Unlike scrollBody: TerminalPanel is the scroller and has to stay one, or
    // it stops following the newest line.
    expect(panel.querySelector('.overflow-y-auto')).toBeNull()
    expect(screen.getByText('body').parentElement).toBe(panel)
    expect(panel.className).toContain('flex-col')
    // the heading cannot be part of what flexbox shrinks to honour the cap
    expect(screen.getByText('app.install #7').className).toContain('shrink-0')
  })
})

describe('AlertDialog', () => {
  it('marks the panel as a modal alertdialog with an accessible name', async () => {
    render(<AlertHarness />)
    fireEvent.click(screen.getByRole('button', { name: 'Open alert' }))

    const panel = await screen.findByRole('alertdialog', { name: 'Remove pve1?' })
    expect(panel).toHaveAttribute('aria-modal', 'true')
  })

  it('closes on Escape', async () => {
    render(<AlertHarness />)
    fireEvent.click(screen.getByRole('button', { name: 'Open alert' }))
    await screen.findByRole('alertdialog')

    fireEvent.keyDown(document.activeElement ?? document.body, { key: 'Escape' })

    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument())
  })

  it('keeps focus inside the panel while it is open', async () => {
    render(<AlertHarness />)
    fireEvent.click(screen.getByRole('button', { name: 'Open alert' }))
    const panel = await screen.findByRole('alertdialog')

    await waitFor(() => expect(panel.contains(document.activeElement)).toBe(true))
  })

  it('takes a CSS width, so a panel can ask for a share of the window', () => {
    // The install transcript asks for 60% of the window rather than a fixed
    // number of pixels: a terminal that wraps mid-line hides the part worth
    // reading, which on an install is the finished URL and the errors. A
    // number still means px, which every other caller passes.
    //
    // Asserted as the RESOLVED width rather than the literal expression: the
    // point is that the panel comes out wider than the form it replaces, and
    // a string compare would pass just as happily on a value that resolved to
    // nothing.
    const px = (w: number | string) => {
      const { unmount } = render(
        <Dialog title="Install redis" width={w} onClose={vi.fn()}><p>body</p></Dialog>)
      const width = getComputedStyle(screen.getByRole('dialog')).width
      unmount()
      return parseFloat(width)
    }
    expect(px('max(520px, 60vw)')).toBeGreaterThan(px(520))
  })
})
