import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

type Call = { path: string; method: string; body: any }
const calls: Call[] = []

let options: any = null
let putFails: { status: number; body: unknown } | null = null

vi.mock('../api/client', () => {
  class ApiError extends Error {
    status: number; body: unknown
    constructor(status: number, body: unknown) {
      super(`API ${status}`); this.status = status; this.body = body
    }
  }
  return {
    ApiError,
    apiErrorDetail: (_e: unknown, fallback: string) => fallback,
    api: vi.fn((path: string, opts?: RequestInit) => {
      const method = (opts?.method ?? 'GET').toUpperCase()
      const body = opts?.body ? JSON.parse(String(opts.body)) : {}
      if (method !== 'GET') calls.push({ path, method, body })
      if (method === 'PUT') {
        if (putFails) return Promise.reject(new ApiError(putFails.status, putFails.body))
        return Promise.resolve({
          changed: Object.keys(body), pending_reboot: true,
          pending: { kvm: 0 }, detail: null,
        })
      }
      if (path.endsWith('/options')) return Promise.resolve(options)
      return Promise.resolve(null)
    }),
  }
})

const toasts: { kind: string; msg: string }[] = []
vi.mock('../lib/notify', () => ({
  notify: {
    success: (msg: string) => toasts.push({ kind: 'success', msg }),
    error: (msg: string) => toasts.push({ kind: 'error', msg }),
    info: (msg: string) => toasts.push({ kind: 'info', msg }),
  },
}))

import { VmOptionsDialog } from '../components/VmOptionsDialog'

const VM = { id: 3, name: 'win-build', vmid: 100, host_id: 1 } as any

const payload = (over: Partial<any> = {}) => ({
  values: {
    name: 'win-build', onboot: 1, boot: 'order=scsi0;ide2', ostype: 'l26',
    agent: '1', hotplug: 'network,disk,usb',
  },
  pending: {},
  restricted: ['spice_enhancements', 'amd-sev', 'intel-tdx'],
  running: false,
  storages: ['local', 'local-lvm'],
  ...over,
})

const wrap = () => {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={qc}>
      <VmOptionsDialog vm={VM} onClose={() => {}} />
    </QueryClientProvider>,
  )
}

const ready = () => waitFor(() => expect(screen.getByLabelText('Name')).toBeInTheDocument())
const saveBtn = () => screen.getByRole('button', { name: 'Save changes' })

/** The dialog is a rail plus one pane, so a control only exists once its
 *  section is showing. Every test that reaches past General opens it first. */
const go = (section: string) =>
  fireEvent.click(screen.getByRole('button', { name: new RegExp(`^${section}`) }))

describe('VmOptionsDialog', () => {
  it('renders every group', async () => {
    calls.length = 0
    options = payload()
    wrap()
    await ready()
    for (const group of ['General', 'Guest OS', 'Boot', 'Advanced']) {
      expect(screen.getByText(group)).toBeInTheDocument()
    }
    // One control out of each group, so the groups are not empty headings.
    expect(screen.getByLabelText('Start at boot')).toBeInTheDocument()
    go('Guest OS'); expect(screen.getByLabelText('OS type')).toBeInTheDocument()
    go('Boot'); expect(screen.getByLabelText('Saved state storage')).toBeInTheDocument()
    go('Advanced'); expect(screen.getByLabelText('ACPI support')).toBeInTheDocument()
  })

  it('sends nothing for a switch nobody touched', async () => {
    calls.length = 0
    options = payload()
    wrap()
    await ready()
    expect(saveBtn()).toBeDisabled()
    go('Advanced')
    // A key Proxmox does not hold at all shows its default without becoming
    // a change: acpi is absent from values and reads on.
    expect(screen.getByLabelText('ACPI support')).toBeChecked()
    expect(saveBtn()).toBeDisabled()
    expect(calls).toEqual([])
  })

  it('deletes the setting when a switch goes back to its Proxmox default', async () => {
    calls.length = 0
    options = payload()
    wrap()
    await ready()
    // onboot is set to 1 and its default is off, so switching it off must
    // remove the line rather than write onboot=0 into the config.
    fireEvent.click(screen.getByLabelText('Start at boot'))
    expect(saveBtn()).toBeEnabled()
    fireEvent.click(saveBtn())
    await waitFor(() => expect(calls.length).toBe(1))
    expect(calls[0].method).toBe('PUT')
    expect(calls[0].path).toBe('/vms/3/options')
    expect(calls[0].body).toEqual({ onboot: null })
  })

  it('sends the value when a switch leaves its default', async () => {
    calls.length = 0
    options = payload()
    wrap()
    await ready()
    go('Advanced')
    fireEvent.click(screen.getByLabelText('Hardware virtualisation'))
    fireEvent.click(saveBtn())
    await waitFor(() => expect(calls.length).toBe(1))
    expect(calls[0].body).toEqual({ kvm: 0 })
  })

  it('marks the eight next-boot settings while the VM is running', async () => {
    calls.length = 0
    options = payload({ running: true })
    wrap()
    await ready()
    // One pane is mounted at a time, so the eight are collected by walking the
    // rail rather than read off a single render.
    const marked: string[] = []
    for (const sec of ['General', 'Guest OS', 'Boot', 'Advanced']) {
      go(sec)
      marked.push(...[...document.body.querySelectorAll('[data-next-boot]')]
        .map((el) => el.getAttribute('data-next-boot') as string))
    }
    expect(marked.sort()).toEqual(
      ['acpi', 'boot', 'freeze', 'kvm', 'localtime', 'ostype', 'smbios1', 'startdate'])
    expect(screen.getAllByText(/full shutdown and start/i).length).toBeGreaterThan(0)
  })

  it('shows nothing about the next boot while the VM is stopped', async () => {
    options = payload({ running: false })
    wrap()
    await ready()
    expect(document.body.querySelectorAll('[data-next-boot]').length).toBe(0)
  })

  it('shows what Proxmox is already holding for the next boot', async () => {
    options = payload({ pending: { kvm: 0, acpi: null } })
    wrap()
    await ready()
    go('Advanced')
    expect(document.body.querySelector('[data-pending="kvm"]')?.textContent)
      .toContain('Waiting for the next boot: 0')
    expect(document.body.querySelector('[data-pending="acpi"]')?.textContent)
      .toContain('back to the Proxmox default')
  })

  it('disables the three root-only settings and never submits them', async () => {
    calls.length = 0
    options = payload()
    wrap()
    await ready()
    go('Advanced')
    for (const label of ['SPICE enhancements', 'AMD SEV memory encryption',
                         'Intel TDX trusted domains']) {
      expect(screen.getByLabelText(label)).toBeDisabled()
    }
    expect(screen.getAllByText(/only lets the root user change this/i).length).toBe(3)
    expect(screen.getByText(/AMD EPYC host CPU/)).toBeInTheDocument()
    expect(screen.getByText(/Intel Xeon host CPU/)).toBeInTheDocument()
    // Clicking a disabled switch changes nothing, and a real edit alongside it
    // still submits only the real edit.
    fireEvent.click(screen.getByLabelText('SPICE enhancements'))
    expect(saveBtn()).toBeDisabled()
    go('General')
    fireEvent.click(screen.getByLabelText('Protection'))
    fireEvent.click(saveBtn())
    await waitFor(() => expect(calls.length).toBe(1))
    expect(calls[0].body).toEqual({ protection: 1 })
    for (const k of ['spice_enhancements', 'amd-sev', 'intel-tdx']) {
      expect(calls[0].body).not.toHaveProperty(k)
    }
  })

  it('warns when the boot order is empty', async () => {
    options = payload()
    wrap()
    await ready()
    go('Boot')
    fireEvent.click(screen.getByLabelText('Boot from scsi0'))
    go('Boot')
    fireEvent.click(screen.getByLabelText('Boot from ide2'))
    expect(screen.getByText(/will not boot/i)).toBeInTheDocument()
  })

  it('sends the boot order as an object of sub-keys', async () => {
    calls.length = 0
    options = payload()
    wrap()
    await ready()
    go('Boot')
    fireEvent.click(screen.getByLabelText('Boot from ide2'))
    fireEvent.click(saveBtn())
    await waitFor(() => expect(calls.length).toBe(1))
    expect(calls[0].body).toEqual({ boot: { order: 'scsi0' } })
  })

  it('surfaces the backend detail inline and as a toast', async () => {
    calls.length = 0
    toasts.length = 0
    options = payload()
    putFails = { status: 502, body: { detail: 'only root can set this option' } }
    wrap()
    await ready()
    fireEvent.click(screen.getByLabelText('Protection'))
    fireEvent.click(saveBtn())
    expect(await screen.findByText('only root can set this option')).toBeInTheDocument()
    expect(toasts).toContainEqual({ kind: 'error', msg: 'only root can set this option' })
    putFails = null
  })
})

describe('the Advanced section', () => {
  it('groups its rows under headings rather than one long list', async () => {
    // Seven unrelated rows in a column, from hot-plug to SMBIOS identity, with
    // nothing saying which belong together.
    options = payload()
    wrap()
    await ready()
    go('Advanced')
    expect(screen.getByText('Hardware')).toBeInTheDocument()
    expect(screen.getByText('Startup and identity')).toBeInTheDocument()
  })

  it('puts each row under the heading it belongs to', async () => {
    options = payload()
    wrap()
    await ready()
    go('Advanced')
    const hardware = screen.getByText('Hardware').closest('div')!
    const startup = screen.getByText('Startup and identity').closest('div')!
    expect(within(hardware).getByLabelText('ACPI support')).toBeInTheDocument()
    expect(within(hardware).getByLabelText('Hardware virtualisation')).toBeInTheDocument()
    expect(within(startup).getByLabelText('Freeze the CPU at startup')).toBeInTheDocument()
    expect(within(startup).getByLabelText('Clock start date')).toBeInTheDocument()
  })

  it('keeps the Proxmox-only group last and separate', async () => {
    options = payload()
    wrap()
    await ready()
    go('Advanced')
    const headings = screen.getAllByText(
      /^(Hardware|Startup and identity|Set by Proxmox only)$/)
      .map((el) => el.textContent)
    expect(headings[0]).toBe('Hardware')
    expect(headings[1]).toBe('Startup and identity')
  })

  it('stacks the hot-plug switches one per line', async () => {
    // Six of them wrapped three to a row, so which label went with which
    // switch depended on how wide the dialog happened to be.
    options = payload()
    wrap()
    await ready()
    go('Advanced')
    const first = screen.getByLabelText('Network cards')
    const list = first.closest('div[class*="flex-col"]') as HTMLElement | null
    expect(list).not.toBeNull()
    expect(within(list!).getAllByRole('switch')).toHaveLength(6)
  })
})
