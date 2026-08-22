import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

vi.mock('../api/client', () => ({
  api: vi.fn((path: string) =>
    path === '/entitlements'
      ? Promise.resolve({ tier: 'pro', features: { 'notify.inapp': true } })
      : Promise.resolve([])),
  ApiError: class extends Error {},
}))
vi.mock('../components/AccountMenu', () => ({ AccountMenu: () => null }))
vi.mock('../components/TierPill', () => ({ TierPill: () => null }))
vi.mock('../components/CommandPalette', () => ({ openCommandPalette: vi.fn() }))
vi.mock('../components/BellPopover', () => ({
  BellPopover: () => <button aria-label="Activity">bell</button>,
}))
// The brand mark is a Link (to /hosts); Link needs a real RouterProvider to
// resolve its href, which this file doesn't mount. Mock it thin, matching
// sidebar-nav.test.tsx / healthfooter.test.tsx, setting href explicitly so
// the mocked anchor still carries the "link" role.
vi.mock('@tanstack/react-router', async (orig) => ({
  ...(await orig() as object),
  Link: ({ to, children, ...rest }: { to?: string; children?: unknown }) =>
    <a href={to} {...rest}>{children as never}</a>,
}))

import { Topbar } from '../components/Topbar'
import { applyStoredTheme } from '../lib/theme'

const wrap = () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}><Topbar /></QueryClientProvider>)
}

describe('Topbar', () => {
  // The sidebar is max-[720px]:hidden, so before this the product showed no
  // logo at all on a phone. The header is the one chrome that is always there.
  //
  // Not `container.querySelector('header svg')`: Logo is the only <svg> in
  // the header now (the search control's icon is a Material Symbols span,
  // not an svg), but asserting on the tag would still miss <Logo> being
  // swapped for some other svg. Logo carries `role="img"
  // aria-label="Proxploy"`; assert that specifically.
  it('carries the brand mark, one variant per theme', () => {
    wrap()
    // Both variants are in the markup and CSS decides which shows, so that
    // the swap lands in the same frame as the theme. jsdom applies no CSS and
    // therefore sees both; a browser gives the hidden one display:none, which
    // takes it out of the accessibility tree, so exactly one is announced.
    const marks = screen.getAllByRole('img', { name: 'Proxploy' })
    expect(marks).toHaveLength(2)
    expect(marks.map(m => m.getAttribute('src'))).toEqual(
      ['/proxploy-logo-dark.svg', '/proxploy-logo-light.svg'])
  })

  // The emoji became SVGs; the accessible names must not have moved with them.
  it('keeps the search control named and reachable', () => {
    wrap()
    expect(screen.getByRole('button', { name: /search/i })).toBeInTheDocument()
  })

  it('keeps the activity control named and reachable, now opening the bell popover', async () => {
    wrap()
    expect(await screen.findByRole('button', { name: 'Activity' })).toBeInTheDocument()
  })

  it('has no emoji left in it', () => {
    const { container } = wrap()
    const header = container.querySelector('header')!
    expect(header.textContent ?? '').not.toMatch(/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/u)
  })
})

describe('theme defaulting', () => {
  it('follows the system when nobody has chosen', () => {
    // It used to be a flat default of dark, so a machine in light mode was
    // handed a dark app and had to go and find the toggle.
    localStorage.removeItem('pp_theme')
    const spy = vi.spyOn(window, 'matchMedia').mockReturnValue(
      { matches: true } as MediaQueryList)
    expect(applyStoredTheme()).toBe('light')
    expect(document.documentElement.dataset.theme).toBe('light')
    spy.mockRestore()
  })

  it('lets an explicit choice beat the system', () => {
    // Someone who reached for the toggle meant it.
    localStorage.setItem('pp_theme', 'dark')
    const spy = vi.spyOn(window, 'matchMedia').mockReturnValue(
      { matches: true } as MediaQueryList)
    expect(applyStoredTheme()).toBe('dark')
    spy.mockRestore()
    localStorage.removeItem('pp_theme')
  })

  it('falls back to dark where the browser cannot say', () => {
    localStorage.removeItem('pp_theme')
    const spy = vi.spyOn(window, 'matchMedia').mockReturnValue(
      { matches: false } as MediaQueryList)
    expect(applyStoredTheme()).toBe('dark')
    spy.mockRestore()
  })
})
