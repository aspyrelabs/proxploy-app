import { useState } from 'react'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
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
})
