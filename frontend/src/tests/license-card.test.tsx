import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const calls: { path: string; body: unknown }[] = []
/** What POST /entitlements/license does next: 'ok', or the 409 shape the
 *  service sends when the seat is held. */
let activateResult: 'ok' | 'occupied' = 'ok'
let transferResult: 'ok' | 'denied' = 'ok'

const OCCUPANT = {
  installation_id: 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
  last_seen_at: new Date(Date.now() - 120_000).toISOString().replace('Z', ''),
  activated_at: null,
  stale: false,
}

// The class lives inside the factory: vi.mock is hoisted above every
// top-level declaration, so a class defined outside is still in its temporal
// dead zone when the factory runs.
vi.mock('../api/client', () => {
  class FakeApiError extends Error {
    status: number
    body: unknown
    constructor(status: number, body: unknown) {
      super(`API ${status}`)
      this.status = status
      this.body = body
    }
  }
  return {
  ApiError: FakeApiError,
  apiErrorDetail: (_e: unknown, fallback: string) => fallback,
  api: vi.fn((path: string, opts?: RequestInit) => {
    calls.push({ path, body: opts?.body ? JSON.parse(String(opts.body)) : null })
    if (path === '/entitlements/license' && opts?.method === 'POST') {
      if (activateResult === 'occupied') {
        // problem+json puts a dict detail at the top level, which is what the
        // card reads: nesting it under `detail` is the bug this pins.
        return Promise.reject(new FakeApiError(409, {
          error: 'license already active on another installation',
          occupant: OCCUPANT,
        }))
      }
      return Promise.resolve({ ok: true, tier: 'pro' })
    }
    if (path === '/entitlements/license/transfer') {
      if (transferResult === 'denied') return Promise.reject(new FakeApiError(502, {}))
      return Promise.resolve({ ok: true, tier: 'pro' })
    }
    if (path === '/entitlements/activations') {
      return Promise.resolve({ activations: [
        { id: 1, installation_id: 'old-install-1', status: 'transferred',
          conflict_reason: null, activated_at: null, last_seen_at: null,
          released_at: null, release_reason: 'force transfer', current: false },
        { id: 2, installation_id: 'new-install-2', status: 'active',
          conflict_reason: 'sequence regression', activated_at: null,
          last_seen_at: new Date().toISOString().replace('Z', ''),
          released_at: null, release_reason: null, current: true },
      ] })
    }
    return Promise.resolve({})
  }),
  }
})

import { LicenseCard } from '../components/LicenseCard'

function wrap(licensed = false, tier = 'free') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <LicenseCard tier={tier} licensed={licensed} />
    </QueryClientProvider>,
  )
}

describe('LicenseCard', () => {
  beforeEach(() => { calls.length = 0; activateResult = 'ok'; transferResult = 'ok' })

  it('shows the current tier alongside the activation field', () => {
    wrap()
    expect(screen.getByText('FREE')).toBeInTheDocument()
    expect(screen.getByLabelText('License key')).toBeInTheDocument()
  })

  it('will not submit an empty key', () => {
    wrap()
    expect(screen.getByRole('button', { name: 'Activate' })).toBeDisabled()
  })

  it('activates and sends the key', async () => {
    wrap()
    fireEvent.change(screen.getByLabelText('License key'), { target: { value: 'PPL-A' } })
    fireEvent.click(screen.getByRole('button', { name: 'Activate' }))
    await waitFor(() => expect(calls.some(c => c.path === '/entitlements/license')).toBe(true))
    expect(calls[0].body).toEqual({ license_key: 'PPL-A' })
  })

  it('turns a held seat into the transfer choice rather than an error line', async () => {
    activateResult = 'occupied'
    wrap()
    fireEvent.change(screen.getByLabelText('License key'), { target: { value: 'PPL-A' } })
    fireEvent.click(screen.getByRole('button', { name: 'Activate' }))

    expect(await screen.findByText(/already active on another installation/i))
      .toBeInTheDocument()
    // The owner has to recognise their own box, so recency is shown, not a
    // raw timestamp.
    expect(screen.getByText(/2 minutes ago/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Force Transfer' })).toBeInTheDocument()
  })

  it('requires a recovery code before it will transfer', async () => {
    activateResult = 'occupied'
    wrap()
    fireEvent.change(screen.getByLabelText('License key'), { target: { value: 'PPL-A' } })
    fireEvent.click(screen.getByRole('button', { name: 'Activate' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Force Transfer' }))

    const go = screen.getByRole('button', { name: 'Transfer license here' })
    expect(go).toBeDisabled()

    fireEvent.change(screen.getByLabelText('Recovery code'), { target: { value: 'RC-1' } })
    expect(go).not.toBeDisabled()
    fireEvent.click(go)

    await waitFor(() =>
      expect(calls.some(c => c.path === '/entitlements/license/transfer')).toBe(true))
    expect(calls.at(-1)!.body).toEqual({ license_key: 'PPL-A', recovery_code: 'RC-1' })
  })

  it('keeps the dialog open and explains a refused transfer', async () => {
    activateResult = 'occupied'
    transferResult = 'denied'
    wrap()
    fireEvent.change(screen.getByLabelText('License key'), { target: { value: 'PPL-A' } })
    fireEvent.click(screen.getByRole('button', { name: 'Activate' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Force Transfer' }))
    fireEvent.change(screen.getByLabelText('Recovery code'), { target: { value: 'nope' } })
    fireEvent.click(screen.getByRole('button', { name: 'Transfer license here' }))

    expect(await screen.findByText(/Check the recovery code/)).toBeInTheDocument()
    // Still open: a wrong code is a typo to correct, not a reason to make the
    // owner walk the whole flow again.
    expect(screen.getByLabelText('Recovery code')).toBeInTheDocument()
  })

  it('offers release, not transfer, once this installation holds the licence', () => {
    wrap(true, 'pro')
    expect(screen.getByRole('button', { name: 'Release license' })).toBeInTheDocument()
    expect(screen.queryByLabelText('License key')).not.toBeInTheDocument()
  })

  it('names a conflicting installation in the history', async () => {
    wrap(true, 'pro')
    fireEvent.click(screen.getByRole('button', { name: 'Installations' }))
    expect(await screen.findByText(/conflict: sequence regression/)).toBeInTheDocument()
    expect(screen.getByText('this installation')).toBeInTheDocument()
    expect(screen.getByText('transferred')).toBeInTheDocument()
  })
})
