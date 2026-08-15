/**
 * What the notification surfaces do when /entitlements has not answered, or
 * has failed.
 *
 * `has()` in api/hooks.ts is fail-closed on purpose: a paid feature must
 * never unlock because a request failed. But it is a security default, not a
 * statement of fact, and both surfaces here used to read it as one. A user
 * whose /entitlements call 500s lost the bell from the topbar and had every
 * job completion and alert thrown away as it arrived, leaving nothing at all
 * that said whether their install worked.
 *
 * `ent.data != null` is what separates "not entitled" from "could not
 * check", the same guard routes/hosts.tsx, routes/store.tsx and
 * routes/settings.tsx use.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

/** What GET /entitlements does this test. */
let entitlements: 'pro' | 'free' | 'error' | 'pending' = 'pro'

vi.mock('../api/client', () => ({
  api: vi.fn((path: string) => {
    if (path !== '/entitlements') return Promise.resolve([])
    if (entitlements === 'error') return Promise.reject(new Error('boom'))
    if (entitlements === 'pending') return new Promise(() => {})
    return Promise.resolve({
      tier: entitlements === 'pro' ? 'pro' : 'builtin', grace: null, clock_skew: false,
      features: { 'notify.inapp': entitlements === 'pro' },
    })
  }),
  ApiError: class extends Error {},
}))
vi.mock('../components/AccountMenu', () => ({ AccountMenu: () => null }))
vi.mock('../components/TierPill', () => ({ TierPill: () => null }))
vi.mock('../components/CommandPalette', () => ({ openCommandPalette: vi.fn() }))
vi.mock('../components/BellPopover', () => ({
  BellPopover: () => <button aria-label="Activity">bell</button>,
}))
vi.mock('@tanstack/react-router', async (orig) => ({
  ...(await orig() as object),
  Link: ({ to, children, ...rest }: { to?: string; children?: unknown }) =>
    <a href={to} {...rest}>{children as never}</a>,
}))

import { LiveProvider } from '../components/LiveProvider'
import { Topbar } from '../components/Topbar'
import { getNotifications, resetNotificationStore } from '../lib/notificationStore'
import { FakeEventSource, installFakeEventSource } from './fakeEventSource'

const wrap = (ui: React.ReactNode) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

beforeEach(() => {
  entitlements = 'pro'
  resetNotificationStore()
})

describe('the topbar bell', () => {
  it('stays when the plan could not be checked', async () => {
    entitlements = 'error'
    wrap(<Topbar />)
    // Not a fail-open: the tray shows /jobs, which the backend authorises on
    // its own. Hiding it would assert a plan limit that was never read.
    expect(await screen.findByRole('button', { name: 'Activity' })).toBeInTheDocument()
    expect(screen.queryByRole('status', { name: 'Checking your plan' })).toBeNull()
  })

  it('shows a placeholder, not an empty slot, while the plan is still being checked', () => {
    entitlements = 'pending'
    wrap(<Topbar />)
    expect(screen.getByRole('status', { name: 'Checking your plan' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Activity' })).toBeNull()
  })

  it('goes away for a plan that was read and genuinely lacks the feature', async () => {
    entitlements = 'free'
    wrap(<Topbar />)
    await waitFor(() =>
      expect(screen.queryByRole('status', { name: 'Checking your plan' })).toBeNull())
    expect(screen.queryByRole('button', { name: 'Activity' })).toBeNull()
  })
})

describe('live job and alert events', () => {
  const finished = {
    id: 7, kind: 'app.install', status: 'succeeded',
    target_type: 'app', target_id: 1,
  }

  it('are still recorded when the plan could not be checked', async () => {
    entitlements = 'error'
    const uninstall = installFakeEventSource()
    try {
      wrap(<LiveProvider>{null}</LiveProvider>)
      await waitFor(() => expect(FakeEventSource.last).toBeDefined())
      FakeEventSource.last.emit('job', finished)
      // The events are not replayed, so dropping them here is permanent: the
      // operator never finds out whether the install succeeded.
      await waitFor(() => expect(getNotifications()).toHaveLength(1))
    } finally {
      uninstall()
    }
  })

  it('are dropped for a plan that was read and genuinely lacks the feature', async () => {
    entitlements = 'free'
    const uninstall = installFakeEventSource()
    try {
      // Topbar is mounted alongside only so its bell can act as the signal
      // that /entitlements has actually landed; firing before it does would
      // pass for the wrong reason.
      wrap(<LiveProvider><Topbar /></LiveProvider>)
      await waitFor(() =>
        expect(screen.queryByRole('status', { name: 'Checking your plan' })).toBeNull())
      FakeEventSource.last.emit('job', finished)
      expect(getNotifications()).toHaveLength(0)
    } finally {
      uninstall()
    }
  })
})
