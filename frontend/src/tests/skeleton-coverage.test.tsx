/**
 * A sample of the surfaces the second pass covered, one per mechanism, checked
 * end to end: pending draws a placeholder of the right shape, and the
 * placeholder is GONE once the data lands rather than left animating under it.
 *
 * Deliberately a sample and not one case per file. What can actually break
 * here is the wiring, a `loading` prop that never reaches QueryState, an
 * `isPending` branch ordered after the empty check, a placeholder that outlives
 * its query. Those are properties of the four mechanisms below, not of the
 * thirty call sites, and the shapes themselves are measured in skeleton.test.tsx.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

/** path -> the promise that call should return. Set per test. */
let routes: Record<string, Promise<unknown>> = {}

vi.mock('../api/client', () => ({
  api: vi.fn((path: string) => routes[path] ?? Promise.resolve([])),
  ApiError: class extends Error {},
}))

vi.mock('../lib/notify', () => ({
  notify: { error: vi.fn(), success: vi.fn(), info: vi.fn() },
}))

import { AlertRuleForm } from '../components/AlertRuleForm'
import { SessionsCard } from '../components/SessionsCard'
import { SnapshotPanel } from '../components/SnapshotPanel'

/** A promise this test decides when to settle, which is the only way to hold a
 *  component in its pending state long enough to look at it. */
function deferred<T>() {
  let resolve!: (v: T) => void
  const promise = new Promise<T>((r) => { resolve = r })
  return { promise, resolve }
}

const wrap = (ui: React.ReactNode) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

const pulses = (c: HTMLElement) => c.querySelectorAll('.animate-pulse').length

beforeEach(() => {
  // Several of these components gate a control on an entitlement. Nothing here
  // is about plan gating, so every test gets the same fully-featured answer
  // and none of them has to think about it.
  routes = {
    '/entitlements': Promise.resolve({
      tier: 'builtin', grace: null, clock_skew: false,
      features: new Proxy({}, { get: () => true }),
    }),
  }
})

describe('a QueryState surface that had no `loading` prop', () => {
  // SessionsCard stands in for the eleven call sites that were falling through
  // to the default ring. What is checked is that the prop is wired at all.
  it('draws the table placeholder, then the real rows', async () => {
    const d = deferred<unknown>()
    routes['/auth/sessions'] = d.promise
    const { container } = wrap(<SessionsCard />)

    expect(screen.getByRole('status')).toHaveAttribute('aria-label', 'Loading sessions')
    expect(pulses(container)).toBeGreaterThan(0)
    // Not the ring: the whole point of the second pass.
    expect(screen.queryByLabelText('Loading')).not.toBeInTheDocument()

    d.resolve([{ id: 1, ip: '10.0.0.4', user_agent: 'Firefox', current: true,
                 created_at: '2026-01-01T00:00:00Z', last_seen_at: null }])

    await waitFor(() => expect(screen.getByText('10.0.0.4')).toBeInTheDocument())
    expect(pulses(container)).toBe(0)
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })
})

describe('a surface that was answering "empty" while it fetched', () => {
  // SnapshotPanel is the clearest of them: `rows` is [] until PVE answers, so
  // the panel stated "No snapshots" about a VM whose rollback points somebody
  // had opened the page to check.
  it('never claims the list is empty before it has looked', async () => {
    const d = deferred<unknown>()
    routes['/vms/7/snapshots'] = d.promise
    const { container } = wrap(<SnapshotPanel vmId={7} vmName="db-01" />)

    expect(screen.getByRole('status')).toHaveAttribute('aria-label', 'Loading snapshots')
    expect(screen.queryByText('No snapshots')).not.toBeInTheDocument()

    d.resolve([{ name: 'pre-upgrade', snaptime: 1767225600, size_bytes: 1024,
                 description: null, vmstate: false, parent: null }])

    await waitFor(() => expect(screen.getByText('pre-upgrade')).toBeInTheDocument())
    expect(pulses(container)).toBe(0)
  })

  it('still says "empty" when the answer really is empty', async () => {
    // The placeholder must not swallow the empty state, only precede it.
    routes['/vms/7/snapshots'] = Promise.resolve([])
    wrap(<SnapshotPanel vmId={7} vmName="db-01" />)
    await waitFor(() => expect(screen.getByText('No snapshots')).toBeInTheDocument())
  })
})

describe('a form whose fields are decided by a fetch', () => {
  // The Form pattern's one real call site. GET /alert-rules/metrics decides
  // which metrics exist, which targets each offers and whether the Threshold
  // pair is shown at all, so the form cannot honestly render before it lands.
  it('holds the form shape, then hands over the real fields', async () => {
    const d = deferred<unknown>()
    routes['/alert-rules/metrics'] = d.promise
    const { container } = wrap(<AlertRuleForm onSaved={() => {}} />)

    expect(screen.getByRole('status'))
      .toHaveAttribute('aria-label', 'Loading the alert rule form')
    // A live-looking Name box over an empty Metric select is the thing this
    // replaces, so no real control may be on screen yet.
    expect(screen.queryByLabelText('Name')).not.toBeInTheDocument()
    expect(container.querySelectorAll('input, select')).toHaveLength(0)

    d.resolve({ metrics: [{ metric: 'cpu_pct', targets: ['host', 'app'],
                            needs_threshold: true }] })

    await waitFor(() => expect(screen.getByLabelText('Metric')).toBeInTheDocument())
    expect(pulses(container)).toBe(0)
  })
})
