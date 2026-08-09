import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const calls: { path: string; method: string; body: any }[] = []
let features: Record<string, boolean> = { 'vms.snapshots': true }
let rollbackGuard = false

const SNAPS = [
  // PVE's snapshot list always carries a synthetic `current` row for the live
  // state; it is not a snapshot and must never be offered Rollback/Delete.
  { name: 'current', description: 'You are here!', snaptime: null, vmstate: false, parent: 'pre-upgrade' },
  { name: 'pre-upgrade', description: 'before the 24.04 jump', snaptime: 1785369600,
    vmstate: true, parent: null, size_bytes: 2147483648 },
]

vi.mock('../api/client', () => {
  class ApiError extends Error {
    status: number; body: unknown
    constructor(status: number, body: unknown) {
      super(`API ${status}`); this.status = status; this.body = body
    }
  }
  return {
    ApiError,
    api: vi.fn((path: string, opts?: RequestInit) => {
      if (path === '/entitlements') return Promise.resolve({ tier: 'builtin', features, grace: null, clock_skew: false })
      const method = (opts?.method ?? 'GET').toUpperCase()
      const body = opts?.body ? JSON.parse(String(opts.body)) : {}
      if (method === 'GET' && path === '/vms/9/snapshots') return Promise.resolve(SNAPS)
      calls.push({ path, method, body })
      if (rollbackGuard && path.endsWith('/rollback') && !body.confirm) {
        return Promise.reject(new ApiError(409, {
          error: 'confirm_required', confirm_phrase: 'win11',
          detail: 'Rolling back discards every change made since the snapshot.',
        }))
      }
      return Promise.resolve({ job: { id: 7, kind: 'vm.snapshot_create', status: 'queued' } })
    }),
  }
})

import { SnapshotPanel } from '../components/SnapshotPanel'

const wrap = (ui: React.ReactNode) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return { qc, ...render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>) }
}

describe('SnapshotPanel', () => {
  beforeEach(() => {
    calls.length = 0
    rollbackGuard = false
    features = { 'vms.snapshots': true }
  })

  it('renders Name/Created/Size rows and hides the synthetic current row', async () => {
    wrap(<SnapshotPanel vmId={9} vmName="win11" />)
    expect(await screen.findByText('pre-upgrade')).toBeInTheDocument()
    expect(screen.queryByText('current')).toBeNull()
    expect(screen.getByText('2026-07-30 00:00')).toBeInTheDocument()
    // fmtBytes is binary-unit with one decimal: 2147483648 -> "2.0 GiB"
    expect(screen.getByText('2.0 GiB')).toBeInTheDocument()
    expect(screen.getByText('RAM')).toBeInTheDocument()
  })

  it('takes a snapshot with name, description and the with-RAM flag', async () => {
    wrap(<SnapshotPanel vmId={9} vmName="win11" />)
    fireEvent.change(await screen.findByLabelText(/snapshot name/i), { target: { value: 'clean-install' } })
    fireEvent.change(screen.getByLabelText(/description/i), { target: { value: 'fresh' } })
    fireEvent.click(screen.getByLabelText(/include ram/i))
    fireEvent.click(screen.getByRole('button', { name: /take snapshot/i }))
    await waitFor(() => expect(calls.length).toBe(1))
    expect(calls[0]).toMatchObject({
      path: '/vms/9/snapshots', method: 'POST',
      body: { name: 'clean-install', description: 'fresh', vmstate: true },
    })
  })

  it('escalates a 409 confirm_required on rollback into the typed-confirmation dialog and retries', async () => {
    rollbackGuard = true
    wrap(<SnapshotPanel vmId={9} vmName="win11" />)
    fireEvent.click(await screen.findByRole('button', { name: /rollback/i }))
    expect(await screen.findByText(/discards every change made since the snapshot/i)).toBeInTheDocument()

    const input = screen.getByLabelText(/type/i)
    fireEvent.change(input, { target: { value: 'nope' } })
    expect(screen.getByRole('button', { name: /confirm/i })).toBeDisabled()

    fireEvent.change(input, { target: { value: 'win11' } })
    fireEvent.click(screen.getByRole('button', { name: /confirm/i }))
    await waitFor(() => expect(calls.length).toBe(2))
    expect(calls[1].path).toBe('/vms/9/snapshots/pre-upgrade/rollback')
    expect(calls[1].body).toEqual({ confirm: 'win11' })
  })

  it('deletes through window.confirm and invalidates the snapshot list', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)
    const { qc } = wrap(<SnapshotPanel vmId={9} vmName="win11" />)
    const spy = vi.spyOn(qc, 'invalidateQueries')
    fireEvent.click(await screen.findByRole('button', { name: /delete/i }))
    expect(confirmSpy).toHaveBeenCalled()
    await waitFor(() => expect(calls.length).toBe(1))
    expect(calls[0]).toMatchObject({ path: '/vms/9/snapshots/pre-upgrade', method: 'DELETE' })
    await waitFor(() => expect(spy).toHaveBeenCalledWith({ queryKey: ['vms', 9, 'snapshots'] }))
    confirmSpy.mockRestore()
  })

  it('does not delete when window.confirm is dismissed', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false)
    wrap(<SnapshotPanel vmId={9} vmName="win11" />)
    fireEvent.click(await screen.findByRole('button', { name: /delete/i }))
    expect(confirmSpy).toHaveBeenCalled()
    // run.mutate() reaches the mocked api() call on a later microtask, so a
    // synchronous check here would pass whether or not the guard actually
    // blocked it. Give the mutation a real chance to fire before asserting
    // it didn't (same tick-flush idiom as settings.test.tsx).
    await new Promise((r) => setTimeout(r, 10))
    expect(calls.length).toBe(0)
    confirmSpy.mockRestore()
  })

  it('disables every mutating control with a plan tooltip when vms.snapshots is off', async () => {
    features = { 'vms.snapshots': false }
    wrap(<SnapshotPanel vmId={9} vmName="win11" />)
    // "Take snapshot" is also disabled by an empty name field on first paint,
    // so waiting on it alone would pass before the snapshots query (and thus
    // the row-level Rollback/Delete buttons) ever resolves. Wait on a
    // data-dependent control first so the assertions below aren't racing it.
    expect(await screen.findByRole('button', { name: /rollback/i })).toBeDisabled()
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /take snapshot/i })).toBeDisabled())
    expect(screen.getByRole('button', { name: /delete/i })).toBeDisabled()
    expect(screen.getByRole('button', { name: /rollback/i }))
      .toHaveAttribute('title', 'Not included in your plan')
  })
})
