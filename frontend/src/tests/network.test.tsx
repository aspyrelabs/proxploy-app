import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

const BRIDGES = {
  nodes: [{
    host_id: 1, host_name: 'host-01', node: 'pve1',
    interfaces: [
      { iface: 'vmbr0', type: 'bridge', method: 'static', address: '10.0.0.9',
        netmask: '255.255.255.0', cidr: '10.0.0.9/24', gateway: '10.0.0.1',
        bridge_ports: 'bond0', slaves: null, vlan_aware: true, vlan_id: null,
        vlan_raw_device: null, active: true, autostart: true, comments: 'management' },
      { iface: 'vmbr1', type: 'bridge', method: 'manual', address: null, netmask: null,
        cidr: null, gateway: null, bridge_ports: 'enp3s0', slaves: null,
        vlan_aware: false, vlan_id: null, vlan_raw_device: null, active: false,
        autostart: true, comments: null },
      { iface: 'bond0', type: 'bond', method: 'manual', address: null, netmask: null,
        cidr: null, gateway: null, bridge_ports: null, slaves: 'enp1s0 enp2s0',
        vlan_aware: false, vlan_id: null, vlan_raw_device: null, active: true,
        autostart: true, comments: null },
      // Every field PVE can legitimately omit, at once: pins that the Type,
      // Subnet and Ports columns fall back to "unknown", never a bare ", ".
      { iface: 'eth9', type: null, method: null, address: null, netmask: null,
        cidr: null, gateway: null, bridge_ports: null, slaves: null,
        vlan_aware: false, vlan_id: null, vlan_raw_device: null, active: false,
        autostart: false, comments: null },
    ],
  }],
  attachments: [
    { host_id: 1, node: 'pve1', guest_type: 'vm', guest_id: 9, name: 'win11', vmid: 201,
      iface: 'net0', raw: 'virtio=AA:BB:CC:DD:EE:FF,bridge=vmbr0,tag=10,firewall=1',
      model: 'virtio', macaddr: 'AA:BB:CC:DD:EE:FF', bridge: 'vmbr0', tag: 10,
      firewall: true, rate: null, mtu: null, link_down: false },
    { host_id: 1, node: 'pve1', guest_type: 'app', guest_id: 5, name: 'Immich', vmid: 150,
      iface: 'net0', raw: 'name=eth0,bridge=vmbr0,hwaddr=BC:24:11:00:11:22,ip=dhcp,type=veth',
      model: 'veth', macaddr: 'BC:24:11:00:11:22', bridge: 'vmbr0', tag: null,
      firewall: false, rate: null, mtu: null, link_down: false },
    // Bridge, VLAN and MAC all missing: pins the Guest attachments row falls
    // back to "unknown" too, not a bare ", ".
    { host_id: 1, node: 'pve1', guest_type: 'vm', guest_id: 11, name: 'ghost', vmid: 202,
      iface: 'net0', raw: 'bridge=,firewall=0',
      model: null, macaddr: null, bridge: null, tag: null,
      firewall: false, rate: null, mtu: null, link_down: false },
  ],
  errors: [] as { host_id: number; host_name: string; error: string }[],
}

const THROUGHPUT = {
  hours: 1, resolution: 'raw',
  hosts: [{
    host_id: 1, host_name: 'host-01',
    in: { resolution: 'raw', ts: [1, 2, 3], value: [1_000_000, 1_100_000, 1_250_000] },
    out: { resolution: 'raw', ts: [1, 2, 3], value: [200_000, 210_000, 250_000] },
  }],
}

const calls: { path: string; method: string; body: any }[] = []
let features: Record<string, boolean> = {
  'network.view': true, 'network.guest_config': true, 'network.host_config': true,
}

vi.mock('../api/client', () => {
  class ApiError extends Error {
    status: number; body: unknown
    constructor(status: number, body: unknown) {
      super(`API ${status}`); this.status = status; this.body = body
    }
  }
  return {
    ApiError,
    api: vi.fn((path: string, opts?: RequestInit) => {
      const method = (opts?.method ?? 'GET').toUpperCase()
      const body = opts?.body ? JSON.parse(String(opts.body)) : {}
      if (path === '/entitlements') {
        return Promise.resolve({ tier: 'builtin', features, grace: null, clock_skew: false })
      }
      if (method !== 'GET') calls.push({ path, method, body })
      if (path.startsWith('/network/bridges') && method === 'GET') {
        return Promise.resolve(BRIDGES)
      }
      if (path.startsWith('/network/throughput')) return Promise.resolve(THROUGHPUT)
      if (path.endsWith('/apply')) {
        if (!body.confirm) {
          // The real 409 is FLAT: main.py::problem_handler does
          // body.update(exc.detail), so error/confirm_phrase are top-level
          // and detail is a plain string, the same convention
          // lifecycle.test.tsx uses for self_target. Verified against the
          // live endpoint (task-14 review, finding 1).
          return Promise.reject(new ApiError(409, {
            type: 'about:blank', title: 'Conflict', status: 409,
            error: 'confirm_required', confirm_phrase: 'pve1',
            detail: "Applying the staged network config reloads pve1's interfaces.",
          }))
        }
        return Promise.resolve({ job: { id: 7, kind: 'network.apply', status: 'queued' } })
      }
      if (path.includes('/network/net')) {
        return Promise.resolve({ iface: 'net0', value: 'virtio=AA:BB:CC:DD:EE:FF,bridge=vmbr1,tag=10,firewall=1',
          upid: null, pending_reboot: false, detail: 'Applied immediately; no reboot needed.' })
      }
      return Promise.resolve(null)
    }),
  }
})

vi.mock('@tanstack/react-router', async (orig) => ({
  ...(await orig() as object),
  Link: ({ children }: { children?: unknown }) => <a>{children as never}</a>,
  useNavigate: () => () => {},
  useSearch: () => ({}),
}))

// uPlot needs a real canvas 2D context; jsdom hands it null and uPlot's _commit
// throws on the first paint with non-empty data. The chart is a leaf with
// nothing this page asserts on.
vi.mock('../components/charts/Sparkline', () => ({
  Sparkline: ({ values }: { values: (number | null)[] }) =>
    <div data-testid="sparkline">{values.length}</div>,
}))

import { NetworkPage } from '../routes/network'
import { NicForm } from '../components/NicForm'

const wrap = () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={qc}><NetworkPage /></QueryClientProvider>)
}

// Interface names legitimately appear in three places at once (bridges table,
// attachment map, host-config table), so every query is scoped to the table it
// is about. Each table carries an aria-label for exactly this reason.
const table = (name: string | RegExp) => within(screen.getByRole('table', { name }))

describe('NetworkPage reads', () => {
  it('renders the bridges table with subnet, zone and ports', async () => {
    calls.length = 0
    wrap()
    await screen.findByRole('table', { name: 'Bridges' })
    const t = table('Bridges')
    expect(t.getByText('vmbr0')).toBeInTheDocument()
    expect(t.getByText('10.0.0.9/24')).toBeInTheDocument()
    expect(t.getByText('VLAN-aware')).toBeInTheDocument()
    expect(t.getByText('bond0')).toBeInTheDocument()          // vmbr0's port
    // bonds and physical NICs are not bridges, doc 06's table is bridges only.
    // They belong to the host-config section, which asserts them below.
    expect(t.queryByText('enp1s0 enp2s0')).toBeNull()
  })

  it('does not show the degraded-host banner when errors is empty', async () => {
    calls.length = 0
    wrap()
    await screen.findByRole('table', { name: 'Bridges' })
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('shows a banner naming the host when list_bridges degrades one bad host', async () => {
    calls.length = 0
    BRIDGES.errors = [{ host_id: 2, host_name: 'host-02',
                        error: 'host host-02 has no API token credential' }]
    try {
      wrap()
      const banner = await screen.findByRole('alert')
      expect(banner).toHaveTextContent('1 host could not be read')
      expect(banner).toHaveTextContent('host-02')
      // the rest of the page still renders; this is a degrade, not a wipeout
      expect(await screen.findByRole('table', { name: 'Bridges' })).toBeInTheDocument()
    } finally {
      BRIDGES.errors = []
    }
  })

  it('renders the throughput figures in Mbps from the newest sample', async () => {
    calls.length = 0
    wrap()
    expect(await screen.findByText(/10\.0 Mbps/)).toBeInTheDocument()   // 1_250_000 B/s in
    expect(screen.getByText(/2\.0 Mbps/)).toBeInTheDocument()           // 250_000 B/s out
    expect(screen.getAllByTestId('sparkline')).toHaveLength(2)
  })

  it('lists the guest attachment map with each NIC bridge and MAC', async () => {
    calls.length = 0
    wrap()
    await screen.findByRole('table', { name: 'Guest attachments' })
    const t = table('Guest attachments')
    expect(t.getByText('win11')).toBeInTheDocument()
    expect(t.getByText('Immich')).toBeInTheDocument()
    expect(t.getByText('AA:BB:CC:DD:EE:FF')).toBeInTheDocument()
    expect(t.getByText('BC:24:11:00:11:22')).toBeInTheDocument()
  })

  it('falls back to "unknown" for a missing bridge, VLAN or MAC, never a bare comma', async () => {
    calls.length = 0
    wrap()
    await screen.findByRole('table', { name: 'Guest attachments' })
    const t = table('Guest attachments')
    expect(t.getAllByText('unknown').length).toBeGreaterThan(0)
    expect(t.queryByText(',')).toBeNull()
  })

  it('sends only the fields the NIC form edited, never the model or MAC', async () => {
    calls.length = 0
    wrap()
    await screen.findByRole('table', { name: 'Guest attachments' })
    fireEvent.click(table('Guest attachments').getAllByRole('button', { name: 'Edit' })[0])
    expect(await screen.findByText(/preserved exactly as Proxmox stores/i)).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Bridge'), { target: { value: 'vmbr1' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save NIC' }))
    await waitFor(() => expect(calls.length).toBe(1))
    expect(calls[0].path).toBe('/vms/9/network/net0')
    expect(calls[0].method).toBe('PUT')
    // the whole point: an untouched tag/firewall are absent (exclude_unset),
    // and model/macaddr are never in the body at all
    expect(calls[0].body).toEqual({ bridge: 'vmbr1' })
  })
})

describe('NetworkPage host config', () => {
  it('veils the host bridge editor when network.host_config is not entitled', async () => {
    calls.length = 0
    features = { 'network.view': true, 'network.guest_config': true }
    wrap()
    expect(await screen.findByText(/Host network editing is a Pro feature/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Unlock Pro/i })).toBeInTheDocument()
    features = { 'network.view': true, 'network.guest_config': true, 'network.host_config': true }
  })

  it('lists every interface type in the host section, not just bridges', async () => {
    calls.length = 0
    wrap()
    await screen.findByRole('table', { name: 'Interfaces on pve1' })
    const t = table('Interfaces on pve1')
    expect(t.getByText('enp1s0 enp2s0')).toBeInTheDocument()   // bond0's slaves
    expect(t.getByText('vmbr1')).toBeInTheDocument()
  })

  it('falls back to "unknown" for a missing Type, Subnet or Ports, never a bare comma', async () => {
    calls.length = 0
    wrap()
    await screen.findByRole('table', { name: 'Interfaces on pve1' })
    const t = table('Interfaces on pve1')
    expect(t.getByText('eth9')).toBeInTheDocument()
    expect(t.getAllByText('unknown').length).toBeGreaterThanOrEqual(3) // Type, Subnet, Ports
    expect(t.queryByText(',')).toBeNull()
  })

  it('routes the apply 409 through the typed confirmation and retries with the phrase', async () => {
    calls.length = 0
    wrap()
    fireEvent.click(await screen.findByRole('button', { name: /Apply staged config/i }))
    await waitFor(() => expect(calls.length).toBe(1))
    expect(calls[0].path).toBe('/network/1/pve1/apply')
    expect(calls[0].body).toEqual({})

    // the backend's own sentence, not a generic one
    expect(await screen.findByText(/reloads pve1/)).toBeInTheDocument()
    const input = screen.getByLabelText(/type/i)
    fireEvent.change(input, { target: { value: 'pve2' } })
    expect(screen.getByRole('button', { name: /^Confirm$/ })).toBeDisabled()
    fireEvent.change(input, { target: { value: 'pve1' } })
    fireEvent.click(screen.getByRole('button', { name: /^Confirm$/ }))
    await waitFor(() => expect(calls.length).toBe(2))
    expect(calls[1].body).toEqual({ confirm: 'pve1' })
  })
})

// One NIC row each way, shaped like GET /network/bridges' `attachments`.
const NIC_PLAIN = {
  host_id: 1, node: 'pve1', guest_type: 'app', guest_id: 1, name: 'Immich',
  vmid: 150, iface: 'net0', raw: 'virtio=AA:BB:CC:DD:EE:FF,bridge=vmbr0',
  model: 'virtio', mac: 'AA:BB:CC:DD:EE:FF', bridge: 'vmbr0', tag: null,
  firewall: false, rate: null, mtu: null, link_down: false,
}
const NIC_FIREWALLED = { ...NIC_PLAIN, firewall: true }
const NIC_CT_STATIC = { ...NIC_PLAIN, ip: '192.168.1.50/24', gw: '192.168.1.1' }
// A VM NIC: PVE keeps no address on it, so ip/gw are null whatever the guest
// has. `addresses` is whatever Proxmox knows, from the agent or from cloud-init.
const NIC_VM = {
  ...NIC_PLAIN, guest_type: 'vm', name: 'win11', vmid: 201,
  ip: null, gw: null, addresses: ['192.168.50.77'],
}
const NIC_VM_NO_ADDRESS = { ...NIC_VM, addresses: null }

const wrapNic = (ui: React.ReactNode) => render(
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    {ui}
  </QueryClientProvider>)

// The toggle removed on 2026-08-18 is back, and these tests now check that it
// is here rather than that it is absent. That removal assumed there would
// never be a way to permit traffic again once the flag turned filtering on
// for a guest; the firewall feature this repository has shipped since then is
// exactly that way, so a guest's rules do nothing unless BOTH this flag and
// its own `enable` option are set. Leaving the flag unmanageable would have
// shipped a rule table with no way to make it take effect.
describe('NicForm has its firewall toggle back', () => {
  it('offers a checkbox that starts from the NIC state and can be turned on', () => {
    wrapNic(<NicForm nic={NIC_PLAIN as never} bridges={['vmbr0', 'vmbr1']}
                     onClose={() => {}} />)
    const checkbox = screen.getByRole('checkbox', { name: /filter this nic/i }) as HTMLInputElement
    expect(checkbox.checked).toBe(false)
    fireEvent.click(checkbox)
    expect(checkbox.checked).toBe(true)
  })

  it('starts checked when Proxmox already has the flag on', () => {
    wrapNic(<NicForm nic={NIC_FIREWALLED as never} bridges={['vmbr0']}
                     onClose={() => {}} />)
    expect((screen.getByRole('checkbox', { name: /filter this nic/i }) as HTMLInputElement).checked)
      .toBe(true)
  })

  it('sends the firewall key when the flag changed, same as any other field', async () => {
    // A VM NIC, so the container-only ip/gw branch stays out of this patch:
    // the point here is the firewall key alone.
    calls.length = 0
    wrapNic(<NicForm nic={NIC_VM as never} bridges={['vmbr0']} onClose={() => {}} />)
    fireEvent.click(screen.getByRole('checkbox', { name: /filter this nic/i }))
    fireEvent.click(screen.getByRole('button', { name: 'Save NIC' }))
    await waitFor(() => expect(calls.length).toBe(1))
    expect(calls[0].body).toEqual({ firewall: true })
  })

  it('offers the link to the guest Firewall page and says the flag gates its rules', () => {
    wrapNic(<NicForm nic={NIC_PLAIN as never} bridges={['vmbr0']} onClose={() => {}} />)
    expect(screen.getByText(/firewall page/i)).toBeInTheDocument()
    expect(screen.getByText(/none of them apply to this nic/i)).toBeInTheDocument()
  })
})

describe('NicForm addressing', () => {
  it('offers a container an address mode, and a prefix hint with it', () => {
    wrapNic(<NicForm nic={NIC_CT_STATIC as never} bridges={['vmbr0']} onClose={() => {}} />)
    const mode = screen.getByLabelText(/IPv4 address/i) as HTMLSelectElement
    expect(mode.value).toBe('static')
    expect((screen.getByLabelText(/address and prefix/i) as HTMLInputElement).value)
      .toBe('192.168.1.50/24')
    expect((screen.getByLabelText(/gateway/i) as HTMLInputElement).value)
      .toBe('192.168.1.1')
    // Said in the form, not only in the error: PVE rejects a bare address, and
    // learning that from a round trip is a worse way to find out.
    expect(screen.getByText(/does not accept a bare address/i)).toBeInTheDocument()
  })

  it('hides the address fields behind the mode, so DHCP asks for nothing', () => {
    wrapNic(<NicForm nic={{ ...NIC_PLAIN, ip: 'dhcp' } as never} bridges={['vmbr0']}
                     onClose={() => {}} />)
    expect((screen.getByLabelText(/IPv4 address/i) as HTMLSelectElement).value).toBe('dhcp')
    expect(screen.queryByLabelText(/address and prefix/i)).toBeNull()
    expect(screen.queryByLabelText(/gateway/i)).toBeNull()
  })

  it('shows a VM address when Proxmox knows one, with no field to edit it', () => {
    // qm set --netN has no ip or gw at all, so there is nothing to edit here.
    wrapNic(<NicForm nic={NIC_VM as never} bridges={['vmbr0']} onClose={() => {}} />)
    expect(screen.queryByLabelText(/IPv4 address/i)).toBeNull()
    expect(screen.queryByLabelText(/address and prefix/i)).toBeNull()
    expect(screen.getByText(/192\.168\.192\.77/)).toBeInTheDocument()
  })

  it('shows nothing at all when Proxmox does not know the address', () => {
    // Not "unknown", not an explanation of why: a DHCP VM with no agent is the
    // ordinary case and has nothing to say about it.
    wrapNic(<NicForm nic={NIC_VM_NO_ADDRESS as never} bridges={['vmbr0']}
                     onClose={() => {}} />)
    expect(screen.queryByText(/^Address$/i)).toBeNull()
    expect(screen.queryByText(/guest agent/i)).toBeNull()
    expect(screen.queryByText(/cloud-init/i)).toBeNull()
  })
})
