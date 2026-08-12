import { render } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

// AppShell's defining shape: a full-width header, then a flex row (sidebar +
// main) starting beneath it. Everything else it renders (the router outlet,
// the command palette, the notification surface) is provider-side wiring
// unrelated to that shape, so those collapse to markers here.
vi.mock('@tanstack/react-router', () => ({ Outlet: () => <div data-testid="outlet" /> }))
vi.mock('../components/Topbar', () => ({ Topbar: () => <header data-testid="topbar" /> }))
vi.mock('../components/SidebarNav', () => ({ SidebarNav: () => <aside data-testid="sidebar" /> }))
vi.mock('../components/CommandPalette', () => ({ CommandPalette: () => null }))
vi.mock('../components/NotificationSurface', () => ({ NotificationSurface: () => null }))

import { AppShell } from '../components/AppShell'

describe('AppShell', () => {
  // This is the exact regression the branch already shipped once: the header
  // used to live inside the sidebar's own column and had to be pulled out by
  // eye into a full-width row above it. Lock the ordering down so it can't
  // silently move back inside the flex row.
  it('renders the header above the sidebar/main row, not nested inside it', () => {
    const { container } = render(<AppShell />)
    const header = container.querySelector('header')!
    const sidebar = container.querySelector('[data-testid="sidebar"]')!
    const flexRow = sidebar.parentElement!

    expect(header).not.toBeNull()
    // The header is a sibling of the flex row, not a descendant of it.
    expect(flexRow.contains(header)).toBe(false)
    // ...and it comes before that row in document order.
    expect(header.compareDocumentPosition(flexRow) & Node.DOCUMENT_POSITION_FOLLOWING)
      .toBeTruthy()
  })

  it('keeps the sidebar and main content in the row beneath the header', () => {
    const { container } = render(<AppShell />)
    const sidebar = container.querySelector('[data-testid="sidebar"]')!
    const main = container.querySelector('main')!
    expect(sidebar.parentElement).toBe(main.parentElement)
  })
})
