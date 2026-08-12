import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

// The Icon component throws for any name without a codepoint entry, and this
// menu needs names (more_vert, edit, restart_alt, power_settings_new) that do
// not exist yet -- coordinated separately with whoever owns
// lib/material-symbols-codepoints.mjs (see the report). Stubbed here so this
// file tests the MENU, not the icon font subset; icon.test.tsx already pins
// Icon's own contract.
vi.mock('../components/ui/icon', () => ({
  Icon: ({ name, size }: { name: string; size?: number }) => (
    <span data-icon={name} data-size={size ?? 18} />
  ),
}))

vi.mock('../api/client', () => ({
  api: vi.fn(() => Promise.resolve({ is_self: false })),
  ApiError: class extends Error {},
}))

import { HostActionsMenu } from '../components/HostActionsMenu'

const host = { name: 'pve1', address: 'https://10.0.0.5:8006' }

// Radix opens a menu on pointerdown, not click (AccountMenu.test.tsx precedent).
const openMenu = (trigger: HTMLElement) => fireEvent.pointerDown(trigger, { button: 0, ctrlKey: false })

const wrap = () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <HostActionsMenu hostId={1} node="pve1" host={host} />
    </QueryClientProvider>)
}

describe('HostActionsMenu', () => {
  it('renders a trigger with an accessible name, hidden from the a11y tree otherwise', () => {
    wrap()
    const trigger = screen.getByRole('button', { name: /actions/i })
    expect(trigger).toBeInTheDocument()
    expect(trigger.querySelector('[data-icon="more_vert"]')).not.toBeNull()
  })

  it('opens on click and lists Edit, Reboot and Power off, each with an icon', async () => {
    wrap()
    openMenu(screen.getByRole('button', { name: /actions/i }))
    const edit = await screen.findByRole('menuitem', { name: /edit/i })
    const reboot = screen.getByRole('menuitem', { name: /reboot/i })
    const powerOff = screen.getByRole('menuitem', { name: /power off/i })
    expect(edit.querySelector('[data-icon="edit"]')).not.toBeNull()
    expect(reboot.querySelector('[data-icon="restart_alt"]')).not.toBeNull()
    expect(powerOff.querySelector('[data-icon="power_settings_new"]')).not.toBeNull()
  })

  it('styles Power off destructively, the way a Delete item would be', async () => {
    wrap()
    openMenu(screen.getByRole('button', { name: /actions/i }))
    const powerOff = await screen.findByRole('menuitem', { name: /power off/i })
    // The existing destructive vocabulary in this codebase is the `text-red`
    // token (Button's `danger` variant, AccountMenu's Sign out item) -- not a
    // hardcoded colour, which src/tests/no-hardcoded-colors.test.ts forbids.
    expect(powerOff.className).toContain('text-red')
  })

  it('does not style Edit or Reboot as destructive', async () => {
    wrap()
    openMenu(screen.getByRole('button', { name: /actions/i }))
    const edit = await screen.findByRole('menuitem', { name: /edit/i })
    const reboot = screen.getByRole('menuitem', { name: /reboot/i })
    expect(edit.className).not.toContain('text-red')
    expect(reboot.className).not.toContain('text-red')
  })

  it('opens the edit dialog on Edit, as a popup card rather than navigating', async () => {
    wrap()
    openMenu(screen.getByRole('button', { name: /actions/i }))
    fireEvent.click(await screen.findByRole('menuitem', { name: /edit/i }))
    expect(await screen.findByRole('dialog')).toBeInTheDocument()
    expect(screen.getByText(/edit pve1/i)).toBeInTheDocument()
  })

  it('opens a typed-confirmation dialog on Reboot, naming the node', async () => {
    wrap()
    openMenu(screen.getByRole('button', { name: /actions/i }))
    fireEvent.click(await screen.findByRole('menuitem', { name: /reboot/i }))
    const dialog = await screen.findByRole('alertdialog')
    expect(dialog).toHaveTextContent(/reboot pve1/i)
    expect(screen.getByLabelText(/type pve1 to confirm/i)).toBeInTheDocument()
  })

  it('opens a typed-confirmation dialog on Power off, naming the node', async () => {
    wrap()
    openMenu(screen.getByRole('button', { name: /actions/i }))
    fireEvent.click(await screen.findByRole('menuitem', { name: /power off/i }))
    const dialog = await screen.findByRole('alertdialog')
    expect(dialog).toHaveTextContent(/power off pve1/i)
    expect(screen.getByLabelText(/type pve1 to confirm/i)).toBeInTheDocument()
  })
})
