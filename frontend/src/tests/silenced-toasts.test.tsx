/**
 * The master switch silences the toast as well as the Apprise send.
 *
 * Deliberately NOT done by suppressing the SSE publish: applyJob does the
 * react-query invalidation and the toast from the same delta, so dropping the
 * publish would stop the Jobs page updating live rather than merely silencing
 * a notification. The gate sits in the toast callback, next to the
 * notify.inapp one, and leaves the data path alone.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

let silenced: string[] = []

vi.mock('../api/client', () => ({
  ApiError: class extends Error {},
  api: vi.fn((path: string) => {
    if (path === '/entitlements') {
      return Promise.resolve({
        tier: 'pro', features: { 'notify.inapp': true },
        grace: null, clock_skew: false,
      })
    }
    if (path === '/notifications/types') {
      return Promise.resolve({
        types: [
          { key: 'job.succeeded', label: 'Job succeeded', group: 'Other jobs',
            enabled: !silenced.includes('job.succeeded') },
          { key: 'job.failed', label: 'Job failed', group: 'Other jobs',
            enabled: !silenced.includes('job.failed') },
          { key: 'alert.fired', label: 'Alert triggered', group: 'Alerts',
            enabled: !silenced.includes('alert.fired') },
        ],
      })
    }
    return Promise.resolve([])
  }),
}))

import { LiveProvider } from '../components/LiveProvider'
import { getNotifications, resetNotificationStore } from '../lib/notificationStore'
import { FakeEventSource, installFakeEventSource } from './fakeEventSource'

const wrap = () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <LiveProvider><div /></LiveProvider>
    </QueryClientProvider>)
  return qc
}

const done = (extra: Record<string, unknown>) => ({
  id: 7, kind: 'vm.create', status: 'succeeded',
  target_type: 'vm', ...extra,
})

describe('a silenced notification type', () => {
  let uninstall: () => void
  beforeEach(() => {
    silenced = []
    resetNotificationStore()
    uninstall = installFakeEventSource()
    return () => uninstall()
  })

  it('does not toast a job whose type the operator turned off', async () => {
    silenced = ['job.succeeded']
    wrap()
    await waitFor(() => expect(FakeEventSource.last).toBeTruthy())
    // Let the types query resolve before the event arrives.
    await waitFor(() => expect(getNotifications()).toHaveLength(0))
    FakeEventSource.last.emit('job', done({ notify_type: 'job.succeeded' }))
    expect(getNotifications()).toHaveLength(0)
  })

  it('still toasts a type that is left on', async () => {
    silenced = ['job.succeeded']
    const qc = wrap()
    await waitFor(() => expect(FakeEventSource.last).toBeTruthy())
    await waitFor(() =>
      expect(qc.getQueryData(['notifications', 'types'])).toBeTruthy())
    FakeEventSource.last.emit('job', done({ status: 'failed', error: 'nope',
                                            notify_type: 'job.failed' }))
    await waitFor(() => expect(getNotifications()).toHaveLength(1))
  })

  it('toasts a delta that carries no notify_type', async () => {
    // Progress deltas have no terminal type. Treating absent as off would
    // silence every running job.
    silenced = ['job.succeeded']
    const qc = wrap()
    await waitFor(() => expect(FakeEventSource.last).toBeTruthy())
    await waitFor(() =>
      expect(qc.getQueryData(['notifications', 'types'])).toBeTruthy())
    FakeEventSource.last.emit('job', done({ status: 'failed', error: 'nope' }))
    await waitFor(() => expect(getNotifications()).toHaveLength(1))
  })

  it('silences a resolved alert when Alert triggered is off', async () => {
    silenced = ['alert.fired']
    const qc = wrap()
    await waitFor(() => expect(FakeEventSource.last).toBeTruthy())
    await waitFor(() =>
      expect(qc.getQueryData(['notifications', 'types'])).toBeTruthy())
    FakeEventSource.last.emit('alert', { id: 3, state: 'firing',
                                         severity: 'critical', message: 'down' })
    expect(getNotifications()).toHaveLength(0)
  })
})
