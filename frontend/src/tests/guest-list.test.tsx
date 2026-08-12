/** One list, two kinds of guest. */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

// Path-aware on purpose. LifecycleActions calls useEntitlements, whose `has`
// reads `q.data?.features[key]`: the optional chain guards `data`, NOT
// `features`. Resolving every call to [] would make `[].features[key]` throw,
// and the failure would look like a GuestList bug.
vi.mock('../api/client', () => ({
  api: vi.fn((path: string) =>
    path === '/entitlements'
      ? Promise.resolve({ tier: 'pro', features: { 'apps.lifecycle': true, 'vms.lifecycle': true } })
      : Promise.resolve([])),
  ApiError: class extends Error {},
}))

// GuestList uses only useNavigate; LifecycleActions imports no router at all.
vi.mock('@tanstack/react-router', () => ({ useNavigate: () => vi.fn() }))

import type { AppRow, VmRow } from '../api/hooks'
import { GuestList, toGuests } from '../components/GuestList'

const app = (over: Partial<AppRow> = {}): AppRow => ({
  id: 7, name: 'jellyfin', slug: 'jellyfin', host_id: 1, host_name: 'host-01',
  node: 'pve1', ctid: 104, category: null, catalog_slug: null,
  icon_initials: null, icon_colors: null, web_port: null, web_protocol: null,
  web_path: null, status: 'running', ip: null, cpu_pct: 12,
  mem_bytes: 2161287168, mem_total_bytes: 4294967296, uptime_s: 100,
  update_available: null, adopted: false, ...over,
})

const vm = (over: Partial<VmRow> = {}): VmRow => ({
  id: 3, host_id: 1, host_name: 'host-01', vmid: 201, name: 'win11-lab',
  status: 'stopped', os_type: 'win11', cpu_cores: 4, cpu_pct: 0,
  mem_bytes: 2161287168, disk_bytes: null, uptime_s: null, synced_at: null,
  ...over,
})

const wrap = (guests = toGuests([app()], [vm()])) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <GuestList guests={guests} />
    </QueryClientProvider>)
}

describe('GuestList', () => {
  it('puts apps and VMs in one list, each saying which it is', () => {
    wrap()
    expect(screen.getByText('jellyfin')).toBeInTheDocument()
    expect(screen.getByText('win11-lab')).toBeInTheDocument()
    expect(screen.getByText('app')).toBeInTheDocument()
    expect(screen.getByText('vm')).toBeInTheDocument()
  })

  it('names the guest by the id its operator types, not its row id', () => {
    wrap()
    expect(screen.getByText('CT 104')).toBeInTheDocument()
    expect(screen.getByText('VM 201')).toBeInTheDocument()
  })

  // VmRow has mem_bytes but no mem_total_bytes. Rendering a VM's memory as a
  // percentage would mean inventing the denominator, so the app gets "x / y"
  // and the VM gets the figure it actually has.
  it('shows a total only for the side that knows one', () => {
    wrap()
    expect(screen.getByText('2.0 GiB / 4.0 GiB')).toBeInTheDocument()
    expect(screen.getByText('2.0 GiB')).toBeInTheDocument()
  })

  it('gives both kinds their lifecycle controls', async () => {
    wrap()
    // Exact names, not /start/i: LifecycleActions renders Stop AND Restart
    // for a running guest, and /start/i matches "Restart" too, which would
    // make getByRole throw on multiple matches rather than assert anything.
    // The running app supplies Stop, the stopped VM supplies Start.
    expect(await screen.findByRole('button', { name: 'Stop' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Restart' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Start' })).toBeInTheDocument()
  })

  it('offers a console for both kinds', () => {
    wrap()
    expect(screen.getAllByRole('button', { name: 'Console' })).toHaveLength(2)
  })

  it('renders nothing but keeps its shape when there are no guests', () => {
    wrap([])
    expect(screen.queryByText('app')).not.toBeInTheDocument()
  })

  it('badges an app with an update available, and leaves the VM alone', () => {
    wrap(toGuests([app({ update_available: 'v2.4.0' })], [vm()]))
    expect(screen.getByText('update')).toBeInTheDocument()
    expect(screen.getAllByText('update')).toHaveLength(1)
  })

  it('has real list semantics, not an undifferentiated run of buttons', () => {
    wrap()
    expect(screen.getByRole('list')).toBeInTheDocument()
    expect(screen.getAllByRole('listitem')).toHaveLength(2)
  })
})
