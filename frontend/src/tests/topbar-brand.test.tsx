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
vi.mock('../components/ActivityDrawer', () => ({
  useActivityDrawer: () => ({ toggle: vi.fn() }),
}))
vi.mock('../components/CommandPalette', () => ({ openCommandPalette: vi.fn() }))
// The brand mark is now a Link (to /hosts); Link needs a real RouterProvider
// to resolve its href, which this file doesn't mount. Mock it thin, matching
// sidebar-nav.test.tsx / healthfooter.test.tsx.
vi.mock('@tanstack/react-router', async (orig) => ({
  ...(await orig() as object),
  Link: ({ children, ...rest }: { children?: unknown }) => <a {...rest}>{children as never}</a>,
}))

import { Topbar } from '../components/Topbar'

const wrap = () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}><Topbar /></QueryClientProvider>)
}

describe('Topbar', () => {
  // The sidebar is max-[720px]:hidden, so before this the product showed no
  // logo at all on a phone. The header is the one chrome that is always there.
  //
  // Not `container.querySelector('header svg')`: the search control's
  // MagnifyingGlassIcon also matches that selector, so the assertion stayed
  // green when <Logo> was deleted outright. Logo carries `role="img"
  // aria-label="Proxploy"`; assert that specifically.
  it('carries the brand mark', () => {
    wrap()
    expect(screen.getByRole('img', { name: 'Proxploy' })).toBeInTheDocument()
  })

  // The emoji became SVGs; the accessible names must not have moved with them.
  it('keeps the search control named and reachable', () => {
    wrap()
    expect(screen.getByRole('button', { name: /search/i })).toBeInTheDocument()
  })

  it('keeps the activity control named', async () => {
    wrap()
    expect(await screen.findByRole('button', { name: 'Activity' })).toBeInTheDocument()
  })

  it('has no emoji left in it', () => {
    const { container } = wrap()
    const header = container.querySelector('header')!
    expect(header.textContent ?? '').not.toMatch(/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/u)
  })
})
