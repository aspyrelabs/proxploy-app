/** The host page Hardware tab: every section the node will answer, and an
 *  honest note for each one it will not. */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

let payload: unknown = null
let fails = false

vi.mock('../api/client', () => ({
  api: vi.fn(() => (fails ? Promise.reject(new Error('502')) : Promise.resolve(payload))),
  ApiError: class extends Error {},
}))

import { HardwareTab } from '../components/HardwareTab'

/** Shapes captured from a real PVE 9.2.10 node, normalised by the backend. */
const full = () => ({
  disks: [{ devpath: '/dev/nvme0n1', model: 'WD Green SN350 2TB',
            serial: '22303K800007', size: 2000398934016, type: 'nvme',
            health: 'PASSED', wearout: 99, used: 'LVM', osd_id: null }],
  network: [
    { iface: 'vmbr0', type: 'bridge', method: 'static', method6: 'manual',
      families: ['inet'], active: true, exists: true, autostart: true,
      cidr: '192.168.50.20/24', gateway: '192.168.50.1',
      bridge_ports: 'enp1s0', altnames: [] },
    { iface: 'enp1s0', type: 'eth', method: 'manual', method6: 'manual',
      families: ['inet'], active: false, exists: true, autostart: false,
      cidr: null, gateway: null, bridge_ports: null, altnames: [] },
  ],
  pci: [
    { id: '0000:00:02.0', class_id: '0x030000', class_name: 'Display controller',
      device_id: '0xa780', device_name: 'Raptor Lake-S GT1 [UHD Graphics 770]',
      vendor_id: '0x8086', vendor_name: 'Intel Corporation',
      subsystem_vendor_name: 'Intel Corporation', iommu_group: 2 },
    { id: '0000:00:1f.3', class_id: '0x040300', class_name: 'Multimedia controller',
      device_id: '0x7a50', device_name: 'Raptor Lake HD Audio Controller',
      vendor_id: '0x8086', vendor_name: 'Intel Corporation',
      subsystem_vendor_name: 'Intel Corporation', iommu_group: 13 },
  ],
  services: [
    { name: 'pveproxy', desc: 'PVE API Proxy Server', state: 'running',
      active_state: 'active', unit_state: 'enabled' },
    { name: 'pvedaemon', desc: 'PVE API Daemon', state: 'running',
      active_state: 'active', unit_state: 'enabled' },
    { name: 'corosync', desc: 'Corosync Cluster Engine', state: 'stopped',
      active_state: 'inactive', unit_state: 'enabled' },
  ],
  subscription: { status: 'notfound', message: 'There is no subscription key',
                  level: null, server_id: '8FE4C0DEADBEEF' },
  dns: { servers: ['192.168.50.249'], search: 'lab.local' },
  time: { timezone: 'Asia/Kolkata', localtime: 1754900000, utc: 1754880200 },
  unreadable: {} as Record<string, { error: string; detail: string }>,
})

const wrap = () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <HardwareTab hostId={1} node="pve1" />
    </QueryClientProvider>)
}

/** The card whose heading matches, so a per-section assertion cannot be
 *  satisfied by text that happens to live in a neighbouring section. */
const section = (heading: RegExp) =>
  screen.getByRole('heading', { name: heading }).closest('section') as HTMLElement

describe('HardwareTab', () => {
  beforeEach(() => {
    fails = false
    payload = full()
  })

  it('still lists the disks with health and wearout', async () => {
    wrap()
    expect(await screen.findByText('/dev/nvme0n1')).toBeInTheDocument()
    expect(screen.getByText('WD Green SN350 2TB')).toBeInTheDocument()
    expect(screen.getByText(/99% left/)).toBeInTheDocument()
  })

  it('lists the network interfaces with their addressing', async () => {
    wrap()
    await screen.findByText('/dev/nvme0n1')
    const s = within(section(/network interfaces/i))
    expect(s.getByText('vmbr0')).toBeInTheDocument()
    expect(s.getByText('192.168.50.20/24')).toBeInTheDocument()
    // twice: once as its own row, once as the port vmbr0 is bridged onto
    expect(s.getAllByText('enp1s0')).toHaveLength(2)
  })

  it('groups PCI devices by class rather than dumping one flat list', async () => {
    wrap()
    await screen.findByText('/dev/nvme0n1')
    const s = within(section(/pci devices/i))
    expect(s.getByText('Display controller')).toBeInTheDocument()
    expect(s.getByText('Multimedia controller')).toBeInTheDocument()
    expect(s.getByText(/UHD Graphics 770/)).toBeInTheDocument()
    expect(s.getByText('0000:00:02.0')).toBeInTheDocument()
  })

  it('shows only the services that are not running, until asked for all', async () => {
    // Twenty-three rows of "running" is not information. The one that is
    // stopped is, so that is what the tab leads with.
    wrap()
    await screen.findByText('/dev/nvme0n1')
    const s = within(section(/services/i))
    expect(s.getByText('corosync')).toBeInTheDocument()
    expect(s.queryByText('pveproxy')).not.toBeInTheDocument()
    // and the count of the ones being hidden is stated, not silently dropped
    expect(s.getByText(/2 .*running/i)).toBeInTheDocument()

    fireEvent.click(s.getByRole('button', { name: /show all/i }))
    expect(s.getByText('pveproxy')).toBeInTheDocument()
    expect(s.getByText('pvedaemon')).toBeInTheDocument()
  })

  it('says every service is running when none of them is not', async () => {
    const p = full()
    p.services = p.services.filter((s) => s.state === 'running')
    payload = p
    wrap()
    await screen.findByText('/dev/nvme0n1')
    const s = within(section(/services/i))
    expect(s.getByText(/all 2 services are running/i)).toBeInTheDocument()
  })

  it('words a missing subscription key neutrally, never as a problem', async () => {
    wrap()
    await screen.findByText('/dev/nvme0n1')
    const s = within(section(/node facts/i))
    expect(s.getByText('No subscription key')).toBeInTheDocument()
    // the nag PVE itself shows is not this page's job to repeat
    expect(s.queryByText(/error|invalid|warning|expired/i)).not.toBeInTheDocument()
  })

  it('shows the resolvers, search domain and timezone', async () => {
    wrap()
    await screen.findByText('/dev/nvme0n1')
    const s = within(section(/node facts/i))
    expect(s.getByText('192.168.50.249')).toBeInTheDocument()
    expect(s.getByText('lab.local')).toBeInTheDocument()
    expect(s.getByText('Asia/Kolkata')).toBeInTheDocument()
  })

  it('explains a section the node would not answer, and keeps the rest', async () => {
    const p = full()
    p.pci = null as never
    p.unreadable = { pci: { error: 'auth', detail: '403 forbidden' } }
    payload = p
    wrap()
    expect(await screen.findByText('/dev/nvme0n1')).toBeInTheDocument()
    const s = within(section(/pci devices/i))
    expect(s.getByText(/would not report/i)).toBeInTheDocument()
    expect(s.getByText(/403 forbidden/)).toBeInTheDocument()
    // an unreadable section must not read as an empty one
    expect(s.queryByText(/reports no/i)).not.toBeInTheDocument()
    // the sections that DID answer are untouched
    expect(within(section(/services/i)).getByText('corosync')).toBeInTheDocument()
  })

  it('tells an empty section apart from an unreadable one', async () => {
    const p = full()
    p.pci = []
    payload = p
    wrap()
    await screen.findByText('/dev/nvme0n1')
    const s = within(section(/pci devices/i))
    expect(s.getByText(/reports no PCI devices/i)).toBeInTheDocument()
    expect(s.queryByText(/would not report/i)).not.toBeInTheDocument()
  })

  it('says the node is unreachable when the whole read fails', async () => {
    fails = true
    wrap()
    expect(await screen.findByText(/would not report its hardware/i)).toBeInTheDocument()
  })
})
