import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

// AppRow.ip is the App row's own (effectively always-stale/never-populated,
// see api/apps.py::_app_out) cached field. It is deliberately DIFFERENT from
// the address the /network mock below returns, so a test that used the
// stored field by mistake would open the wrong host and fail loudly instead
// of passing by coincidence.
const APP = {
  id: 1, name: 'Immich', slug: 'immich', host_id: 1, host_name: 'pve-a',
  node: 'pve-a', ctid: 150, category: null, catalog_slug: 'immich',
  icon_initials: 'IM', icon_colors: null, web_port: null, web_protocol: 'http',
  web_path: '/', catalog_port: 8096 as number | null,
  status: 'running', ip: '10.0.0.5', cpu_pct: null, icon_url: null,
  mem_bytes: null, mem_total_bytes: null, uptime_s: null,
  disk_bytes: null, disk_total_bytes: null,
  net_in_bps: null, net_out_bps: null,
  update_available: null, adopted: true,
}

const calls: string[] = []

vi.mock('../api/client', () => ({
  api: vi.fn((path: string) => {
    calls.push(path)
    if (path === '/apps/1') return Promise.resolve({ ...APP })
    if (path === '/entitlements') {
      return Promise.resolve({
        tier: 'builtin', grace: null, clock_skew: false,
        features: { 'apps.open_ui': true, 'apps.lifecycle': true },
      })
    }
    // Live guest NIC read (services guest_nics, "no cache"): the address the
    // button must actually use.
    if (path === '/apps/1/network') {
      // `addresses`, not `ip`: `ip` is the config, and a container on DHCP has
      // the word `dhcp` there. `addresses` is what the guest actually holds.
      return Promise.resolve([{ ip: dhcpGuest ? 'dhcp' : '10.9.9.9/24',
                               addresses: ['10.9.9.9/24'] }])
    }
    return Promise.resolve(null)
  }),
  ApiError: class extends Error {},
}))

// A container whose CONFIG says dhcp but which holds a real lease, which is
// the case that used to report "could not determine this app's address".
let dhcpGuest = false

vi.mock('@tanstack/react-router', async (orig) => ({
  ...(await orig() as object),
  useNavigate: () => () => {},
  useSearch: () => ({}),
}))

// The app detail PAGE is gone; the Open button lives on the action bar every
// app row carries, using the same useOpenWebUi call the page used to make.
import { AppActionBar } from '../components/AppActionBar'
import type { AppRow } from '../api/hooks'

const withQuery = (ui: React.ReactNode) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

describe('AppActionBar Open', () => {
  beforeEach(() => { calls.length = 0 })

  it('shows the action when the catalog names a port, and opens the address it fetches live, not app.ip', async () => {
    APP.catalog_port = 8096
    const openSpy = vi.spyOn(window, 'open').mockImplementation(() => null)
    withQuery(<AppActionBar app={APP as AppRow} />)

    const btn = await screen.findByRole('button', { name: 'Open' })
    fireEvent.click(btn)

    await waitFor(() => expect(calls).toContain('/apps/1/network'))
    await waitFor(() => expect(openSpy).toHaveBeenCalledWith(
      'http://10.9.9.9:8096/', '_blank', 'noopener,noreferrer'))
    openSpy.mockRestore()
  })

  it('opens a DHCP container, whose config address is the word "dhcp"', async () => {
    // Reported from real use: the app card knew the port, and clicking Open
    // web UI said "Could not determine <app>'s address". The container was on
    // DHCP, so its PVE config carries `ip=dhcp`, and the button filtered that
    // out and gave up. The port was never the problem.
    dhcpGuest = true
    APP.catalog_port = 8000
    const openSpy = vi.spyOn(window, 'open').mockImplementation(() => null)
    withQuery(<AppActionBar app={APP as AppRow} />)

    fireEvent.click(await screen.findByRole('button', { name: 'Open' }))
    await waitFor(() => expect(openSpy).toHaveBeenCalledWith(
      'http://10.9.9.9:8000/', '_blank', 'noopener,noreferrer'))
    openSpy.mockRestore()
    dhcpGuest = false
  })

  it('hides the action entirely when the catalog names no port', async () => {
    APP.catalog_port = null
    withQuery(<AppActionBar app={APP as AppRow} />)

    // The overflow menu is always there, so its arrival is what proves the
    // bar has rendered rather than the assertion below passing on an empty
    // tree.
    await screen.findByRole('button', { name: /More actions/ })
    expect(screen.queryByRole('button', { name: 'Open' })).not.toBeInTheDocument()
  })
})
