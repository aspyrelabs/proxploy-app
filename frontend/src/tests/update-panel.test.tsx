/** UpdatePanel (frontend/src/routes/apps.tsx): the app-detail "Update to vX"
 *  flow. services/appstore.py::run_update reports the same three-step
 *  ctx.progress(10)/(80)/(100) run_install does. Location 1 of the
 *  determinate loading pass covers both, and this file is the update half. */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { FakeEventSource, installFakeEventSource } from './fakeEventSource'

const { toastSuccess } = vi.hoisted(() => ({ toastSuccess: vi.fn() }))
vi.mock('sonner', () => ({ toast: { success: toastSuccess, error: vi.fn() } }))

let updateJob: { id: number; kind: string; progress_pct: number | null } = {
  id: 21, kind: 'app.update', progress_pct: null,
}

vi.mock('../api/client', () => ({
  ApiError: class extends Error {},
  api: vi.fn((path: string, opts?: RequestInit) => {
    if (path === '/entitlements') {
      return Promise.resolve({
        tier: 'pro', features: { 'store.updates': true }, grace: null, clock_skew: false,
      })
    }
    if (path === '/apps/5/update' && opts?.method === 'POST') {
      return Promise.resolve({ job: updateJob })
    }
    if (path === '/apps/5/update') {
      return Promise.resolve({
        update_available: 'abc1234', from_ref: 'deadbee', to_ref: 'abc1234', diff_vs_upstream: null,
      })
    }
    if (path === `/jobs/${updateJob.id}/events`) return Promise.resolve([])
    return Promise.resolve(null)
  }),
}))

import { UpdatePanel } from '../routes/apps'

const wrap = () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <UpdatePanel appId={5} app={{ name: 'Immich', update_available: 'abc1234' }} />
    </QueryClientProvider>,
  )
}

const startUpdate = async () => {
  fireEvent.click(await screen.findByRole('checkbox'))
  fireEvent.click(screen.getByRole('button', { name: /update to/i }))
}

describe('UpdatePanel', () => {
  it('shows no ring until the update job reports progress, then reflects a live update', async () => {
    updateJob = { id: 21, kind: 'app.update', progress_pct: null }
    const restore = installFakeEventSource()
    wrap()
    await startUpdate()

    await waitFor(() => expect(toastSuccess).toHaveBeenCalled())
    expect(screen.queryByRole('status')).toBeNull()

    FakeEventSource.last.emit('progress', { pct: 80 })
    await waitFor(() => expect(screen.getByRole('status')).toHaveAttribute(
      'aria-label', expect.stringContaining('80 percent')))

    restore()
  })

  it('seeds the ring from the job row instead of starting at zero', async () => {
    updateJob = { id: 22, kind: 'app.update', progress_pct: 10 }
    wrap()
    await startUpdate()

    await waitFor(() => expect(screen.getByRole('status')).toHaveAttribute(
      'aria-label', expect.stringContaining('10 percent')))
  })
})
