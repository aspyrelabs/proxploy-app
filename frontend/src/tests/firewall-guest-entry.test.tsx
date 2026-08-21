import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

let OPTIONS: any = { scope: 'guest', digest: null,
                     options: { enable: 1 }, defaults: { policy_in: 'DROP' } }
let RULES: any = { scope: 'guest', digest: null, rules: [
  { pos: 0, type: 'in', action: 'ACCEPT', enable: 1 },
  { pos: 1, type: 'in', action: 'DROP', enable: 1 },
] }

vi.mock('../api/client', () => ({
  ApiError: class extends Error {},
  api: vi.fn((path: string) => {
    if (path.endsWith('/options')) return Promise.resolve(OPTIONS)
    if (path.endsWith('/rules')) return Promise.resolve(RULES)
    return Promise.resolve({})
  }),
}))

// The real Link needs a <RouterProvider>, which nothing here stands up; every
// other test in this repo mocks it thin for the same reason. `to` is forwarded
// as `href` because the second test below asserts the exact destination.
vi.mock('@tanstack/react-router', async (orig) => ({
  ...(await orig() as object),
  Link: ({ to, children, ...rest }: { to?: unknown; children?: unknown }) => (
    <a href={String(to)} {...rest}>{children as never}</a>
  ),
}))

import { GuestFirewallLine } from '../components/GuestFirewallLine'

function wrap() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <GuestFirewallLine guestType="app" guestId={5} />
    </QueryClientProvider>,
  )
}

describe('GuestFirewallLine', () => {
  it('says the firewall is on and how many rules there are', async () => {
    await wrap()
    expect(await screen.findByText(/on, 2 rules/i)).toBeTruthy()
  })

  it('links to the guest firewall page', async () => {
    wrap()
    const link = await screen.findByRole('link', { name: /firewall/i })
    expect(link.getAttribute('href')).toBe('/firewall/guest/app/5')
  })

  it('says off when Proxmox is not filtering this guest', async () => {
    OPTIONS = { scope: 'guest', digest: null, options: { enable: 0 },
                defaults: { policy_in: 'DROP' } }
    wrap()
    expect(await screen.findByText(/off/i)).toBeTruthy()
  })
})
