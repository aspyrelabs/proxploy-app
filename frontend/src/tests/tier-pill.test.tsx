/** The pill is not shrinkable, so its label length is a layout constraint, not
 *  a cosmetic choice: 'FREE · ALL FEATURES' is ~143px of tracked mono and was
 *  the single biggest reason the topbar overran a 375px phone. */
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

let tier = 'builtin'
let inGrace = false

vi.mock('../api/hooks', () => ({
  useEntitlements: () => ({ tier, grace: { in_grace: inGrace } }),
}))
vi.mock('@tanstack/react-router', () => ({
  Link: ({ children, className }: { children: React.ReactNode; className?: string }) =>
    <a className={className}>{children}</a>,
}))

import { TierPill } from '../components/TierPill'

describe('TierPill', () => {
  it('carries a short label for narrow viewports and the full one above sm', () => {
    tier = 'builtin'
    render(<TierPill />)
    // Both are in the DOM; CSS picks one. jsdom cannot see the breakpoint, so
    // the guard is that the short form exists at all and is the sm:hidden one.
    const short = screen.getByText('FREE')
    const full = screen.getByText('FREE · ALL FEATURES')
    expect(short.className).toContain('sm:hidden')
    expect(full.className).toContain('hidden')
  })

  it('never wraps or shrinks, whatever the tier', () => {
    tier = 'pro'
    const { container } = render(<TierPill />)
    const link = container.querySelector('a')!
    expect(link.className).toContain('whitespace-nowrap')
    expect(link.className).toContain('shrink-0')
  })
})
