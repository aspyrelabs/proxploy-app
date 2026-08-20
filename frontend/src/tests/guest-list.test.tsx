/** One list, two kinds of guest. */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

// Both guests below share host_id: 1, so one row here controls both.
let hostCapabilities: Record<string, boolean> | undefined =
  { monitoring: true, lifecycle: true, console: true, backup: true }

// Path-aware on purpose. LifecycleActions calls useEntitlements, whose `has`
// reads `q.data?.features[key]`: the optional chain guards `data`, NOT
// `features`. Resolving every call to [] would make `[].features[key]` throw,
// and the failure would look like a GuestList bug.
vi.mock('../api/client', () => ({
  api: vi.fn((path: string) => {
    if (path === '/entitlements') {
      return Promise.resolve({ tier: 'pro', features: { 'apps.lifecycle': true, 'vms.lifecycle': true } })
    }
    if (path === '/hosts') {
      return Promise.resolve([{ id: 1, capabilities: hostCapabilities }])
    }
    return Promise.resolve([])
  }),
  ApiError: class extends Error {},
}))

// GuestList uses only useNavigate; LifecycleActions imports no router at all.
vi.mock('@tanstack/react-router', () => ({ useNavigate: () => vi.fn() }))

import type { AppRow, VmRow } from '../api/hooks'
import { GuestList, toGuests } from '../components/GuestList'

const app = (over: Partial<AppRow> = {}): AppRow => ({
  id: 7, name: 'jellyfin', slug: 'jellyfin', host_id: 1, host_name: 'host-01',
  node: 'pve1', ctid: 104, category: null, catalog_slug: null,
  icon_initials: null, icon_colors: null, icon_url: null,
  web_port: null, web_protocol: null, catalog_port: null,
  web_path: null, status: 'running', ip: null, cpu_pct: 12,
  mem_bytes: 2161287168, mem_total_bytes: 4294967296,
  disk_bytes: null, disk_total_bytes: null, net_in_bps: null, net_out_bps: null,
  uptime_s: 100,
  update_available: null, adopted: false, ...over,
})

const vm = (over: Partial<VmRow> = {}): VmRow => ({
  id: 3, host_id: 1, host_name: 'host-01', vmid: 201, name: 'win11-lab',
  status: 'stopped', os_type: 'win11', cpu_cores: 4, cpu_pct: 0,
  mem_bytes: 1073741824, mem_total_bytes: 2147483648,
  disk_bytes: null, disk_total_bytes: null, net_in_bps: null, net_out_bps: null,
  uptime_s: null, guest_agent_ok: null,
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
  beforeEach(() => {
    hostCapabilities = { monitoring: true, lifecycle: true, console: true, backup: true }
  })

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

  // Both kinds now report used and allocated memory under the same two field
  // names, so both read "used / allocated" and the column means one thing.
  it('writes memory as used over allocated for both kinds', () => {
    wrap()
    expect(screen.getByText('2.0 GiB / 4.0 GiB')).toBeInTheDocument()
    expect(screen.getByText('1.0 GiB / 2.0 GiB')).toBeInTheDocument()
  })

  // A total is still nullable on either side, and a guest missing one shows
  // the figure it has rather than a denominator nobody measured.
  it('drops the denominator when the guest reports no allocation', () => {
    wrap(toGuests([], [vm({ mem_total_bytes: null })]))
    expect(screen.getByText('1.0 GiB')).toBeInTheDocument()
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

  // Bug: Console rendered enabled even when its host answered
  // capabilities.console: false, and opening it only failed once the
  // console ticket request reached the backend.
  it('disables Console when the host reports capabilities.console: false, and says why', async () => {
    hostCapabilities = { monitoring: true, lifecycle: true, console: false, backup: true }
    wrap()
    await waitFor(() => {
      for (const b of screen.getAllByRole('button', { name: 'Console' })) expect(b).toBeDisabled()
    })
    for (const b of screen.getAllByRole('button', { name: 'Console' })) {
      expect(b).toHaveAttribute('title', expect.stringContaining('console'))
    }
  })

  it('renders nothing but keeps its shape when there are no guests', () => {
    wrap([])
    expect(screen.queryByText('app')).not.toBeInTheDocument()
  })

  it('marks an app with an update available, and leaves the VM alone', () => {
    wrap(toGuests([app({ update_available: 'v2.4.0' })], [vm()]))
    // The mark is a bare dot now (UpdateDot), so its accessible name is the
    // only thing there is to assert on: no text is rendered at all.
    expect(screen.getAllByRole('img', { name: 'Update available' })).toHaveLength(1)
    expect(screen.queryByText('update')).not.toBeInTheDocument()
  })

  it('has real list semantics, not an undifferentiated run of buttons', () => {
    wrap()
    expect(screen.getByRole('list')).toBeInTheDocument()
    expect(screen.getAllByRole('listitem')).toHaveLength(2)
  })
})

describe('GuestList console button', () => {
  it('opens a console window instead of navigating to a route', async () => {
    // Regression: consoles moved out of in-page tabs and into windows of their
    // own, and those tab routes were deleted. This button still navigated to
    // /apps/$appId/console, so clicking Console on the Hosts page answered
    // "not found". Every ConsoleButton caller has to go through
    // lib/console-window.ts, not just the ones on the VM and app pages.
    const open = vi.fn()
    vi.stubGlobal('open', open)
    wrap(toGuests([app()], [vm()]))

    const buttons = await screen.findAllByRole('button', { name: /^console$/i })
    expect(buttons.length).toBe(2)          // one app, one VM
    fireEvent.click(buttons[0])
    fireEvent.click(buttons[1])

    expect(open.mock.calls.map((c) => c[0]).sort())
      .toEqual(['/shell/app/7', '/shell/vm/3'])
    vi.unstubAllGlobals()
  })
})
