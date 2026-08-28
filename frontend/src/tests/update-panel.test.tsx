/** UpdatePanel (frontend/src/routes/apps.tsx): the app-detail "Update to vX"
 *  flow. run_update reports three checkpoints, which is not enough to draw a
 *  rate from, so the panel spins rather than counting and says how the job
 *  ended once it settles. */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

const { notifySuccess } = vi.hoisted(() => ({ notifySuccess: vi.fn() }))
vi.mock('../lib/notify', () => ({ notify: { success: notifySuccess, error: vi.fn(), info: vi.fn(), warning: vi.fn() } }))

let updateJob: { id: number; kind: string; progress_pct: number | null } = {
  id: 21, kind: 'app.update', progress_pct: null,
}
// What GET /jobs/{id} answers while the panel watches the job it started.
let jobStatus = 'running'

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
    if (path === `/jobs/${updateJob.id}`) {
      return Promise.resolve({ id: updateJob.id, kind: 'app.update', status: jobStatus,
                               progress_pct: null, error: null })
    }
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
  it('spins without claiming a figure, and keeps the transcript one click away', async () => {
    updateJob = { id: 21, kind: 'app.update', progress_pct: null }
    jobStatus = 'running'
    wrap()
    await startUpdate()

    await waitFor(() => expect(notifySuccess).toHaveBeenCalled())
    // Indeterminate: the ring names what it is waiting on and no percentage,
    // because three checkpoints cannot say how far along anything is.
    await waitFor(() => expect(screen.getByRole('status'))
      .toHaveAttribute('aria-label', 'Updating Immich'))
    expect(screen.getByRole('status').getAttribute('aria-label')).not.toMatch(/percent/)
    expect(screen.getByText('Updating…')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Logs' })).toBeInTheDocument()
  })

  it('says how the update ended instead of spinning for ever', async () => {
    updateJob = { id: 22, kind: 'app.update', progress_pct: null }
    jobStatus = 'succeeded'
    wrap()
    await startUpdate()

    await waitFor(() => expect(screen.getByText('Updated Immich.')).toBeInTheDocument())
    expect(screen.queryByRole('status')).toBeNull()
    expect(screen.getByRole('button', { name: 'Logs' })).toBeInTheDocument()
  })
})
