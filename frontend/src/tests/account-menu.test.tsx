/** The avatar was a <span>: no menu, no profile, and POST /auth/logout was
 *  called from nowhere in the app, so there was no way to sign out at all. */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const navigate = vi.fn()
let posted: string[] = []

vi.mock('../api/client', () => ({
  api: vi.fn((path: string, init?: RequestInit) => {
    if (init?.method === 'POST') posted.push(path)
    if (path === '/auth/me') {
      return Promise.resolve({ id: 1, email: 'ops@acme.io', display_name: 'Ops',
                               role: 'owner', totp_enabled: false })
    }
    if (path === '/entitlements') return Promise.resolve({ features: [] })
    return Promise.resolve(null)
  }),
  ApiError: class extends Error {},
}))

vi.mock('@tanstack/react-router', async (orig) => ({
  ...(await orig() as object),
  useNavigate: () => navigate,
  Link: ({ children, ...p }: { children: React.ReactNode }) =>
    <a {...p}>{children}</a>,
}))

import { AccountMenu } from '../components/AccountMenu'

beforeEach(() => { posted = []; navigate.mockClear() })

const renderMenu = () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}><AccountMenu /></QueryClientProvider>)
}

describe('AccountMenu', () => {
  it('opens from the avatar, which is a real button', async () => {
    renderMenu()
    const trigger = await screen.findByRole('button', { name: /account/i })
    expect(trigger).toHaveAttribute('aria-expanded', 'false')
    fireEvent.click(trigger)
    expect(trigger).toHaveAttribute('aria-expanded', 'true')
  })

  it('names who is signed in, so the avatar letter is not the only clue', async () => {
    renderMenu()
    fireEvent.click(await screen.findByRole('button', { name: /account/i }))
    expect(await screen.findByText('ops@acme.io')).toBeInTheDocument()
  })

  it('offers a profile link', async () => {
    renderMenu()
    fireEvent.click(await screen.findByRole('button', { name: /account/i }))
    expect(await screen.findByText(/profile/i)).toBeInTheDocument()
  })

  it('signs out through the endpoint that was never called', async () => {
    renderMenu()
    fireEvent.click(await screen.findByRole('button', { name: /account/i }))
    // menuitem, not button: inside role="menu" the ARIA role wins, and that is
    // the correct markup rather than something to work around.
    fireEvent.click(await screen.findByRole('menuitem', { name: /sign out/i }))
    await vi.waitFor(() => expect(posted).toContain('/auth/logout'))
    await vi.waitFor(() => expect(navigate).toHaveBeenCalled())
  })

  it('closes on Escape', async () => {
    renderMenu()
    const trigger = await screen.findByRole('button', { name: /account/i })
    fireEvent.click(trigger)
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(trigger).toHaveAttribute('aria-expanded', 'false')
  })
})
