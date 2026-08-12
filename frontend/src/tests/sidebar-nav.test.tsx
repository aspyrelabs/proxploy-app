import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

// The nav renders TanStack Router <Link>s. This file only cares about the
// nav's own markup, so Link becomes a plain anchor carrying its target.
vi.mock('@tanstack/react-router', () => ({
  Link: ({ to, children, className }: {
    to: string; children: React.ReactNode; className?: string
  }) => <a href={to} data-to={to} className={className}>{children}</a>,
}))

// HealthFooter runs its own queries and is not what this file tests.
vi.mock('../components/HealthFooter', () => ({ HealthFooter: () => null }))

import { NAV, SidebarNav } from '../components/SidebarNav'

describe('SidebarNav icons', () => {
  it('gives every one of the ten nav items an icon', () => {
    // .map().flat() rather than .flatMap(): with NAV's heterogeneous
    // per-group `as const` tuples, flatMap's overload resolution collapses
    // the item union into the first group's shape and tsc rejects it.
    const items = NAV.map((g) => g.items).flat()
    expect(items).toHaveLength(10)
    for (const item of items) {
      // Not toBeTypeOf('function'): @heroicons/react v2 icons are
      // React.forwardRef components, so typeof is 'object' at runtime even
      // though they render fine as JSX tags. toBeDefined() still catches
      // the bug this test exists for (a missing `icon` field).
      expect(item.icon, `${item.label} has no icon`).toBeDefined()
    }
  })

  it('renders an svg beside each label, hidden from the accessibility tree', () => {
    render(<SidebarNav />)
    // Every nav link holds exactly one svg, and that svg is aria-hidden: the
    // label beside it is the accessible name, so an icon announcing itself
    // would make every item read twice.
    for (const item of NAV.map((g) => g.items).flat()) {
      const link = screen.getByText(item.label).closest('a')
      expect(link, `${item.label} link missing`).not.toBeNull()
      const svgs = link!.querySelectorAll('svg')
      expect(svgs).toHaveLength(1)
      expect(svgs[0].getAttribute('aria-hidden')).toBe('true')
    }
  })

  it('keeps the label text, so the nav is still readable without icons', () => {
    render(<SidebarNav />)
    expect(screen.getByText('Virtual Machines')).toBeInTheDocument()
    expect(screen.getByText('App Store')).toBeInTheDocument()
  })
})
