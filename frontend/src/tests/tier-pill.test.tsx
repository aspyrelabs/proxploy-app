/** The badge is not shrinkable, so its label length is a layout constraint,
 *  not a cosmetic choice: it sits in a topbar that has overrun a 375px phone
 *  before. One size constant drives all four tiers and their icons. */
import { render } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

let tier = 'builtin'
let inGrace = false
let refreshError: string | null = null
const toasts: { kind: string; title: string }[] = []

vi.mock('../api/hooks', () => ({
  useEntitlements: () => ({ tier, grace: { in_grace: inGrace }, refreshError }),
}))
vi.mock('../lib/notify', () => ({
  notify: {
    error: (title: string) => { toasts.push({ kind: 'error', title }) },
    warning: (title: string) => { toasts.push({ kind: 'warning', title }) },
    success: () => {}, info: () => {}, custom: () => {},
  },
}))
vi.mock('@tanstack/react-router', () => ({
  Link: ({ children, to, search, ...rest }: {
    children: React.ReactNode; to?: string; search?: unknown
  } & Record<string, unknown>) => <a {...rest}>{children}</a>,
}))

import { TIER_BADGE_PX, TierPill, resetLicenceAnnouncement } from '../components/TierPill'

describe('TierPill', () => {
  beforeEach(() => {
    tier = 'builtin'; inGrace = false; refreshError = null
    toasts.length = 0
    resetLicenceAnnouncement()
  })

  it('names the plan, its icon and its tone, for every tier', () => {
    const cases = [
      ['builtin', 'FREE', 'shield_lock', 'text-amber'],
      ['pro', 'PRO', 'crown', 'text-red'],
      ['teams', 'TEAMS', 'groups', 'text-text'],
      ['dev', 'DEV', 'frame_source', 'text-green'],
    ] as const
    for (const [t, label, icon, tone] of cases) {
      tier = t
      const { container, unmount } = render(<TierPill />)
      const link = container.querySelector('a')!
      expect(link.textContent).toContain(label)
      expect(link.querySelector('.material-symbols-outlined')!.textContent).toBe(icon)
      expect(link.className).toContain(tone)
      unmount()
    }
  })

  it('drives the label and its icon from one size constant', () => {
    tier = 'pro'
    const { container } = render(<TierPill />)
    const link = container.querySelector('a')! as HTMLElement
    const glyph = container.querySelector('.material-symbols-outlined')! as HTMLElement
    expect(link.style.fontSize).toBe(`${TIER_BADGE_PX}px`)
    expect(glyph.style.fontSize).toBe(`${TIER_BADGE_PX}px`)
  })

  it('never wraps or shrinks, whatever the tier', () => {
    tier = 'pro'
    const { container } = render(<TierPill />)
    const link = container.querySelector('a')!
    expect(link.className).toContain('whitespace-nowrap')
    expect(link.className).toContain('shrink-0')
  })

  it('falls back to the raw tier name for a plan it has never heard of', () => {
    tier = 'enterprise'
    const { container } = render(<TierPill />)
    expect(container.querySelector('a')!.textContent).toContain('ENTERPRISE')
  })

  it('marks a licence in its grace period without changing the plan shown', () => {
    tier = 'pro'
    inGrace = true
    const { container } = render(<TierPill />)
    const link = container.querySelector('a')!
    expect(link.textContent).toContain('PRO')
    expect(link.getAttribute('title')).toMatch(/grace/i)
    expect(link.querySelectorAll('.pp-blink')).toHaveLength(1)
  })

  it('shows the unreachable marker instead of grace when the licence check failed', () => {
    tier = 'pro'
    inGrace = true
    refreshError = 'connection refused'
    const { container } = render(<TierPill />)
    const link = container.querySelector('a')!
    expect(link.getAttribute('title')).toMatch(/could not reach the licence server/i)
    expect(link.querySelectorAll('.pp-blink')).toHaveLength(1)
  })

  it('toasts once per licence state, not on every refetch', () => {
    tier = 'pro'
    refreshError = 'connection refused'
    const first = render(<TierPill />)
    expect(toasts).toEqual([{ kind: 'error', title: 'Could not check your licence' }])
    first.rerender(<TierPill />)
    first.unmount()
    render(<TierPill />)
    expect(toasts).toHaveLength(1)
  })

  it('warns rather than errors while inside the grace period', () => {
    tier = 'teams'
    inGrace = true
    render(<TierPill />)
    expect(toasts.map((t) => t.kind)).toEqual(['warning'])
  })

  it('stays quiet when the licence is healthy', () => {
    tier = 'pro'
    render(<TierPill />)
    expect(toasts).toEqual([])
  })
})
