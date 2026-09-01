import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const calls: { path: string; method: string; body: any }[] = []
let features: Record<string, boolean> = { 'vms.create': true, 'vms.clone': true }
let cloneRejects = false
let vmsListResult: 'ok' | 'empty' | 'error' | 'withPending' = 'ok'
// A two-node cluster shaped exactly as GET /storage really answers for one:
// its dedupe drops host_id from the key, so EVERY row comes back owned by
// whichever host polled first, and a SHARED datastore comes back once, under
// whichever node was seen first. Captured off the real `lab-cluster` cluster.
let clusterFixture = false
// Held open by the "shows the indeterminate ring" test below so it can
// observe the pending state before the clone POST resolves.
let cloneHeld = false
let releaseClone: ((v: unknown) => void) | null = null

const VM = {
  id: 9, host_id: 1, host_name: 'host-01', vmid: 201, name: 'win11',
  status: 'running', os_type: 'win11', cpu_cores: 4, cpu_pct: 3,
  mem_bytes: 8589934592, disk_bytes: 68719476736, uptime_s: 3600, guest_agent_ok: null,
}

const PENDING_VM = {
  id: 20, host_id: 1, host_name: 'host-01', vmid: 501, name: 'ubuntu-lab',
  status: 'stopped', os_type: 'l26', cpu_cores: 2, cpu_pct: 0,
  mem_bytes: 0, disk_bytes: 0, uptime_s: 0, guest_agent_ok: null,
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
      if (method === 'GET') {
        if (path === '/entitlements') return Promise.resolve({ tier: 'builtin', features, grace: null, clock_skew: false })
        if (path === '/vms') {
          if (vmsListResult === 'error') return Promise.reject(new ApiError(502, { detail: 'boom' }))
          if (vmsListResult === 'empty') return Promise.resolve([])
          if (vmsListResult === 'withPending') return Promise.resolve([VM, PENDING_VM])
          return Promise.resolve([VM])
        }
        if (path === '/hosts') {
          if (clusterFixture) return Promise.resolve([
            { id: 1, name: 'node1', cluster_name: 'lab-cluster' },
            { id: 2, name: 'node2', cluster_name: 'lab-cluster' },
          ])
          return Promise.resolve([{ id: 1, name: 'host-01' }, { id: 2, name: 'host-02' }])
        }
        if (path === '/cluster/nodes') {
          if (clusterFixture) return Promise.resolve([
            { host_id: 1, node: 'node1' }, { host_id: 2, node: 'node2' },
          ])
          return Promise.resolve([
            { host_id: 1, node: 'pve1' },
            { host_id: 2, node: 'pve2a' }, { host_id: 2, node: 'pve2b' },
          ])
        }
        if (path === '/storage') {
          if (clusterFixture) return Promise.resolve([
            // every row owned by host 1, because host 1 polled first
            { host_id: 1, node: 'node1', storage: 'local', content: ['iso', 'vztmpl'],
              shared: false, status: 'available', cluster_name: 'lab-cluster' },
            { host_id: 1, node: 'node1', storage: 'local-lvm', content: ['images', 'rootdir'],
              shared: false, status: 'available', cluster_name: 'lab-cluster' },
            { host_id: 1, node: 'node2', storage: 'local-lvm', content: ['images', 'rootdir'],
              shared: false, status: 'available', cluster_name: 'lab-cluster' },
            // shared, so ONE row, and under node2 here: which node wins is
            // whichever the poller saw first, so node1 asking for it must not
            // depend on having won that race.
            { host_id: 1, node: 'node2', storage: 'nfs-shared',
              content: ['iso', 'rootdir', 'vztmpl', 'backup', 'images'],
              shared: true, status: 'available', cluster_name: 'lab-cluster' },
          ])
          return Promise.resolve([
            { host_id: 1, node: 'pve1', storage: 'local', content: ['iso', 'vztmpl'],
              shared: false, status: 'available', cluster_name: null },
            { host_id: 1, node: 'pve1', storage: 'local-lvm', content: ['images', 'rootdir'],
              shared: false, status: 'available', cluster_name: null },
          ])
        }
        if (path.includes('/content?')) {
          return Promise.resolve([{ volid: 'local:iso/ubuntu-24.04.iso', size: 6000000000 }])
        }
        if (path.startsWith('/network/bridges')) {
          return Promise.resolve({ nodes: [{ host_id: 1, node: 'pve1', interfaces: [
            { iface: 'vmbr0', type: 'bridge' }, { iface: 'enp1s0', type: 'eth' },
          ] }], attachments: [] })
        }
        if (path.startsWith('/jobs/')) return Promise.resolve([])
        return Promise.resolve(null)
      }
      const body = opts?.body ? JSON.parse(String(opts.body)) : {}
      calls.push({ path, method, body })
      if (cloneRejects && path.endsWith('/clone')) {
        return Promise.reject(new ApiError(502, {
          detail: "proxmox: 400 Parameter verification failed. full: linked clone feature is not supported for drive 'scsi0'",
        }))
      }
      if (cloneHeld && path.endsWith('/clone')) {
        return new Promise((resolve) => { releaseClone = resolve })
      }
      return Promise.resolve({ job: { id: 11, kind: 'vm.create', status: 'queued' }, vmid: 501 })
    }),
  }
})

vi.mock('@tanstack/react-router', async (orig) => ({
  ...(await orig() as object),
  Link: ({ children }: { children?: unknown }) => <a>{children as never}</a>,
  useNavigate: () => () => {},
  useSearch: () => ({}),
}))

import { CloneDialog } from '../components/CloneDialog'
import { VmCreateWizard } from '../components/VmCreateWizard'
import { VmsPage } from '../routes/vms'

const wrap = (ui: React.ReactNode) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return { qc, ...render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>) }
}
const next = () => fireEvent.click(screen.getByRole('button', { name: 'Next' }))

describe('VmCreateWizard', () => {
  beforeEach(() => {
    calls.length = 0
    cloneRejects = false
    clusterFixture = false
    features = { 'vms.create': true, 'vms.clone': true }
  })

  // Reported from real use 2026-08-18: an attached NFS datastore did not show
  // up when deploying a VM, and on one node the target-storage select was
  // empty altogether. Both fall out of GET /storage's dedupe, which drops
  // host_id from its key and collapses a shared datastore to one row: the
  // wizard filtered `s.host_id === hostId && s.node === f.node`, which no
  // deduped row can satisfy for every host/node pair on a cluster.
  const reachStorageStep = async (hostValue: string, hostLabel: string) => {
    wrap(<VmCreateWizard onClose={() => {}} />)
    await screen.findByRole('option', { name: hostLabel })
    fireEvent.change(screen.getByLabelText(/^host$/i), { target: { value: hostValue } })
    fireEvent.change(screen.getByLabelText(/vm name/i), { target: { value: 'x' } })
    next()
    // nfs-shared on purpose: it is shared, so it is the one ISO datastore
    // offered to BOTH hosts, which is what lets one helper serve both cases.
    const isoStorageSelect = await screen.findByLabelText(/^iso storage$/i)
    await within(isoStorageSelect).findByRole('option', { name: 'nfs-shared' })
    fireEvent.change(isoStorageSelect, { target: { value: 'nfs-shared' } })
    await screen.findByRole('option', { name: 'local:iso/ubuntu-24.04.iso' })
    fireEvent.change(screen.getByLabelText(/^iso image$/i),
      { target: { value: 'local:iso/ubuntu-24.04.iso' } })
    next()
    next()
    return await screen.findByLabelText(/target storage/i)
  }

  it('offers a shared datastore on every node of the cluster', async () => {
    clusterFixture = true
    const select = await reachStorageStep('1', 'node1')
    await waitFor(() => expect(
      within(select).getByRole('option', { name: 'nfs-shared' })).toBeInTheDocument())
    expect(within(select).getByRole('option', { name: 'local-lvm' })).toBeInTheDocument()
  })

  it('offers pools to the host of a cluster that did not win the poll race', async () => {
    // Every row in the fixture is owned by host 1. Host 2 is the same cluster
    // and can serve all of them, so it must not see an empty list.
    clusterFixture = true
    const select = await reachStorageStep('2', 'node2')
    await waitFor(() => expect(
      within(select).getByRole('option', { name: 'nfs-shared' })).toBeInTheDocument())
    expect(within(select).getByRole('option', { name: 'local-lvm' })).toBeInTheDocument()
  })

  it('does not offer another node\'s local pool', async () => {
    // local-lvm exists on both nodes and is NOT shared, so node2's row must
    // not surface for node1 as a second, duplicate candidate.
    clusterFixture = true
    const select = await reachStorageStep('1', 'node1')
    await waitFor(() => expect(
      within(select).getByRole('option', { name: 'nfs-shared' })).toBeInTheDocument())
    expect(within(select).getAllByRole('option', { name: 'local-lvm' })).toHaveLength(1)
    // `local` carries no images content, so it is not a VM disk candidate
    expect(within(select).queryByRole('option', { name: 'local' })).toBeNull()
  })

  it('walks Target → OS → System → Disks → CPU & Memory → Network → Confirm and posts the assembled spec', async () => {
    wrap(<VmCreateWizard onClose={() => {}} />)

    // Every <select> renders empty and fills in when its query resolves, so each
    // pick waits for its own <option>, changing to a value with no matching
    // option is a silent no-op in jsdom.
    await screen.findByRole('option', { name: 'host-01' })
    fireEvent.change(screen.getByLabelText(/^host$/i), { target: { value: '1' } })
    // host-01 has exactly one cluster node, so PXP-87 pre-fills it and never
    // shows a node select: asking would just repeat the host question.
    expect(screen.queryByLabelText(/^node$/i)).not.toBeInTheDocument()
    fireEvent.change(screen.getByLabelText(/vm name/i), { target: { value: 'ubuntu-lab' } })
    next()

    fireEvent.change(await screen.findByLabelText(/^iso storage$/i), { target: { value: 'local' } })
    // The ISO list only loads once a datastore is picked; wait for the <option>
    // itself, or fireEvent.change sets a value that has no matching option.
    await screen.findByRole('option', { name: 'local:iso/ubuntu-24.04.iso' })
    fireEvent.change(screen.getByLabelText(/^iso image$/i),
      { target: { value: 'local:iso/ubuntu-24.04.iso' } })
    fireEvent.change(screen.getByLabelText(/os type/i), { target: { value: 'l26' } })
    next()

    next()

    fireEvent.change(screen.getByLabelText(/disk size/i), { target: { value: '64' } })
    await screen.findByRole('option', { name: 'local-lvm' })
    fireEvent.change(screen.getByLabelText(/target storage/i), { target: { value: 'local-lvm' } })
    next()

    fireEvent.change(screen.getByLabelText(/^cores$/i), { target: { value: '4' } })
    fireEvent.change(screen.getByLabelText(/^memory \(mb\)$/i), { target: { value: '4096' } })
    next()

    await screen.findByRole('option', { name: 'vmbr0' })
    fireEvent.change(screen.getByLabelText(/^bridge$/i), { target: { value: 'vmbr0' } })
    fireEvent.change(screen.getByLabelText(/vlan tag/i), { target: { value: '20' } })
    next()

    expect(screen.getByText('ubuntu-lab')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Create' }))

    await waitFor(() => expect(calls.length).toBe(1))
    expect(calls[0]).toMatchObject({
      path: '/vms', method: 'POST',
      body: {
        host_id: 1, node: 'pve1', name: 'ubuntu-lab', ostype: 'l26',
        iso: 'local:iso/ubuntu-24.04.iso', cores: 4, memory_mb: 4096,
        disk_gb: 64, storage: 'local-lvm', bridge: 'vmbr0', vlan_tag: 20,
      },
    })
    // InstallDialog pattern: the body swaps for the job log once the job lands.
    expect(await screen.findByText('No output yet.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Close' })).toBeInTheDocument()
  })

  it('builds a Windows 11 VM with EFI, TPM, agent and VirtIO drivers, and posts the exact spec', async () => {
    wrap(<VmCreateWizard onClose={() => {}} />)
    await screen.findByRole('option', { name: 'host-01' })
    fireEvent.change(screen.getByLabelText(/^host$/i), { target: { value: '1' } })
    fireEvent.change(screen.getByLabelText(/vm name/i), { target: { value: 'win11-vm' } })
    next()

    fireEvent.change(await screen.findByLabelText(/^iso storage$/i), { target: { value: 'local' } })
    await screen.findByRole('option', { name: 'local:iso/ubuntu-24.04.iso' })
    fireEvent.change(screen.getByLabelText(/^iso image$/i),
      { target: { value: 'local:iso/ubuntu-24.04.iso' } })
    fireEvent.change(screen.getByLabelText(/os type/i), { target: { value: 'win11' } })
    fireEvent.change(screen.getByLabelText(/virtio drivers storage/i), { target: { value: 'local' } })
    const virtioIsoSelect = await screen.findByLabelText(/virtio drivers iso/i)
    await within(virtioIsoSelect).findByRole('option', { name: 'local:iso/ubuntu-24.04.iso' })
    fireEvent.change(virtioIsoSelect, { target: { value: 'local:iso/ubuntu-24.04.iso' } })
    next()

    fireEvent.change(screen.getByLabelText(/^machine$/i), { target: { value: 'q35' } })
    fireEvent.change(screen.getByLabelText(/^bios$/i), { target: { value: 'ovmf' } })
    await screen.findByLabelText(/efi storage/i)
    await screen.findByRole('option', { name: 'local-lvm' })
    fireEvent.change(screen.getByLabelText(/efi storage/i), { target: { value: 'local-lvm' } })
    fireEvent.click(screen.getByLabelText(/add tpm/i))
    fireEvent.change(await screen.findByLabelText(/tpm storage/i), { target: { value: 'local-lvm' } })
    fireEvent.click(screen.getByLabelText(/qemu guest agent/i))
    next()

    await screen.findByRole('option', { name: 'local-lvm' })
    fireEvent.change(screen.getByLabelText(/target storage/i), { target: { value: 'local-lvm' } })
    next()

    next()

    await screen.findByRole('option', { name: 'vmbr0' })
    fireEvent.change(screen.getByLabelText(/^bridge$/i), { target: { value: 'vmbr0' } })
    next()

    fireEvent.click(screen.getByRole('button', { name: 'Create' }))
    await waitFor(() => expect(calls.length).toBe(1))
    expect(calls[0].body).toEqual({
      host_id: 1, node: 'pve1', name: 'win11-vm', vmid: null,
      pool: '', tags: '', onboot: false,
      startup_order: '', startup_up: '', startup_down: '', start: false,

      iso: 'local:iso/ubuntu-24.04.iso', virtio_iso: 'local:iso/ubuntu-24.04.iso', ostype: 'win11',

      machine: 'q35', bios: 'ovmf', vga: '', scsihw: 'virtio-scsi-single',
      efi_disk: true, efi_storage: 'local-lvm', efi_pre_enrolled_keys: true,
      tpm: true, tpm_storage: 'local-lvm', tpm_version: 'v2.0',
      agent: true, agent_type: 'virtio', agent_fstrim: false,

      disk_bus: 'scsi', disk_gb: 32, storage: 'local-lvm',
      disk_cache: '', disk_aio: '', disk_discard: false, disk_iothread: false, disk_ssd: false,
      disk_backup: true, disk_replicate: true,
      disk_mbps_rd: null, disk_mbps_wr: null, disk_iops_rd: null, disk_iops_wr: null,

      sockets: 1, cores: 2, cpu_type: '', cpu_flags: '',
      vcpus: null, cpulimit: null, cpuunits: null, numa: false,

      memory_mb: 2048, ballooning: true, balloon_mb: null, shares: null,

      net: true, bridge: 'vmbr0', vlan_tag: null, net_model: 'virtio', net_macaddr: '',
      net_mtu: null, net_queues: null, net_rate: null, net_firewall: false, net_link_down: false,
    })
  })

  it('sends net: false when the network device is turned off', async () => {
    wrap(<VmCreateWizard onClose={() => {}} />)
    await screen.findByRole('option', { name: 'host-01' })
    fireEvent.change(screen.getByLabelText(/^host$/i), { target: { value: '1' } })
    fireEvent.change(screen.getByLabelText(/vm name/i), { target: { value: 'no-net' } })
    next()

    fireEvent.change(await screen.findByLabelText(/^iso storage$/i), { target: { value: 'local' } })
    await screen.findByRole('option', { name: 'local:iso/ubuntu-24.04.iso' })
    fireEvent.change(screen.getByLabelText(/^iso image$/i),
      { target: { value: 'local:iso/ubuntu-24.04.iso' } })
    next()

    next()

    await screen.findByRole('option', { name: 'local-lvm' })
    fireEvent.change(screen.getByLabelText(/target storage/i), { target: { value: 'local-lvm' } })
    next()

    next()

    fireEvent.click(screen.getByLabelText(/no network device/i))
    expect(screen.queryByLabelText(/^bridge$/i)).not.toBeInTheDocument()
    next()

    fireEvent.click(screen.getByRole('button', { name: 'Create' }))
    await waitFor(() => expect(calls.length).toBe(1))
    expect(calls[0].body).toMatchObject({ net: false })
  })

  it('hides SSD emulation when the disk bus is virtio', async () => {
    wrap(<VmCreateWizard onClose={() => {}} />)
    await screen.findByRole('option', { name: 'host-01' })
    fireEvent.change(screen.getByLabelText(/^host$/i), { target: { value: '1' } })
    fireEvent.change(screen.getByLabelText(/vm name/i), { target: { value: 'x' } })
    next()

    fireEvent.change(await screen.findByLabelText(/^iso storage$/i), { target: { value: 'local' } })
    await screen.findByRole('option', { name: 'local:iso/ubuntu-24.04.iso' })
    fireEvent.change(screen.getByLabelText(/^iso image$/i),
      { target: { value: 'local:iso/ubuntu-24.04.iso' } })
    next()
    next()

    expect(screen.getByLabelText(/ssd emulation/i)).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText(/^bus$/i), { target: { value: 'virtio' } })
    expect(screen.queryByLabelText(/ssd emulation/i)).not.toBeInTheDocument()
  })

  it('still asks for the node when the host is a real cluster with more than one', async () => {
    // PXP-87: skipping the node question only holds when there is one answer.
    // host-02 has two nodes, so this is a genuine choice and stays on screen.
    wrap(<VmCreateWizard onClose={() => {}} />)
    await screen.findByRole('option', { name: 'host-02' })
    fireEvent.change(screen.getByLabelText(/^host$/i), { target: { value: '2' } })
    await screen.findByRole('option', { name: 'pve2a' })
    expect(screen.getByRole('option', { name: 'pve2b' })).toBeInTheDocument()
    // Nothing is pre-selected, and Next stays disabled, until a node is chosen.
    expect(screen.getByLabelText(/^node$/i)).toHaveValue('')
    fireEvent.change(screen.getByLabelText(/vm name/i), { target: { value: 'x' } })
    expect(screen.getByRole('button', { name: 'Next' })).toBeDisabled()
    fireEvent.change(screen.getByLabelText(/^node$/i), { target: { value: 'pve2b' } })
    expect(screen.getByRole('button', { name: 'Next' })).not.toBeDisabled()
  })

  it('asks the storage content endpoint for ISOs only', async () => {
    const { api } = await import('../api/client')
    wrap(<VmCreateWizard onClose={() => {}} />)
    await screen.findByRole('option', { name: 'host-01' })
    fireEvent.change(screen.getByLabelText(/^host$/i), { target: { value: '1' } })
    fireEvent.change(screen.getByLabelText(/vm name/i), { target: { value: 'x' } })
    next()
    const isoStorageSelect = await screen.findByLabelText(/^iso storage$/i)
    await within(isoStorageSelect).findByRole('option', { name: 'local' })
    fireEvent.change(isoStorageSelect, { target: { value: 'local' } })
    await waitFor(() =>
      expect(api).toHaveBeenCalledWith('/storage/1/local/content?node=pve1&content=iso'))
  })
})

// The rail replaced the old row of step chips (VmCreateWizard.tsx). It is the
// same StepRail component onboarding uses, so these only check the wiring
// this wizard is responsible for: one entry per step, the current one marked,
// and reachability following ok[step] rather than a separate source of truth.
describe('VmCreateWizard rail', () => {
  beforeEach(() => {
    calls.length = 0
    features = { 'vms.create': true, 'vms.clone': true }
  })

  it('renders one rail entry per step', async () => {
    wrap(<VmCreateWizard onClose={() => {}} />)
    await screen.findByRole('option', { name: 'host-01' })
    for (const label of ['Target', 'OS', 'System', 'Disks', 'CPU & Memory', 'Network', 'Confirm']) {
      expect(screen.getByRole('button', { name: new RegExp(`^${label}$`, 'i') })).toBeInTheDocument()
    }
  })

  it('marks the current step with aria-current="step" and no other step', async () => {
    wrap(<VmCreateWizard onClose={() => {}} />)
    await screen.findByRole('option', { name: 'host-01' })
    expect(screen.getByRole('button', { name: /^target$/i }).getAttribute('aria-current')).toBe('step')
    expect(screen.getByRole('button', { name: /^os$/i }).getAttribute('aria-current')).toBeNull()
  })

  it('does not navigate to a step that is not yet valid', async () => {
    wrap(<VmCreateWizard onClose={() => {}} />)
    await screen.findByRole('option', { name: 'host-01' })
    // Target is still empty, so ok[0] is false and OS is not reachable yet.
    fireEvent.click(screen.getByRole('button', { name: /^os$/i }))
    expect(screen.getByLabelText(/^host$/i)).toBeInTheDocument()
  })

  it('navigates back to a completed step, the same as Back', async () => {
    wrap(<VmCreateWizard onClose={() => {}} />)
    await screen.findByRole('option', { name: 'host-01' })
    fireEvent.change(screen.getByLabelText(/^host$/i), { target: { value: '1' } })
    fireEvent.change(screen.getByLabelText(/vm name/i), { target: { value: 'ubuntu-lab' } })
    next()

    await screen.findByLabelText(/iso storage/i)
    fireEvent.click(screen.getByRole('button', { name: /^target$/i }))
    expect(screen.getByLabelText(/^host$/i)).toBeInTheDocument()
  })
})

describe('VmsPage create/clone affordances', () => {
  beforeEach(() => {
    calls.length = 0
    cloneRejects = false
    features = { 'vms.create': true, 'vms.clone': true }
    vmsListResult = 'ok'
  })

  it('says the VMs could not be read rather than showing "no VMs discovered"', async () => {
    // The bug: a failed fetch renders identically to a genuinely empty fleet.
    vmsListResult = 'error'
    wrap(<VmsPage />)
    expect(await screen.findByText(/VMs not readable/i)).toBeInTheDocument()
    expect(screen.queryByText('No VMs discovered')).not.toBeInTheDocument()
  })

  it('shows the real empty-state copy when there genuinely are no VMs', async () => {
    vmsListResult = 'empty'
    wrap(<VmsPage />)
    expect(await screen.findByText('No VMs discovered')).toBeInTheDocument()
    expect(screen.queryByText(/VMs not readable/i)).not.toBeInTheDocument()
  })

  it('renders the New VM button and disables it with a tooltip when vms.create is off', async () => {
    features = { 'vms.create': false, 'vms.clone': true }
    wrap(<VmsPage />)
    const btn = await screen.findByRole('button', { name: 'New VM' })
    await waitFor(() => expect(btn).toBeDisabled())
    expect(btn).toHaveAttribute('title', 'Not included in your plan')
  })

  it('disables the Clone action with a Pro tooltip when vms.clone is off', async () => {
    features = { 'vms.create': true, 'vms.clone': false }
    wrap(<VmsPage />)
    // Clone is a menu item now, not a row button: the row carries Start/Stop,
    // Restart and Console, and everything else moved behind the dots. Radix
    // opens on pointerdown, not click.
    const trigger = await screen.findByRole('button', { name: /More actions for/i })
    fireEvent.pointerDown(trigger, { button: 0, ctrlKey: false })
    const item = await screen.findByRole('menuitem', { name: 'Clone' })
    await waitFor(() => expect(item).toHaveAttribute('data-disabled'))
    // "Not included in your plan", not the old row button's bespoke "Cloning
    // is a Pro feature". Clone now sits in a menu beside Backup and Delete,
    // which gate on the same shared wording (19 call sites use it against 4
    // one-off strings), and one menu explaining three denials three different
    // ways reads as three different problems.
    expect(item).toHaveAttribute('title', 'Not included in your plan')
  })
})

describe('VmsPage pending VM indicator', () => {
  beforeEach(() => {
    calls.length = 0
    cloneRejects = false
    features = { 'vms.create': true, 'vms.clone': true }
    vmsListResult = 'ok'
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  // Stops right before Close: the fast-poll and the 30s give-up timer are
  // both started by that click, so fake timers must already be active by
  // then, or those timers get scheduled against the real clock instead.
  const walkWizardToCreated = async () => {
    wrap(<VmsPage />)
    fireEvent.click(await screen.findByRole('button', { name: 'New VM' }))
    await screen.findByRole('option', { name: 'host-01' })
    fireEvent.change(screen.getByLabelText(/^host$/i), { target: { value: '1' } })
    fireEvent.change(screen.getByLabelText(/vm name/i), { target: { value: 'ubuntu-lab' } })
    next()

    fireEvent.change(await screen.findByLabelText(/^iso storage$/i), { target: { value: 'local' } })
    await screen.findByRole('option', { name: 'local:iso/ubuntu-24.04.iso' })
    fireEvent.change(screen.getByLabelText(/^iso image$/i),
      { target: { value: 'local:iso/ubuntu-24.04.iso' } })
    next()

    next()

    await screen.findByRole('option', { name: 'local-lvm' })
    fireEvent.change(screen.getByLabelText(/target storage/i), { target: { value: 'local-lvm' } })
    next()

    next()

    await screen.findByRole('option', { name: 'vmbr0' })
    fireEvent.change(screen.getByLabelText(/^bridge$/i), { target: { value: 'vmbr0' } })
    next()

    fireEvent.click(screen.getByRole('button', { name: 'Create' }))
    await screen.findByText('No output yet.')
  }

  it('shows a spinner for the new VM and clears it once the guest shows up in the list', async () => {
    await walkWizardToCreated()

    fireEvent.click(screen.getByRole('button', { name: 'Close' }))

    expect(screen.getByText(/Creating VM 501/)).toBeInTheDocument()
    expect(screen.getByRole('status', { name: 'Creating the VM' })).toBeInTheDocument()

    vmsListResult = 'withPending'
    await waitFor(() => expect(screen.queryByText(/Creating VM 501/)).toBeNull(), { timeout: 5000 })
    expect(screen.queryByRole('status', { name: 'Creating the VM' })).toBeNull()
  })

  it('gives up after 30 seconds and points at Activity instead of spinning forever', async () => {
    await walkWizardToCreated()

    vi.useFakeTimers()
    fireEvent.click(screen.getByRole('button', { name: 'Close' }))
    expect(screen.getByText(/Creating VM 501/)).toBeInTheDocument()

    await vi.advanceTimersByTimeAsync(30000)

    expect(screen.queryByText(/Creating VM 501/)).toBeNull()
    expect(screen.getByRole('alert')).toHaveTextContent(
      /VM 501 has not shown up yet\. Check Activity/)
  })
})

describe('CloneDialog', () => {
  beforeEach(() => { calls.length = 0; cloneRejects = false; cloneHeld = false; releaseClone = null })

  it('shows the indeterminate ring while the clone job is starting, no percentage anywhere', async () => {
    // Nothing in the clone path calls ctx.progress() (verified against
    // backend/proxploy/services/ for this task), so there is no honest
    // completion figure to show while the POST is in flight.
    cloneHeld = true
    wrap(<CloneDialog vm={VM as never} onClose={() => {}} />)
    fireEvent.change(await screen.findByLabelText(/new name/i), { target: { value: 'win11-copy' } })
    fireEvent.click(screen.getByRole('button', { name: 'Clone' }))

    const status = await screen.findByRole('status')
    expect(status).toHaveAttribute('aria-busy', 'true')
    expect(document.body.textContent).not.toMatch(/\d+ ?%/)

    releaseClone?.({ job: { id: 11, kind: 'vm.create', status: 'queued' } })
    expect(await screen.findByText('No output yet.')).toBeInTheDocument()
  })

  it('posts the new name, clone mode and target storage', async () => {
    wrap(<CloneDialog vm={VM as never} onClose={() => {}} />)
    fireEvent.change(await screen.findByLabelText(/new name/i), { target: { value: 'win11-copy' } })
    await screen.findByRole('option', { name: 'local-lvm' })
    fireEvent.change(screen.getByLabelText(/target storage/i), { target: { value: 'local-lvm' } })
    fireEvent.click(screen.getByRole('button', { name: 'Clone' }))
    await waitFor(() => expect(calls.length).toBe(1))
    expect(calls[0]).toMatchObject({
      path: '/vms/9/clone', method: 'POST',
      body: { name: 'win11-copy', full: true, storage: 'local-lvm' },
    })
    expect(await screen.findByText('No output yet.')).toBeInTheDocument()
  })

  it("renders PVE's linked-clone rejection verbatim instead of pre-validating template-ness", async () => {
    cloneRejects = true
    wrap(<CloneDialog vm={VM as never} onClose={() => {}} />)
    fireEvent.change(await screen.findByLabelText(/new name/i), { target: { value: 'win11-linked' } })
    fireEvent.click(screen.getByLabelText(/linked/i))
    fireEvent.click(screen.getByRole('button', { name: 'Clone' }))
    expect(await screen.findByText(/linked clone feature is not supported for drive 'scsi0'/))
      .toBeInTheDocument()
    expect(calls[0].body).toMatchObject({ full: false })
  })
})

describe('CloneDialog linked mode needs a template', () => {
  beforeEach(() => { calls.length = 0; cloneRejects = false; cloneHeld = false; releaseClone = null })

  it('disables the linked option for an ordinary guest', () => {
    // PVE accepts a linked clone only from a template, and its refusal never
    // says so: `500 Linked clone feature is not supported for '<volume>'
    // (scsi0)`, seen on real hardware (doc 12 check 18). The option used to be
    // offered on every VM and always failed.
    wrap(<CloneDialog vm={VM as never} onClose={() => {}} />)
    const linked = screen.getByLabelText(/linked clone/i)
    expect(linked).toBeDisabled()
    expect(screen.getByText(/needs a template source/i)).toBeInTheDocument()
  })

  it('offers the linked option for a template', () => {
    wrap(<CloneDialog vm={{ ...VM, template: true } as never} onClose={() => {}} />)
    const linked = screen.getByLabelText(/linked clone/i)
    expect(linked).not.toBeDisabled()
    expect(screen.queryByText(/needs a template source/i)).toBeNull()
  })
})
