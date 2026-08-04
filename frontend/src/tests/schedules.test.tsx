import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

const posted: { path: string; method: string; body: any }[] = []
let schedules: any[] = []

vi.mock('../api/client', () => ({
  ApiError: class extends Error {},
  api: vi.fn((path: string, opts?: RequestInit) => {
    const method = (opts?.method ?? 'GET').toUpperCase()
    if (method !== 'GET') {
      posted.push({ path, method, body: opts?.body ? JSON.parse(String(opts.body)) : null })
      return Promise.resolve({ id: 5, job: { id: 1, kind: 'backup.run' } })
    }
    if (path === '/schedules') return Promise.resolve(schedules)
    if (path === '/hosts') return Promise.resolve([{ id: 1, name: 'host-01' }])
    if (path === '/entitlements') return Promise.resolve({
      tier: 'builtin', features: { 'sched.windows': true, 'store.auto_update': true },
      grace: null })
    return Promise.resolve([])
  }),
}))

import { ScheduleForm } from '../components/ScheduleForm'
import { SchedulesCard } from '../routes/settings'

const wrap = (ui: React.ReactNode) => {
  const qc = new QueryClient({ defaultOptions: {
    queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

describe('ScheduleForm', () => {
  it('posts name, job kind, cron and timezone', async () => {
    posted.length = 0
    wrap(<ScheduleForm onSaved={() => {}} />)
    fireEvent.change(screen.getByLabelText(/name/i), { target: { value: 'Nightly backup' } })
    fireEvent.change(screen.getByLabelText(/what to run/i), { target: { value: 'backup.run' } })
    fireEvent.change(screen.getByLabelText(/cron/i), { target: { value: '0 2 * * *' } })
    fireEvent.click(screen.getByRole('button', { name: /create schedule/i }))
    await waitFor(() => expect(posted.length).toBe(1))
    expect(posted[0].path).toBe('/schedules')
    expect(posted[0].body).toMatchObject({
      name: 'Nightly backup', job_kind: 'backup.run', cron: '0 2 * * *',
    })
    expect(typeof posted[0].body.timezone).toBe('string')
  })

  it('defaults the timezone to the browser zone rather than UTC', () => {
    posted.length = 0
    wrap(<ScheduleForm onSaved={() => {}} />)
    const tz = (screen.getByLabelText(/timezone/i) as HTMLInputElement).value
    expect(tz).toBe(Intl.DateTimeFormat().resolvedOptions().timeZone)
  })

  it('asks which host a backup schedule targets', async () => {
    posted.length = 0
    wrap(<ScheduleForm onSaved={() => {}} />)
    fireEvent.change(screen.getByLabelText(/what to run/i), { target: { value: 'backup.run' } })
    await waitFor(() => expect(screen.getByLabelText(/host/i)).toBeInTheDocument())
  })

  it('honours a pinned job kind and hides the picker', () => {
    posted.length = 0
    wrap(<ScheduleForm jobKind="backup.run" onSaved={() => {}} />)
    expect(screen.queryByLabelText(/what to run/i)).toBeNull()
  })
})

describe('SchedulesCard', () => {
  it('lists schedules with their next run', async () => {
    posted.length = 0
    schedules = [{ id: 1, name: 'Nightly backup', job_kind: 'backup.run',
                   cron: '0 2 * * *', timezone: 'UTC', params: { host_id: 1 },
                   enabled: true, created_by: 1,
                   last_run_at: null, next_run_at: '2026-08-02T02:00:00Z' }]
    wrap(<SchedulesCard />)
    await waitFor(() => expect(screen.getByText('Nightly backup')).toBeInTheDocument())
    expect(screen.getByText('0 2 * * *')).toBeInTheDocument()
  })

  it('runs a schedule now', async () => {
    posted.length = 0
    schedules = [{ id: 1, name: 'Nightly backup', job_kind: 'backup.run',
                   cron: '0 2 * * *', timezone: 'UTC', params: {}, enabled: true,
                   created_by: 1, last_run_at: null, next_run_at: null }]
    wrap(<SchedulesCard />)
    await waitFor(() => screen.getByRole('button', { name: /run now/i }))
    fireEvent.click(screen.getByRole('button', { name: /run now/i }))
    await waitFor(() => expect(posted.length).toBe(1))
    expect(posted[0]).toMatchObject({ path: '/schedules/1/run', method: 'POST' })
  })

  it('disables a schedule', async () => {
    posted.length = 0
    schedules = [{ id: 1, name: 'Nightly backup', job_kind: 'backup.run',
                   cron: '0 2 * * *', timezone: 'UTC', params: {}, enabled: true,
                   created_by: 1, last_run_at: null, next_run_at: null }]
    wrap(<SchedulesCard />)
    await waitFor(() => screen.getByRole('button', { name: /disable/i }))
    fireEvent.click(screen.getByRole('button', { name: /disable/i }))
    await waitFor(() => expect(posted.length).toBe(1))
    expect(posted[0]).toMatchObject({ path: '/schedules/1', method: 'PATCH',
                                      body: { enabled: false } })
  })

  it('marks a system-owned schedule so it is not mistaken for a user one', async () => {
    posted.length = 0
    schedules = [{ id: 1, name: 'Catalog refresh', job_kind: 'catalog.refresh',
                   cron: '0 4 * * *', timezone: 'UTC', params: {}, enabled: true,
                   created_by: null, last_run_at: null, next_run_at: null }]
    wrap(<SchedulesCard />)
    await waitFor(() => expect(screen.getByText(/system/i)).toBeInTheDocument())
  })
})
