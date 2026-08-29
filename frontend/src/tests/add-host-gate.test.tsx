/**
 * The hosts.multi gate on "Add a host".
 *
 * This existed as a `blocked` prop defaulting to false, decided by each
 * caller. The Hosts page passed it and Settings > Hosts did not, so Settings
 * offered the whole form and the operator learned the answer from a 403 at
 * submit. The gate now lives inside AddHostDialog, so these cases are the
 * coverage for BOTH routes: neither one decides any more.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

let hosts: unknown = []
let entitlements: unknown = null
let entFails = false

vi.mock('../api/client', () => ({
  api: vi.fn((path: string) => {
    if (path === '/entitlements') {
      return entFails ? Promise.reject(new Error('unreachable'))
                      : Promise.resolve(entitlements)
    }
    if (path === '/hosts') return Promise.resolve(hosts)
    return Promise.resolve(null)
  }),
  ApiError: class extends Error {},
}))

import { AddHostDialog } from '../components/AddHostDialog'

const ent = (multi: boolean) => ({
  tier: multi ? 'pro' : 'builtin',
  features: { 'hosts.multi': multi },
  required_tier: multi ? {} : { 'hosts.multi': 'pro' },
  grace: null, clock_skew: false, refresh_error: null, reason: null,
})

function wrap() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <AddHostDialog onClose={() => {}} onCreated={() => {}} />
    </QueryClientProvider>)
}

const form = () => screen.queryByLabelText('Name')
const upsell = () => screen.queryByText(/second host is where the multi-host plan starts/i)

describe('adding a host is gated on hosts.multi', () => {
  beforeEach(() => { entFails = false })

  it('withholds the form once a host exists and the plan does not include more', async () => {
    hosts = [{ id: 1 }]
    entitlements = ent(false)
    wrap()
    expect(await screen.findByText(/second host is where the multi-host plan starts/i))
      .toBeInTheDocument()
    expect(form()).not.toBeInTheDocument()
  })

  it('offers the form for the FIRST host, which every plan includes', async () => {
    hosts = []
    entitlements = ent(false)
    wrap()
    expect(await screen.findByLabelText('Name')).toBeInTheDocument()
    expect(upsell()).not.toBeInTheDocument()
  })

  it('offers the form for a second host once the plan includes multi-host', async () => {
    hosts = [{ id: 1 }]
    entitlements = ent(true)
    wrap()
    expect(await screen.findByLabelText('Name')).toBeInTheDocument()
    expect(upsell()).not.toBeInTheDocument()
  })

  it('opens the form when the entitlement fetch failed, leaving the backend the authority', async () => {
    // Innocent until proven guilty, the rule app-gates.ts states. Showing an
    // upsell to someone who may well be entitled is the worse error, and
    // POST /hosts still refuses what it should refuse.
    hosts = [{ id: 1 }]
    entFails = true
    wrap()
    expect(await screen.findByLabelText('Name')).toBeInTheDocument()
    expect(upsell()).not.toBeInTheDocument()
  })
})
