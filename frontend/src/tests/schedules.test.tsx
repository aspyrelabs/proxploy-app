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
let guests = {
  apps: [{ id: 7, host_id: 1, name: 'Immich', ctid: 150 }] as any[],
  vms: [{ id: 9, host_id: 1, name: 'win11', vmid: 201 }] as any[],
}
let stores: any[] = [
  { host_id: 1, storage: 'pbs-ds', type: 'pbs', content: ['backup'] },
  { host_id: 1, storage: 'local-lvm', type: 'lvmthin', content: ['rootdir'] },
]
let schedulesError = false

const { notifyError } = vi.hoisted(() => ({ notifyError: vi.fn() }))
vi.mock('../lib/notify', () => ({ notify: { error: notifyError, success: vi.fn(), info: vi.fn(), warning: vi.fn() } }))

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
      // What a scheduled backup can now be pointed at: the guests on the host,
      // and the datastores that accept backups.
      if (path === '/apps') return Promise.resolve(guests.apps)
      if (path === '/vms') return Promise.resolve(guests.vms)
      if (path === '/storage') return Promise.resolve(stores)
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
    // The picker only exists once the job kind above sets `needs`
    // (ScheduleForm's `{needs && ...}`), so check that first: if the change
    // above ever stops taking effect, this says so instead of leaving the
    // wait below to time out with no hint of which step broke.
    expect(screen.getByLabelText(/host/i)).toBeInTheDocument()
    // Wait for the host list itself (not just the label), the picker's
    // <select> exists before its options do, and setting a value with no
    // matching <option> is a silent no-op (mirrors alerts.test.tsx's app pick).
    await waitFor(() => expect(screen.getByRole('option', { name: 'host-01' })).toBeInTheDocument())
    fireEvent.change(screen.getByLabelText(/host/i), { target: { value: '1' } })
    // Cron is still the stored format, so the escape hatch still posts it
    // verbatim; the presets below are just another way of writing one.
    fireEvent.change(screen.getByLabelText(/how often/i), { target: { value: 'custom' } })
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

  it('offers the browser\'s own zone list, with no bundled dependency', () => {
    posted.length = 0
    const { container } = wrap(<ScheduleForm onSaved={() => {}} />)
    const field = screen.getByLabelText(/timezone/i)
    // A real dropdown, not the input+datalist this was: a datalist draws no
    // affordance, so the field read as a label that happened to say the
    // resolved zone and the 418 behind it were invisible.
    expect(field.tagName).toBe('SELECT')
    const offered = [...container.querySelectorAll('#sc-tz option')]
      .map((o) => o.getAttribute('value'))
    expect(offered.length).toBeGreaterThan(100)
    expect(offered).toContain('Europe/London')
    // A browser that resolves to a legacy alias (Asia/Calcutta) while the list
    // carries only the canonical name must still find its own zone in there.
    expect(offered).toContain(Intl.DateTimeFormat().resolvedOptions().timeZone)
  })

  it('builds the cron from a preset, so nobody has to know cron', async () => {
    posted.length = 0
    hosts = [{ id: 1, name: 'host-01' }]
    wrap(<ScheduleForm jobKind="backup.run" onSaved={() => {}} />)
    fireEvent.change(screen.getByLabelText(/name/i), { target: { value: 'Nightly' } })
    fireEvent.change(screen.getByLabelText(/how often/i), { target: { value: 'week' } })
    fireEvent.change(screen.getByLabelText(/^at$/i), { target: { value: '03:30' } })
    fireEvent.change(screen.getByLabelText(/^on$/i), { target: { value: '2' } })
    await waitFor(() => expect(screen.getByRole('option', { name: 'host-01' })).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: /create schedule/i }))
    await waitFor(() => expect(posted.length).toBe(1))
    // Still cron on the wire: `Schedule.cron` is the stored format and
    // jobs/scheduler.py parses nothing else, so the presets write one rather
    // than introducing a second format.
    expect(posted[0].body.cron).toBe('30 3 * * 2')
  })

  it('previews in plain language whichever cron is in effect', () => {
    posted.length = 0
    wrap(<ScheduleForm jobKind="backup.run" onSaved={() => {}} />)
    // The default preset.
    expect(screen.getByText('every day at 02:00')).toBeInTheDocument()
    // And a hand-typed expression, described by the same sentence: the preview
    // reads the string that gets posted, so it cannot describe one schedule
    // while another is saved.
    fireEvent.change(screen.getByLabelText(/how often/i), { target: { value: 'custom' } })
    fireEvent.change(screen.getByLabelText(/cron/i), { target: { value: '15 6 * * 5' } })
    expect(screen.getByText('every Friday at 06:15')).toBeInTheDocument()
  })

  it('asks which host a backup schedule targets', () => {
    posted.length = 0
    wrap(<ScheduleForm onSaved={() => {}} />)
    fireEvent.change(screen.getByLabelText(/what to run/i), { target: { value: 'backup.run' } })
    // Not waitFor: the picker is behind `{needs && ...}`, and `needs` is set
    // by the line above with no query in between, so it is there on the next
    // render or not at all. Waiting for a thing that cannot arrive late only
    // buys a one-second timeout in place of an immediate, named failure.
    expect(screen.getByLabelText(/host/i)).toBeInTheDocument()
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
    notifyError.mockClear()
    postError = { status: 403, body: { error: 'entitlement_required', feature: 'sched.windows' } }
    wrap(<ScheduleForm onSaved={() => {}} />)
    fireEvent.change(screen.getByLabelText(/name/i), { target: { value: 'x' } })
    await waitFor(() => expect(screen.getByRole('option', { name: 'host-01' })).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: /create schedule/i }))
    await waitFor(() => expect(posted.length).toBe(1))
    await waitFor(() => expect(notifyError).toHaveBeenCalledWith('Not included in your plan.'))
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
    // The Runs column names the job, it does not print its identifier. This
    // is the surface that went on saying "metrics.maintain" after the label
    // for that kind had already been renamed everywhere else.
    // "Backup Run" is now ACTION_LABEL's own entry, not a second phrasing
    // built for this column: the labels are neutral, so what a schedule runs
    // and what a finished row is called are the same words.
    expect(screen.getByText('Backup Run')).toBeInTheDocument()
    expect(screen.queryByText('backup.run')).not.toBeInTheDocument()
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

describe('ScheduleForm, backup targets', () => {
  // A scheduled backup used to carry nothing but host_id: it dumped every guest
  // on the node onto whichever datastore Proxmox picked, and the form could not
  // say which. run_backup has always read `vmids` and `storage` out of params.
  it('sends the ticked guests as vmids and the chosen datastore', async () => {
    posted.length = 0
    hosts = [{ id: 1, name: 'host-01' }]
    wrap(<ScheduleForm jobKind="backup.run" onSaved={() => {}} />)
    fireEvent.change(screen.getByLabelText(/name/i), { target: { value: 'Nightly' } })
    fireEvent.click(await screen.findByLabelText('win11 (VM 201)'))   // untick the VM
    expect(screen.getByLabelText(/archive lands on/i)).toHaveValue('pbs-ds')
    fireEvent.click(screen.getByRole('button', { name: /create schedule/i }))
    await waitFor(() => expect(posted.length).toBe(1))
    // PVE vmids, not Proxploy row ids: params go straight to the job handler.
    expect(posted[0].body.params).toEqual({ host_id: 1, storage: 'pbs-ds', vmids: [150] })
  })

  it('omits vmids entirely while every guest is ticked, so later ones are covered', async () => {
    posted.length = 0
    hosts = [{ id: 1, name: 'host-01' }]
    wrap(<ScheduleForm jobKind="backup.run" onSaved={() => {}} />)
    fireEvent.change(screen.getByLabelText(/name/i), { target: { value: 'Nightly' } })
    await screen.findByLabelText('Immich (CT 150)')
    fireEvent.click(screen.getByRole('button', { name: /create schedule/i }))
    await waitFor(() => expect(posted.length).toBe(1))
    expect(posted[0].body.params).toEqual({ host_id: 1, storage: 'pbs-ds' })
  })

  it('will not save a job whose guest list has been emptied', async () => {
    posted.length = 0
    hosts = [{ id: 1, name: 'host-01' }]
    wrap(<ScheduleForm jobKind="backup.run" onSaved={() => {}} />)
    fireEvent.change(screen.getByLabelText(/name/i), { target: { value: 'Nightly' } })
    fireEvent.click(await screen.findByRole('button', { name: 'Clear' }))
    expect(screen.getByRole('button', { name: /create schedule/i })).toBeDisabled()
    expect(posted.length).toBe(0)
  })
})
