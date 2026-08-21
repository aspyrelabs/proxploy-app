import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

// The nav renders TanStack Router <Link>s. This file only cares about the
// nav's own markup, so Link becomes a plain anchor carrying its target. The
// real Link forwards arbitrary DOM props (e.g. aria-label) onto the anchor,
// so the stub spreads the rest through rather than naming only a few.
vi.mock('@tanstack/react-router', () => ({
  Link: ({ to, children, ...rest }: {
    to: string; children: React.ReactNode
  }) => <a href={to} data-to={to} {...rest}>{children}</a>,
}))


import { NAV, SidebarNav } from '../components/SidebarNav'

describe('SidebarNav icons', () => {
  it('gives every one of the eleven nav items an icon name', () => {
    // .map().flat() rather than .flatMap(): with NAV's heterogeneous
    // per-group `as const` tuples, flatMap's overload resolution collapses
    // the item union into the first group's shape and tsc rejects it.
    const items = NAV.map((g) => g.items).flat()
    expect(items).toHaveLength(11)
    for (const item of items) {
      // A Material Symbols name (see components/ui/icon.tsx), not a
      // component reference -- a plain lowercase snake_case string.
      expect(item.icon).toMatch(/^[a-z][a-z0-9_]*$/)
    }
  })

  it('renders one icon beside each label, hidden from the accessibility tree', () => {
    render(<SidebarNav />)
    // Every nav link holds exactly one icon glyph, and that glyph is
    // aria-hidden: the label beside it is the accessible name, so an icon
    // announcing itself would make every item read twice.
    for (const item of NAV.map((g) => g.items).flat()) {
      const link = screen.getByText(item.label).closest('a')
      expect(link, `${item.label} link missing`).not.toBeNull()
      const icons = link!.querySelectorAll('.material-symbols-outlined')
      expect(icons).toHaveLength(1)
      expect(icons[0].getAttribute('aria-hidden')).toBe('true')
      expect(icons[0].textContent).toBe(item.icon)
    }
  })

  it('keeps the label text, so the nav is still readable without icons', () => {
    render(<SidebarNav />)
    expect(screen.getByText('Virtual Machines')).toBeInTheDocument()
    expect(screen.getByText('App Store')).toBeInTheDocument()
  })
})

describe('SidebarNav collapse', () => {
  beforeEach(() => localStorage.clear())

  const toggle = (name: RegExp) =>
    fireEvent.click(screen.getByRole('button', { name }))

  it('starts expanded, showing labels', () => {
    render(<SidebarNav />)
    expect(screen.getByText('Hosts')).toBeInTheDocument()
    expect(screen.getByText('Overview')).toBeInTheDocument()
  })

  it('collapses to icons when the toggle is pressed', () => {
    render(<SidebarNav />)
    toggle(/collapse sidebar/i)
    // The labels go; the links, and their icons, stay.
    expect(screen.queryByText('Hosts')).not.toBeInTheDocument()
    expect(screen.getAllByRole('link')).toHaveLength(11)
    // and the group headings become a rule rather than text
    expect(screen.queryByText('Infrastructure')).not.toBeInTheDocument()
  })

  it('names every icon for assistive tech once the label is gone', () => {
    render(<SidebarNav />)
    toggle(/collapse sidebar/i)
    // With no visible text, the link itself must carry the name.
    expect(screen.getByRole('link', { name: 'Virtual Machines' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'App Store' })).toBeInTheDocument()
  })

  it('names the item in a Radix tooltip on focus', async () => {
    render(<SidebarNav />)
    toggle(/collapse sidebar/i)
    const link = screen.getByRole('link', { name: 'Virtual Machines' })
    fireEvent.focus(link)
    const tooltip = await screen.findByRole('tooltip')
    expect(tooltip).toHaveTextContent('Virtual Machines')
  })

  it('remembers the choice across a remount', () => {
    const { unmount } = render(<SidebarNav />)
    toggle(/collapse sidebar/i)
    unmount()
    render(<SidebarNav />)
    expect(screen.queryByText('Hosts')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /expand sidebar/i })).toBeInTheDocument()
  })

  it('expands again', () => {
    render(<SidebarNav />)
    toggle(/collapse sidebar/i)
    toggle(/expand sidebar/i)
    expect(screen.getByText('Hosts')).toBeInTheDocument()
  })
})
