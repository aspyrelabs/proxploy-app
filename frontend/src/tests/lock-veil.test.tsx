/**
 * The veil itself. The five route/card tests that render it cover the happy
 * paths; what is only reachable here is the branch where the tier lookup comes
 * back with nothing, which is what a caller sees when /entitlements failed.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

let payload: unknown = null
let fail = false

vi.mock('../api/client', () => ({
  api: vi.fn(() => (fail ? Promise.reject(new Error('nope')) : Promise.resolve(payload))),
  ApiError: class extends Error {},
}))

import { LockVeil } from '../components/LockVeil'

function wrap(ui: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

const ent = (required: Record<string, string>) => ({
  tier: 'builtin', features: {}, required_tier: required,
  grace: null, clock_skew: false, refresh_error: null, reason: null,
})

describe('LockVeil', () => {
  it('names the tier the payload gives it, not one written at the call site', async () => {
    fail = false
    payload = ent({ 'teams.rbac': 'team' })
    wrap(<LockVeil locked feature="teams.rbac" subtitle="Roles and teams."><p>secret</p></LockVeil>)
    expect(await screen.findByText('This is a Team feature')).toBeInTheDocument()
  })

  it('says "a paid feature" rather than guessing when the tier is unknown', async () => {
    // /entitlements is unreachable, so `has` failed closed and we are veiled
    // with nothing to name. Naming the wrong plan would be worse than this.
    fail = true
    wrap(<LockVeil locked feature="teams.rbac" subtitle="Roles and teams."><p>secret</p></LockVeil>)
    expect(await screen.findByText('This is a paid feature')).toBeInTheDocument()
  })

  it('replaces the gated content instead of blurring it behind the overlay', async () => {
    fail = false
    payload = ent({ 'api.tokens': 'team' })
    wrap(<LockVeil locked feature="api.tokens" subtitle="Keys."><p>secret</p></LockVeil>)
    await screen.findByText('This is a Team feature')
    // The old veil kept the children in the DOM under a 1px blur, which left
    // them readable to a screen reader and to anyone with dev tools.
    expect(screen.queryByText('secret')).toBeNull()
  })

  it('renders the children untouched when it is not locked', async () => {
    fail = false
    payload = ent({})
    wrap(<LockVeil locked={false} feature="api.tokens" subtitle="Keys."><p>secret</p></LockVeil>)
    expect(screen.getByText('secret')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /Please upgrade/i })).toBeNull()
  })

  it('sends the upgrade link to the production price list, in a new tab', async () => {
    fail = false
    payload = ent({ 'hosts.multi': 'pro' })
    wrap(<LockVeil locked feature="hosts.multi" subtitle="More hosts."><p>x</p></LockVeil>)
    const a = await screen.findByRole('link', { name: /Please upgrade/i })
    // Hardcoded prod on purpose: this is the public price list, and a dev
    // build pointing someone at a staging price is worse than a fixed link.
    expect(a).toHaveAttribute('href', 'https://proxploy.com/#pricing')
    expect(a).toHaveAttribute('target', '_blank')
    // noopener: the price list gets a window.opener handle otherwise.
    expect(a.getAttribute('rel')).toMatch(/noopener/)
  })
})
