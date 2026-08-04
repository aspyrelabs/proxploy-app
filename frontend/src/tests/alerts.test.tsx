import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

const posted: { path: string; method: string; body: any }[] = []
let features: Record<string, boolean> = { 'alerts.rules': true }
let firing: any[] = []
let rules: any[] = []

vi.mock('../api/client', () => ({
  ApiError: class extends Error {},
  api: vi.fn((path: string, opts?: RequestInit) => {
    const method = (opts?.method ?? 'GET').toUpperCase()
    if (method !== 'GET') {
      posted.push({ path, method, body: opts?.body ? JSON.parse(String(opts.body)) : null })
      return Promise.resolve({ id: 99 })
    }
    if (path === '/entitlements') return Promise.resolve({ tier: 'builtin', features, grace: null })
    if (path === '/alerts?state=firing') return Promise.resolve(firing)
    if (path.startsWith('/alerts')) return Promise.resolve(firing)
    if (path === '/alert-rules/metrics') return Promise.resolve({ metrics: [
      { metric: 'cpu_pct', targets: ['host', 'app', 'vm'], needs_threshold: true },
      { metric: 'disk_pct', targets: ['host'], needs_threshold: true },
      { metric: 'host_offline', targets: ['host'], needs_threshold: false },
    ]})
    if (path === '/alert-rules') return Promise.resolve(rules)
    if (path === '/notifications/channels') return Promise.resolve([])
    if (path === '/hosts') return Promise.resolve([{ id: 1, name: 'host-01' }])
    if (path === '/apps') return Promise.resolve([{ id: 5, name: 'jellyfin' }])
    return Promise.resolve([])
  }),
}))

import { AlertsPage } from '../routes/alerts'

const wrap = () => {
  const qc = new QueryClient({ defaultOptions: {
    queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={qc}><AlertsPage /></QueryClientProvider>)
}

describe('AlertsPage', () => {
  it('says nothing is firing when nothing is', async () => {
    posted.length = 0; firing = []; rules = []
    wrap()
    await waitFor(() => expect(screen.getByText(/nothing is firing/i)).toBeInTheDocument())
  })

  it('lists a firing alert with its target and severity', async () => {
    posted.length = 0
    firing = [{ id: 7, rule_id: 1, rule_name: 'CPU high', severity: 'critical',
                target_type: 'host', target_id: 1, target_label: 'host-02',
                state: 'firing', value: 92, message: 'host-02 CPU > 85% for 5m',
                fired_at: new Date().toISOString(), resolved_at: null,
                acked_by: null, acked_by_email: null, acked_at: null }]
    rules = []
    wrap()
    await waitFor(() => expect(screen.getByText(/host-02 CPU > 85% for 5m/)).toBeInTheDocument())
    expect(screen.getByText('critical')).toBeInTheDocument()
    expect(screen.getByText('host-02')).toBeInTheDocument()
  })

  it('acks an alert', async () => {
    posted.length = 0
    firing = [{ id: 7, rule_id: 1, rule_name: 'CPU high', severity: 'warning',
                target_type: 'host', target_id: 1, target_label: 'host-02',
                state: 'firing', value: 92, message: 'hot',
                fired_at: new Date().toISOString(), resolved_at: null,
                acked_by: null, acked_by_email: null, acked_at: null }]
    rules = []
    wrap()
    await waitFor(() => screen.getByRole('button', { name: /^ack$/i }))
    fireEvent.click(screen.getByRole('button', { name: /^ack$/i }))
    await waitFor(() => expect(posted.length).toBe(1))
    expect(posted[0]).toMatchObject({ path: '/alerts/7/ack', method: 'POST' })
  })

  it('shows an already-acked alert as acknowledged instead of an Ack button', async () => {
    posted.length = 0
    firing = [{ id: 7, rule_id: 1, rule_name: 'CPU high', severity: 'warning',
                target_type: 'host', target_id: 1, target_label: 'host-02',
                state: 'firing', value: 92, message: 'hot',
                fired_at: new Date().toISOString(), resolved_at: null,
                acked_by: 1, acked_by_email: 'admin@example.com',
                acked_at: new Date().toISOString() }]
    rules = []
    wrap()
    await waitFor(() => expect(screen.getByText(/admin@example.com/)).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: /^ack$/i })).toBeNull()
  })

  it('lock-veils the rules card when alerts.rules is unentitled', async () => {
    posted.length = 0; firing = []; rules = []
    features = { 'alerts.rules': false }
    wrap()
    await waitFor(() => expect(screen.getByText(/not included in your plan/i)).toBeInTheDocument())
    features = { 'alerts.rules': true }
  })

  it('creates a rule from the form', async () => {
    posted.length = 0; firing = []; rules = []
    wrap()
    await waitFor(() => screen.getByRole('button', { name: /new rule/i }))
    fireEvent.click(screen.getByRole('button', { name: /new rule/i }))
    fireEvent.change(screen.getByLabelText(/name/i), { target: { value: 'CPU high' } })
    fireEvent.change(screen.getByLabelText(/threshold/i), { target: { value: '85' } })
    fireEvent.change(screen.getByLabelText(/for at least/i), { target: { value: '300' } })
    fireEvent.click(screen.getByRole('button', { name: /create rule/i }))
    await waitFor(() => expect(posted.length).toBe(1))
    expect(posted[0].path).toBe('/alert-rules')
    expect(posted[0].body).toMatchObject({
      name: 'CPU high', metric: 'cpu_pct', threshold: 85, duration_s: 300,
      operator: 'gt', severity: 'warning',
    })
  })

  it('picks an app target and submits its id', async () => {
    posted.length = 0; firing = []; rules = []
    wrap()
    await waitFor(() => screen.getByRole('button', { name: /new rule/i }))
    fireEvent.click(screen.getByRole('button', { name: /new rule/i }))
    fireEvent.change(screen.getByLabelText(/name/i), { target: { value: 'App CPU high' } })
    fireEvent.change(screen.getByLabelText(/^target$/i), { target: { value: 'app' } })
    // Wait for the app list itself (not just the label) — the picker's
    // <select> exists before its options do, and setting a value with no
    // matching <option> is a silent no-op.
    await waitFor(() => expect(screen.getByRole('option', { name: 'jellyfin' })).toBeInTheDocument())
    fireEvent.change(screen.getByLabelText(/^app$/i), { target: { value: '5' } })
    fireEvent.click(screen.getByRole('button', { name: /create rule/i }))
    await waitFor(() => expect(posted.length).toBe(1))
    expect(posted[0].body).toMatchObject({ target_type: 'app', target_id: 5 })
  })

  it('hides threshold and operator for a status metric', async () => {
    posted.length = 0; firing = []; rules = []
    wrap()
    await waitFor(() => screen.getByRole('button', { name: /new rule/i }))
    fireEvent.click(screen.getByRole('button', { name: /new rule/i }))
    fireEvent.change(screen.getByLabelText(/^metric$/i), { target: { value: 'host_offline' } })
    await waitFor(() => expect(screen.queryByLabelText(/threshold/i)).toBeNull())
  })

  it('offers only the target kinds the chosen metric supports', async () => {
    posted.length = 0; firing = []; rules = []
    wrap()
    await waitFor(() => screen.getByRole('button', { name: /new rule/i }))
    fireEvent.click(screen.getByRole('button', { name: /new rule/i }))
    fireEvent.change(screen.getByLabelText(/^metric$/i), { target: { value: 'disk_pct' } })
    const select = screen.getByLabelText(/target/i) as HTMLSelectElement
    const opts = [...select.options].map(o => o.value)
    expect(opts).toContain('host')
    expect(opts).not.toContain('vm')      // the backend would 422 it anyway
  })

  it('toggles a rule off', async () => {
    posted.length = 0; firing = []
    rules = [{ id: 3, name: 'CPU high', metric: 'cpu_pct', target_type: 'any',
               target_id: null, operator: 'gt', threshold: 85, duration_s: 300,
               severity: 'warning', channel_ids: [], enabled: true }]
    wrap()
    await waitFor(() => screen.getByRole('button', { name: /disable/i }))
    fireEvent.click(screen.getByRole('button', { name: /disable/i }))
    await waitFor(() => expect(posted.length).toBe(1))
    expect(posted[0]).toMatchObject({ path: '/alert-rules/3', method: 'PATCH',
                                      body: { enabled: false } })
  })
})
