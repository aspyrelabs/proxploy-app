import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

vi.mock('../components/ui/icon', () => ({
  Icon: ({ name, size }: { name: string; size?: number }) => (
    <span data-icon={name} data-size={size ?? 18} />
  ),
}))

import { RowActionsMenu } from '../components/ui/row-actions'

const openMenu = (trigger: HTMLElement) =>
  fireEvent.pointerDown(trigger, { button: 0, ctrlKey: false })

describe('RowActionsMenu', () => {
  it('renders a trigger with the given aria-label', () => {
    render(<RowActionsMenu label="Actions for foo" actions={[]} />)
    expect(screen.getByRole('button', { name: 'Actions for foo' })).toBeInTheDocument()
  })

  it('lists each action label when opened', async () => {
    render(<RowActionsMenu label="Actions" actions={[
      { label: 'Edit', icon: 'edit', onSelect: vi.fn() },
      { label: 'Delete', icon: 'delete', onSelect: vi.fn(), destructive: true },
    ]} />)
    openMenu(screen.getByRole('button', { name: 'Actions' }))
    expect(await screen.findByRole('menuitem', { name: 'Edit' })).toBeInTheDocument()
    expect(screen.getByRole('menuitem', { name: 'Delete' })).toBeInTheDocument()
  })

  it('fires onSelect when an action is clicked', async () => {
    const onSelect = vi.fn()
    render(<RowActionsMenu label="Actions" actions={[
      { label: 'Edit', icon: 'edit', onSelect },
    ]} />)
    openMenu(screen.getByRole('button', { name: 'Actions' }))
    fireEvent.click(await screen.findByRole('menuitem', { name: 'Edit' }))
    expect(onSelect).toHaveBeenCalledTimes(1)
  })

  it('does not fire onSelect for a disabled action', async () => {
    const onSelect = vi.fn()
    render(<RowActionsMenu label="Actions" actions={[
      { label: 'Edit', icon: 'edit', onSelect, disabled: true },
    ]} />)
    openMenu(screen.getByRole('button', { name: 'Actions' }))
    const item = await screen.findByRole('menuitem', { name: 'Edit' })
    fireEvent.click(item)
    expect(onSelect).not.toHaveBeenCalled()
  })

  it('renders a destructive action with the red class, and an ordinary one without it', async () => {
    render(<RowActionsMenu label="Actions" actions={[
      { label: 'Delete', icon: 'delete', onSelect: vi.fn(), destructive: true },
      { label: 'Edit', icon: 'edit', onSelect: vi.fn() },
    ]} />)
    openMenu(screen.getByRole('button', { name: 'Actions' }))
    const del = await screen.findByRole('menuitem', { name: 'Delete' })
    const edit = screen.getByRole('menuitem', { name: 'Edit' })
    expect(del.className).toContain('text-red')
    expect(edit.className).not.toContain('text-red')
  })
})
