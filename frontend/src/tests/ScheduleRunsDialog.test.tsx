import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

let runs: any[] = []

vi.mock('../api/client', () => ({
  api: vi.fn((path: string) => {
    if (path === '/schedules/1/runs') return Promise.resolve(runs)
    if (path.startsWith('/jobs/') && path.endsWith('/events')) return Promise.resolve([])
    return Promise.resolve(null)
  }),
  ApiError: class extends Error {},
}))

import { ScheduleRunsDialog } from '../components/ScheduleRunsDialog'
import type { ScheduleRow } from '../api/schedules'

const SCHEDULE: ScheduleRow = {
  id: 1, name: 'Nightly backup', job_kind: 'backup.run', cron: '0 2 * * *',
  timezone: 'UTC', params: {}, enabled: true, created_by: 1,
  last_run_at: null, next_run_at: null, last_run: null,
}

const FAILED = {
  id: 101, kind: 'backup.run', status: 'failed', target_type: 'host', target_id: 1,
  target_name: 'host-01', params: {}, result: {}, error: 'vzdump exited 2',
  progress_pct: null, requested_by: null, schedule_id: 1,
  started_at: '2026-08-20T10:00:00Z', finished_at: '2026-08-20T10:00:05Z',
  created_at: '2026-08-20T10:00:00Z',
}

const SUCCEEDED = {
  id: 100, kind: 'backup.run', status: 'succeeded', target_type: 'host', target_id: 1,
  target_name: 'host-01', params: {}, result: {}, error: null,
  progress_pct: null, requested_by: null, schedule_id: 1,
  started_at: '2026-08-19T10:00:00Z', finished_at: '2026-08-19T10:00:02Z',
  created_at: '2026-08-19T10:00:00Z',
}

const wrap = () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <ScheduleRunsDialog schedule={SCHEDULE} onClose={() => {}} />
    </QueryClientProvider>)
}

describe('ScheduleRunsDialog', () => {
  it('lists both runs with their outcome label and duration', async () => {
    runs = [FAILED, SUCCEEDED]
    wrap()
    await waitFor(() => expect(screen.getByRole('table')).toBeInTheDocument())
    const list = within(screen.getByRole('table'))
    expect(list.getByText('Failed')).toBeInTheDocument()
    expect(list.getByText('Done')).toBeInTheDocument()
    expect(list.getByText('5.0s')).toBeInTheDocument()
    expect(list.getByText('2.0s')).toBeInTheDocument()
  })

  it('selects the newest run by default', async () => {
    runs = [FAILED, SUCCEEDED]
    wrap()
    await waitFor(() => expect(screen.getByText('#101')).toBeInTheDocument())
    expect(screen.queryByText('#100')).toBeNull()
  })

  it('switches the selection when the other run is clicked', async () => {
    runs = [FAILED, SUCCEEDED]
    wrap()
    await waitFor(() => expect(screen.getByText('#101')).toBeInTheDocument())
    fireEvent.click(screen.getByText('2.0s').closest('tr')!)
    await waitFor(() => expect(screen.getByText('#100')).toBeInTheDocument())
    expect(screen.queryByText('#101')).toBeNull()
  })

  it('shows the job id, host and error text for a failed run', async () => {
    runs = [FAILED, SUCCEEDED]
    wrap()
    await waitFor(() => expect(screen.getByText('#101')).toBeInTheDocument())
    expect(screen.getByText('host-01')).toBeInTheDocument()
    expect(screen.getByText('vzdump exited 2')).toBeInTheDocument()
  })

  it('renders the empty copy when the schedule has no runs', async () => {
    runs = []
    wrap()
    expect(await screen.findByText(/has not run in the last 30 days/i)).toBeInTheDocument()
  })
})
