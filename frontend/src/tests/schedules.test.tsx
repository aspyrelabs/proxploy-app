import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

const posted: { path: string; method: string; body: any }[] = []
let schedules: any[] = []
// Mutable so the "target required" test can put more than one host in play, 
// with exactly one, ScheduleForm auto-selects it and there is nothing to gate.
let hosts: any[] = [{ id: 1, name: 'host-01' }]
let features: Record<string, boolean> = { 'sched.windows': true, 'store.auto_update': true }
let postError: { status: number; body: any } | null = null
let schedulesError = false

const { toastError } = vi.hoisted(() => ({ toastError: vi.fn() }))
vi.mock('sonner', () => ({ toast: { error: toastError, success: vi.fn() } }))

vi.mock('../api/client', () => {
  class ApiError extends Error {
    status: number
    body: any
    constructor(status: number, body: any) {
      super(`API ${status}`)
      this.status = status
      this.body = body
    }
  }
  return {
    ApiError,
    api: vi.fn((path: string, opts?: RequestInit) => {
      const method = (opts?.method ?? 'GET').toUpperCase()
      if (method !== 'GET') {
        posted.push({ path, method, body: opts?.body ? JSON.parse(String(opts.body)) : null })
        if (postError) return Promise.reject(new ApiError(postError.status, postError.body))
        return Promise.resolve({ id: 5, job: { id: 1, kind: 'backup.run' } })
      }
      if (path === '/schedules') {
        if (schedulesError) return Promise.reject(new ApiError(502, { detail: 'boom' }))
        return Promise.resolve(schedules)
      }
      if (path === '/hosts') return Promise.resolve(hosts)
      if (path === '/entitlements') return Promise.resolve({ tier: 'builtin', features, grace: null, clock_skew: false })
      return Promise.resolve([])
    }),
  }
})

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
    hosts = [{ id: 1, name: 'host-01' }]
    wrap(<ScheduleForm onSaved={() => {}} />)
    fireEvent.change(screen.getByLabelText(/name/i), { target: { value: 'Nightly backup' } })
    fireEvent.change(screen.getByLabelText(/what to run/i), { target: { value: 'backup.run' } })
    // Wait for the host list itself (not just the label), the picker's
    // <select> exists before its options do, and setting a value with no
    // matching <option> is a silent no-op (mirrors alerts.test.tsx's app pick).
    await waitFor(() => expect(screen.getByRole('option', { name: 'host-01' })).toBeInTheDocument())
    fireEvent.change(screen.getByLabelText(/host/i), { target: { value: '1' } })
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

  it('keeps Create schedule disabled until a required target is chosen', async () => {
    posted.length = 0
    // More than one host: nothing to auto-select, so "Select…" must gate submit.
    hosts = [{ id: 1, name: 'host-01' }, { id: 2, name: 'host-02' }]
    wrap(<ScheduleForm jobKind="backup.run" onSaved={() => {}} />)
    const submit = screen.getByRole('button', { name: /create schedule/i })
    await waitFor(() => expect(screen.getByRole('option', { name: 'host-02' })).toBeInTheDocument())
    expect(submit).toBeDisabled()
    fireEvent.change(screen.getByLabelText(/host/i), { target: { value: '2' } })
    expect(submit).toBeEnabled()
    hosts = [{ id: 1, name: 'host-01' }]
  })

  it('shows an entitlement message, not the generic one, on a 403', async () => {
    posted.length = 0
    toastError.mockClear()
    postError = { status: 403, body: { error: 'entitlement_required', feature: 'sched.windows' } }
    wrap(<ScheduleForm onSaved={() => {}} />)
    fireEvent.change(screen.getByLabelText(/name/i), { target: { value: 'x' } })
    await waitFor(() => expect(screen.getByRole('option', { name: 'host-01' })).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: /create schedule/i }))
    await waitFor(() => expect(posted.length).toBe(1))
    await waitFor(() => expect(toastError).toHaveBeenCalledWith('Not included in your plan.'))
    postError = null
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

  it('says the schedules could not be read rather than showing "no schedules yet"', async () => {
    posted.length = 0
    schedulesError = true
    wrap(<SchedulesCard />)
    expect(await screen.findByText(/schedules not readable/i)).toBeInTheDocument()
    expect(screen.queryByText('No schedules yet')).not.toBeInTheDocument()
    schedulesError = false
  })

  it('shows the real empty-schedules copy when there genuinely are none', async () => {
    posted.length = 0
    schedules = []
    wrap(<SchedulesCard />)
    expect(await screen.findByText('No schedules yet')).toBeInTheDocument()
  })

  it('hides New schedule and Run now without sched.windows', async () => {
    posted.length = 0
    features = { 'sched.windows': false, 'store.auto_update': true }
    schedules = [{ id: 1, name: 'Nightly backup', job_kind: 'backup.run',
                   cron: '0 2 * * *', timezone: 'UTC', params: {}, enabled: true,
                   created_by: 1, last_run_at: null, next_run_at: null }]
    wrap(<SchedulesCard />)
    await waitFor(() => expect(screen.getByText('Nightly backup')).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: /new schedule/i })).toBeNull()
    expect(screen.queryByRole('button', { name: /run now/i })).toBeNull()
    features = { 'sched.windows': true, 'store.auto_update': true }
  })
})
