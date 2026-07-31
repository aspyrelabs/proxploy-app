import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const calls: { path: string; method: string; body: any }[] = []
let features: Record<string, boolean> = { 'vms.create': true, 'vms.clone': true }
let cloneRejects = false

const VM = {
  id: 9, host_id: 1, host_name: 'host-01', vmid: 201, name: 'win11',
  status: 'running', os_type: 'win11', cpu_cores: 4, cpu_pct: 3,
  mem_bytes: 8589934592, disk_bytes: 68719476736, uptime_s: 3600, synced_at: null,
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
        if (path === '/entitlements') return Promise.resolve({ tier: 'builtin', features, grace: null })
        if (path === '/vms') return Promise.resolve([VM])
        if (path === '/hosts') return Promise.resolve([{ id: 1, name: 'host-01' }])
        if (path === '/cluster/nodes') return Promise.resolve([{ host_id: 1, node: 'pve1' }])
        if (path === '/storage') return Promise.resolve([
          { host_id: 1, node: 'pve1', storage: 'local', content: ['iso', 'vztmpl'] },
          { host_id: 1, node: 'pve1', storage: 'local-lvm', content: ['images', 'rootdir'] },
        ])
        if (path.startsWith('/storage/1/local/content')) {
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
      return Promise.resolve({ job: { id: 11, kind: 'vm.create', status: 'queued' } })
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
    features = { 'vms.create': true, 'vms.clone': true }
  })

  it('walks Target → OS → Resources → Network → Confirm and posts the assembled spec', async () => {
    wrap(<VmCreateWizard onClose={() => {}} />)

    // Every <select> renders empty and fills in when its query resolves, so each
    // pick waits for its own <option> — changing to a value with no matching
    // option is a silent no-op in jsdom.
    await screen.findByRole('option', { name: 'host-01' })
    fireEvent.change(screen.getByLabelText(/^host$/i), { target: { value: '1' } })
    await screen.findByRole('option', { name: 'pve1' })
    fireEvent.change(screen.getByLabelText(/^node$/i), { target: { value: 'pve1' } })
    fireEvent.change(screen.getByLabelText(/vm name/i), { target: { value: 'ubuntu-lab' } })
    next()

    fireEvent.change(await screen.findByLabelText(/iso storage/i), { target: { value: 'local' } })
    // The ISO list only loads once a datastore is picked; wait for the <option>
    // itself, or fireEvent.change sets a value that has no matching option.
    await screen.findByRole('option', { name: 'local:iso/ubuntu-24.04.iso' })
    fireEvent.change(screen.getByLabelText(/iso image/i),
      { target: { value: 'local:iso/ubuntu-24.04.iso' } })
    fireEvent.change(screen.getByLabelText(/os type/i), { target: { value: 'l26' } })
    next()

    fireEvent.change(screen.getByLabelText(/cores/i), { target: { value: '4' } })
    fireEvent.change(screen.getByLabelText(/memory/i), { target: { value: '4096' } })
    fireEvent.change(screen.getByLabelText(/disk size/i), { target: { value: '64' } })
    await screen.findByRole('option', { name: 'local-lvm' })
    fireEvent.change(screen.getByLabelText(/target storage/i), { target: { value: 'local-lvm' } })
    next()

    await screen.findByRole('option', { name: 'vmbr0' })
    fireEvent.change(screen.getByLabelText(/bridge/i), { target: { value: 'vmbr0' } })
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

  it('asks the storage content endpoint for ISOs only', async () => {
    const { api } = await import('../api/client')
    wrap(<VmCreateWizard onClose={() => {}} />)
    await screen.findByRole('option', { name: 'host-01' })
    fireEvent.change(screen.getByLabelText(/^host$/i), { target: { value: '1' } })
    await screen.findByRole('option', { name: 'pve1' })
    fireEvent.change(screen.getByLabelText(/^node$/i), { target: { value: 'pve1' } })
    fireEvent.change(screen.getByLabelText(/vm name/i), { target: { value: 'x' } })
    next()
    await screen.findByRole('option', { name: 'local' })
    fireEvent.change(screen.getByLabelText(/iso storage/i), { target: { value: 'local' } })
    await waitFor(() =>
      expect(api).toHaveBeenCalledWith('/storage/1/local/content?node=pve1&content=iso'))
  })
})

describe('VmsPage create/clone affordances', () => {
  beforeEach(() => {
    calls.length = 0
    cloneRejects = false
    features = { 'vms.create': true, 'vms.clone': true }
  })

  it('renders the New VM button and disables it with a tooltip when vms.create is off', async () => {
    features = { 'vms.create': false, 'vms.clone': true }
    wrap(<VmsPage />)
    const btn = await screen.findByRole('button', { name: 'New VM' })
    await waitFor(() => expect(btn).toBeDisabled())
    expect(btn).toHaveAttribute('title', 'Not included in your plan')
  })

  it('disables the Clone row action with a Pro tooltip when vms.clone is off', async () => {
    features = { 'vms.create': true, 'vms.clone': false }
    wrap(<VmsPage />)
    const btn = await screen.findByRole('button', { name: 'Clone' })
    await waitFor(() => expect(btn).toBeDisabled())
    expect(btn).toHaveAttribute('title', 'Cloning is a Pro feature')
  })
})

describe('CloneDialog', () => {
  beforeEach(() => { calls.length = 0; cloneRejects = false })

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
