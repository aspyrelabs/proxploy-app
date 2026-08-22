import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

let channels: any[] = []
let routing = true
const patched: { path: string; body: any }[] = []

const TYPES = [
  { key: 'app.install.failed', label: 'App install failed', group: 'Apps', enabled: true },
  { key: 'backup.failed', label: 'Backup failed', group: 'Backups', enabled: true },
  { key: 'housekeeping.succeeded', label: 'Housekeeping succeeded', group: 'Housekeeping', enabled: false },
  { key: 'job.failed', label: 'Job failed', group: 'Other jobs', enabled: true },
  { key: 'job.succeeded', label: 'Job succeeded', group: 'Other jobs', enabled: true },
  { key: 'alert.fired', label: 'Alert triggered', group: 'Alerts', enabled: true },
  { key: 'audit.error', label: 'Audited action failed', group: 'Audit', enabled: true },
]

vi.mock('../api/client', () => ({
  ApiError: class extends Error {},
  api: vi.fn((path: string, opts?: RequestInit) => {
    if (path === '/entitlements') {
      return Promise.resolve({
        tier: 'pro', features: { 'notify.routing': routing, 'notify.channels': true },
        grace: null, clock_skew: false,
      })
    }
    if (path === '/notifications/types' && !opts?.method) {
      return Promise.resolve({ types: TYPES })
    }
    if (path === '/notifications/channels' && !opts?.method) {
      return Promise.resolve(channels)
    }
    if (path === '/notifications/public-url' && !opts?.method)
      return Promise.resolve({ url: '' })
    patched.push({ path, body: opts?.body ? JSON.parse(String(opts.body)) : null })
    if (path === '/notifications/types') return Promise.resolve({ types: TYPES })
    return Promise.resolve({})
  }),
}))

import { EventsMatrix } from '../components/EventsMatrix'

const wrap = () => {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(<QueryClientProvider client={qc}><EventsMatrix /></QueryClientProvider>)
}

describe('EventsMatrix', () => {
  beforeEach(() => { channels = []; routing = true; patched.length = 0 })

  it('works with no channels at all, master switches only', async () => {
    wrap()
    expect(await screen.findByRole('switch', { name: 'Job failed' })).toBeChecked()
    expect(screen.getByRole('switch', { name: 'Housekeeping succeeded' })).not.toBeChecked()
    expect(screen.queryByRole('columnheader', { name: 'SMTP' })).not.toBeInTheDocument()
    expect(screen.getByText(/only shown in the app/i)).toBeInTheDocument()
  })

  it('groups the rows under headings rather than listing them flat', async () => {
    wrap()
    for (const g of ['Apps', 'Backups', 'Housekeeping', 'Other jobs', 'Alerts', 'Audit'])
      expect(await screen.findByRole('rowheader', { name: g })).toBeInTheDocument()
  })

  it('turning a master switch off sends only that key', async () => {
    wrap()
    fireEvent.click(await screen.findByRole('switch', { name: 'Job failed' }))
    await waitFor(() => expect(patched).toHaveLength(1))
    expect(patched[0].body).toEqual({ enabled: { 'job.failed': false } })
  })

  it('shows a column per channel and ticks it from that channel events', async () => {
    channels = [{ id: 1, name: 'SMTP', kind: 'email', events: ['job.failed'],
                  enabled: true, last_notified_at: null }]
    wrap()
    expect(await screen.findByRole('checkbox',
      { name: 'Send Job failed to SMTP' })).toBeChecked()
    expect(screen.getByRole('checkbox',
      { name: 'Send Job succeeded to SMTP' })).not.toBeChecked()
  })

  it('renders a channel with an empty events list as fully ticked', async () => {
    // Empty means "every event" server-side. Showing it unticked would lie
    // about what that channel is currently receiving.
    channels = [{ id: 1, name: 'SMTP', kind: 'email', events: [],
                  enabled: true, last_notified_at: null }]
    wrap()
    expect(await screen.findByRole('checkbox',
      { name: 'Send Job failed to SMTP' })).toBeChecked()
    expect(screen.getByRole('checkbox',
      { name: 'Send Alert triggered to SMTP' })).toBeChecked()
  })

  it('materialises the concrete list when an all-events channel is first edited', async () => {
    channels = [{ id: 1, name: 'SMTP', kind: 'email', events: [],
                  enabled: true, last_notified_at: null }]
    wrap()
    fireEvent.click(await screen.findByRole('checkbox',
      { name: 'Send Job succeeded to SMTP' }))
    await waitFor(() => expect(patched).toHaveLength(1))
    expect(patched[0].path).toBe('/notifications/channels/1')
    expect(patched[0].body.events).not.toContain('job.succeeded')
    expect(patched[0].body.events).toContain('job.failed')
    expect(patched[0].body.events).toContain('alert.fired')
  })

  it('turning a master switch off disables that row channel boxes', async () => {
    channels = [{ id: 1, name: 'SMTP', kind: 'email', events: ['job.failed'],
                  enabled: true, last_notified_at: null }]
    wrap()
    expect(await screen.findByRole('checkbox',
      { name: 'Send Housekeeping succeeded to SMTP' })).toBeDisabled()
  })

  it('locks the channel columns without notify.routing and says why', async () => {
    routing = false
    channels = [{ id: 1, name: 'SMTP', kind: 'email', events: [],
                  enabled: true, last_notified_at: null }]
    wrap()
    expect(await screen.findByRole('switch', { name: 'Job failed' })).toBeEnabled()
    expect(screen.getByRole('checkbox',
      { name: 'Send Job failed to SMTP' })).toBeDisabled()
    expect(screen.getByText(/goes to every channel/i)).toBeInTheDocument()
  })
})

describe('EventsMatrix while loading', () => {
  it('shows skeleton rows rather than one line of text', async () => {
    // Nineteen rows arriving at once makes the section jump if the
    // placeholder is smaller than what replaces it.
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={qc}><EventsMatrix /></QueryClientProvider>)
    expect(screen.getByRole('status',
      { name: 'Loading notification types' })).toBeInTheDocument()
  })
})

describe('what the matrix claims', () => {
  it('does not show a row as delivered when its master switch is off', async () => {
    // Greyed-but-ticked said two contradictory things at once: "never" on the
    // left of the row and "yes, to Ops webhook" on the right.
    channels = [{ id: 1, name: 'SMTP', kind: 'email', events: [],
                  enabled: true, last_notified_at: null }]
    wrap()
    const off = await screen.findByRole('checkbox',
      { name: 'Send Housekeeping succeeded to SMTP' })
    expect(off).toBeDisabled()
    expect(off).not.toBeChecked()
    // A row that IS on still shows its delivery.
    expect(screen.getByRole('checkbox',
      { name: 'Send Job failed to SMTP' })).toBeChecked()
  })
})

describe('the installation address', () => {
  it('offers the address of the browser looking at the page', async () => {
    wrap()
    // Whoever is reading this reached the app at the right URL by definition,
    // so it is a suggestion. Not saved for them: on this screen the value can
    // be a LAN address nobody else resolves.
    expect(await screen.findByRole('button',
      { name: /Use http:\/\/localhost/ })).toBeInTheDocument()
    expect(patched).toHaveLength(0)
  })

  it('says plainly what happens when it is left empty', async () => {
    wrap()
    expect(await screen.findByText(/notifications carry no link/i)).toBeInTheDocument()
  })

  it('sends the address to its own endpoint, which trims it', async () => {
    wrap()
    const box = await screen.findByLabelText(/installation.s address/i)
    fireEvent.change(box, { target: { value: 'https://pve.example.com/' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(patched).toHaveLength(1))
    expect(patched[0].path).toBe('/notifications/public-url')
    expect(patched[0].body).toEqual({ url: 'https://pve.example.com/' })
  })
})
