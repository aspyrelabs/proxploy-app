import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const calls: { path: string; method: string; body: any }[] = []
let features: Record<string, boolean> = { 'vms.create': true, 'vms.clone': true }
let cloneRejects = false
let vmsListResult: 'ok' | 'empty' | 'error' = 'ok'
// Held open by the "shows the indeterminate ring" test below so it can
// observe the pending state before the clone POST resolves.
let cloneHeld = false
let releaseClone: ((v: unknown) => void) | null = null

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
        if (path === '/entitlements') return Promise.resolve({ tier: 'builtin', features, grace: null, clock_skew: false })
        if (path === '/vms') {
          if (vmsListResult === 'error') return Promise.reject(new ApiError(502, { detail: 'boom' }))
          return Promise.resolve(vmsListResult === 'empty' ? [] : [VM])
        }
        if (path === '/hosts') return Promise.resolve([{ id: 1, name: 'host-01' }, { id: 2, name: 'host-02' }])
        if (path === '/cluster/nodes') return Promise.resolve([
          { host_id: 1, node: 'pve1' },
          { host_id: 2, node: 'pve2a' }, { host_id: 2, node: 'pve2b' },
        ])
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
      if (cloneHeld && path.endsWith('/clone')) {
        return new Promise((resolve) => { releaseClone = resolve })
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
    // pick waits for its own <option>, changing to a value with no matching
    // option is a silent no-op in jsdom.
    await screen.findByRole('option', { name: 'host-01' })
    fireEvent.change(screen.getByLabelText(/^host$/i), { target: { value: '1' } })
    // host-01 has exactly one cluster node, so PXP-87 pre-fills it and never
    // shows a node select: asking would just repeat the host question.
    expect(screen.queryByLabelText(/^node$/i)).not.toBeInTheDocument()
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
    await screen.findByRole('option', { name: 'local' })
    fireEvent.change(screen.getByLabelText(/iso storage/i), { target: { value: 'local' } })
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
    for (const label of ['Target', 'OS', 'Resources', 'Network', 'Confirm']) {
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

  it('disables the Clone row action with a Pro tooltip when vms.clone is off', async () => {
    features = { 'vms.create': true, 'vms.clone': false }
    wrap(<VmsPage />)
    const btn = await screen.findByRole('button', { name: 'Clone' })
    await waitFor(() => expect(btn).toBeDisabled())
    expect(btn).toHaveAttribute('title', 'Cloning is a Pro feature')
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
