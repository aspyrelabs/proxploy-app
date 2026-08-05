import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { Preflight } from '../api/migrate'

const HOSTS = [
  { id: 1, name: 'pve-a', status: 'connected' },
  { id: 2, name: 'pve-b', status: 'connected' },
  { id: 3, name: 'pve-c', status: 'offline' },
]

const APP = {
  id: 7, name: 'jellyfin', slug: 'jellyfin', host_id: 1, host_name: 'pve-a',
  node: 'pve-a', ctid: 150, category: null, catalog_slug: null,
  icon_initials: null, icon_colors: null, web_port: null, web_protocol: null,
  web_path: null, status: 'running', ip: null, cpu_pct: null,
  mem_bytes: null, mem_total_bytes: null, uptime_s: null,
  update_available: null, adopted: true,
}

// Backend shape mirrors backend/proxploy/services/migrate.py::preflight's
// return dict exactly (Global Constraints Preflight interface).
const PREFLIGHT_OK: Preflight = {
  strategy: 'transfer',
  source: { host_id: 1, host_name: 'pve-a', node: 'pve-a', ctid: 150 },
  target: { host_id: 2, host_name: 'pve-b', node: 'pve-b', ctid: 999 },
  shared_storage: null,
  transfer_bytes: 2_147_483_648, // 2 GiB
  estimate_basis: 'last_backup',
  est_downtime_s: 120,
  est_note: 'assumes ~80 MB/s sustained; measured downtime is reported by the job',
  capacity_ok: true,
  warnings: ['The guest gets a new IP/MAC address on the target host; update '
    + 'any DHCP reservations or static network config it relies on.'],
  blockers: [],
  downtime_statement: 'This is stop → backup → transfer → restore → start. '
    + 'Expect roughly 2 minute(s) of downtime.',
  self_target: false,
}

const PREFLIGHT_BLOCKED = {
  ...PREFLIGHT_OK,
  blockers: ['no dir-type backup storage on pve-b'],
}

let preflightResponse: typeof PREFLIGHT_OK = PREFLIGHT_OK
let migrateRequiresConfirm = false
let jobRow: Record<string, unknown> = {
  id: 55, kind: 'migrate.app', status: 'running',
  target_type: 'app', target_id: 7, params: null, result: null, error: null,
  progress_pct: 40, requested_by: 1, schedule_id: null,
  started_at: '2026-08-05T00:00:00', finished_at: null, created_at: '2026-08-05T00:00:00',
}

const calls: { path: string; method?: string; body?: any }[] = []

vi.mock('../api/client', () => {
  class ApiError extends Error {
    status: number; body: unknown
    constructor(status: number, body: unknown) { super(`API ${status}`); this.status = status; this.body = body }
  }
  return {
    ApiError,
    api: vi.fn((path: string, opts?: RequestInit) => {
      const method = opts?.method
      const body = opts?.body ? JSON.parse(String(opts.body)) : undefined
      calls.push({ path, method, body })
      if (path === '/hosts') return Promise.resolve(HOSTS)
      if (path === '/apps/7/migrate/preflight') return Promise.resolve(preflightResponse)
      if (path === '/apps/7/migrate') {
        if (migrateRequiresConfirm && body?.confirm !== 'jellyfin') {
          return Promise.reject(new ApiError(409, {
            error: 'self_target', confirm_phrase: 'jellyfin',
            detail: 'jellyfin is the container Proxploy itself runs in. '
              + 'Migrating it can strand its own recovery path. Type the name to confirm.',
          }))
        }
        return Promise.resolve({
          job: { id: 55, kind: 'migrate.app', status: 'queued' },
          preflight: preflightResponse,
        })
      }
      if (path === '/jobs/55') return Promise.resolve(jobRow)
      if (path === '/jobs/55/events') return Promise.resolve([])
      return Promise.reject(new Error(`unexpected path ${path}`))
    }),
  }
})

import { MigrateDialog } from '../components/MigrateDialog'

const wrap = (ui: React.ReactNode) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

const openWithTarget = async (hostId = '2') => {
  wrap(<MigrateDialog app={APP as any} onClose={() => {}} />)
  const select = await screen.findByLabelText('Target host')
  // Wait for the hosts query to populate the <option>s before selecting one.
  await screen.findByRole('option', { name: 'pve-b' })
  fireEvent.change(select, { target: { value: hostId } })
  await screen.findByText(/transfer size:/)
}

describe('MigrateDialog', () => {
  it('lists target hosts minus the app\'s own host', async () => {
    calls.length = 0
    preflightResponse = PREFLIGHT_OK
    migrateRequiresConfirm = false
    wrap(<MigrateDialog app={APP as any} onClose={() => {}} />)
    const select = await screen.findByLabelText('Target host') as HTMLSelectElement
    await screen.findByRole('option', { name: 'pve-b' })
    const labels = within(select).getAllByRole('option').map((o) => o.textContent)
    expect(labels).toEqual(['Select a host…', 'pve-b', 'pve-c (offline)'])
    expect(labels).not.toContain('pve-a')
  })

  it('runs the preflight and renders strategy, humanised size, downtime, and warnings', async () => {
    calls.length = 0
    preflightResponse = PREFLIGHT_OK
    migrateRequiresConfirm = false
    await openWithTarget()

    await waitFor(() => expect(calls.some((c) => c.path === '/apps/7/migrate/preflight')).toBe(true))
    expect(calls.find((c) => c.path === '/apps/7/migrate/preflight')?.body)
      .toEqual({ target_host_id: 2 })

    expect(screen.getByText('Backup, transfer, restore')).toBeInTheDocument()
    expect(screen.getByText(/2\.0 GiB/)).toBeInTheDocument()
    expect(screen.getByText(/from last backup/)).toBeInTheDocument()
    expect(screen.getByText(/est\. downtime: 120s/)).toBeInTheDocument()
    expect(screen.getByText(PREFLIGHT_OK.downtime_statement)).toBeInTheDocument()
    expect(screen.getByText(PREFLIGHT_OK.warnings[0])).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Migrate' })).toBeEnabled()
  })

  it('renders blockers as a red list and disables the confirm button', async () => {
    calls.length = 0
    preflightResponse = PREFLIGHT_BLOCKED
    migrateRequiresConfirm = false
    await openWithTarget()

    expect(screen.getByText('no dir-type backup storage on pve-b')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Migrate' })).toBeDisabled()
  })

  it('confirms, fires the migrate POST, and swaps to the JobLog view', async () => {
    calls.length = 0
    preflightResponse = PREFLIGHT_OK
    migrateRequiresConfirm = false
    jobRow = { ...jobRow, status: 'running', result: null }
    await openWithTarget()

    fireEvent.click(screen.getByRole('button', { name: 'Migrate' }))
    await waitFor(() => expect(calls.some((c) => c.path === '/apps/7/migrate')).toBe(true))
    expect(calls.find((c) => c.path === '/apps/7/migrate')?.body).toEqual({ target_host_id: 2 })

    // Swapped to the JobLog view: the target-host picker is gone, the
    // existing JobLog/TerminalPanel is showing instead.
    await waitFor(() => expect(screen.queryByLabelText('Target host')).toBeNull())
    expect(screen.getByText('No output yet.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Close' })).toBeInTheDocument()
    expect(screen.getByText(/actual downtime: not finished yet/)).toBeInTheDocument()
  })

  it('renders the typed-confirm dialog on a self_target 409', async () => {
    calls.length = 0
    preflightResponse = { ...PREFLIGHT_OK, self_target: true }
    migrateRequiresConfirm = true
    await openWithTarget()

    fireEvent.click(screen.getByRole('button', { name: 'Migrate' }))
    expect(await screen.findByText(/container Proxploy itself runs in/)).toBeInTheDocument()

    const input = screen.getByLabelText(/type/i)
    fireEvent.change(input, { target: { value: 'wrong' } })
    expect(screen.getByRole('button', { name: /confirm/i })).toBeDisabled()

    fireEvent.change(input, { target: { value: 'jellyfin' } })
    fireEvent.click(screen.getByRole('button', { name: /confirm/i }))

    await waitFor(() => {
      const migrateCalls = calls.filter((c) => c.path === '/apps/7/migrate')
      expect(migrateCalls.length).toBe(2)
      expect(migrateCalls[1].body).toEqual({ target_host_id: 2, confirm: 'jellyfin' })
    })
    await waitFor(() => expect(screen.queryByLabelText('Target host')).toBeNull())
  })

  it('shows the completed job\'s measured downtime next to the estimate', async () => {
    calls.length = 0
    preflightResponse = PREFLIGHT_OK
    migrateRequiresConfirm = false
    jobRow = { ...jobRow, status: 'succeeded', result: { downtime_s: 143.2 } }
    await openWithTarget()

    fireEvent.click(screen.getByRole('button', { name: 'Migrate' }))
    await waitFor(() => expect(screen.queryByLabelText('Target host')).toBeNull())

    expect(screen.getByText(/est\. downtime: 120s/)).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText(/actual downtime: 143\.2s \(measured\)/)).toBeInTheDocument())
  })
})
