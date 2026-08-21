import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

// The VM row's actions: a small button group plus a three-dots menu, the same
// shape the Apps table carries. Console is a BUTTON in that group, in the slot
// an app spends on Open; it is the only way into a VM at all, so it is not a
// menu item. There is no VM detail page any more, so this
// also covers what used to be tested through it: DELETE /vms/{id}, which is
// still typed-confirmation only and still refused on a running guest.
//
// Icon is stubbed so this file tests the BAR and the MENU, not the font
// subset: an unstubbed Icon renders the ligature name as text, which would
// land in every button's textContent (app-action-bar.test.tsx precedent).
vi.mock('../components/ui/icon', () => ({
  Icon: ({ name, size }: { name: string; size?: number }) => (
    <span data-icon={name} data-size={size ?? 18} />
  ),
}))

let features: Record<string, boolean> = {}
let capabilities: Record<string, boolean> = { lifecycle: true, console: true }
let deleteOutcome: 'ok' | 'guest_running' | 'self_target' = 'ok'
const calls: { path: string; method: string; body: any }[] = []

vi.mock('../api/client', async (importOriginal) => {
  return {
    ...(await importOriginal<typeof import('../api/client')>()),
    api: vi.fn((path: string, opts?: RequestInit) => {
      const method = (opts?.method ?? 'GET').toUpperCase()
      const body = opts?.body ? JSON.parse(String(opts.body)) : {}
      if (path === '/entitlements') {
        return Promise.resolve({ tier: 'builtin', grace: null, clock_skew: false, features })
      }
      if (path.startsWith('/hosts')) {
        return Promise.resolve([{ id: 1, name: 'pve-a', capabilities }])
      }
      if (path.startsWith('/jobs/')) return Promise.resolve([])
      if (method === 'DELETE' && path === '/vms/9') {
        calls.push({ path, method, body })
        if (deleteOutcome === 'guest_running') {
          return Promise.reject(new ApiError(409, {
            error: 'guest_running', detail: 'stop win11 before destroying it',
          }))
        }
        if (deleteOutcome === 'self_target') {
          return Promise.reject(new ApiError(409, {
            error: 'self_target', confirm_phrase: 'win11',
            detail: 'win11 is the guest Proxploy itself runs in.',
          }))
        }
        return Promise.resolve({ job: { id: 44, kind: 'vm.delete', status: 'queued' } })
      }
      return Promise.resolve(null)
    }),
  }
})

vi.mock('../lib/notify', () => ({ notify: { error: vi.fn(), success: vi.fn(), info: vi.fn(), warning: vi.fn() } }))
import { notify } from '../lib/notify'

const openConsole = vi.fn()
vi.mock('../lib/console-window', () => ({ openConsoleWindow: (...a: unknown[]) => openConsole(...a) }))

const navigate = vi.fn()
vi.mock('@tanstack/react-router', async (orig) => ({
  ...(await orig() as object),
  useNavigate: () => navigate,
}))

import { ApiError } from '../api/client'
import { VmActionBar } from '../components/VmActionBar'
import type { VmRow } from '../api/hooks'

const VM: VmRow = {
  id: 9, host_id: 1, host_name: 'pve-a', vmid: 201, name: 'win11',
  status: 'stopped', os_type: 'win11', cpu_cores: 2, cpu_pct: 3,
  mem_bytes: 2147483648, mem_total_bytes: 4294967296,
  disk_bytes: 53687091200, disk_total_bytes: 107374182400,
  net_in_bps: null, net_out_bps: null, uptime_s: 86400,
  guest_agent_ok: null,
}

const ALL_FEATURES = {
  'vms.lifecycle': true, 'vms.create': true, 'vms.clone': true, 'backups.run': true,
}

const wrap = (vm: VmRow) => {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(<QueryClientProvider client={qc}><VmActionBar vm={vm} /></QueryClientProvider>)
}

const labels = () =>
  within(screen.getByRole('group')).getAllByRole('button')
    .map((b) => b.getAttribute('aria-label') ?? b.textContent?.trim())

// Radix opens a menu on pointerdown, not click (AccountMenu/HostActionsMenu
// precedent).
const openMenu = () =>
  fireEvent.pointerDown(screen.getByRole('button', { name: /More actions for win11/i }),
                        { button: 0, ctrlKey: false })

const items = async () =>
  (await screen.findAllByRole('menuitem')).map((i) => i.textContent?.trim())

describe('VmActionBar', () => {
  beforeEach(() => {
    calls.length = 0
    deleteOutcome = 'ok'
    features = { ...ALL_FEATURES }
    capabilities = { lifecycle: true, console: true }
    navigate.mockClear()
    openConsole.mockClear()
    vi.mocked(notify.error).mockClear()
  })

  it('offers Stop, Restart, Console and Firewall beside a menu while the VM is running', () => {
    wrap({ ...VM, status: 'running' })
    expect(labels()).toEqual(['Stop', 'Restart', 'Console', 'Firewall', 'More actions for win11'])
  })

  it('offers Start instead of Stop while it is not running, Console and Firewall either way', () => {
    wrap(VM)
    expect(labels()).toEqual(['Start', 'Console', 'Firewall', 'More actions for win11'])
  })

  it('has no Open button: there is no web interface to point a tab at', () => {
    wrap({ ...VM, status: 'running' })
    expect(within(screen.getByRole('group')).queryByRole('button', { name: 'Open' })).toBeNull()
  })

  it('opens the guest firewall route from the Firewall button', () => {
    wrap(VM)
    fireEvent.click(screen.getByRole('button', { name: 'Firewall' }))
    expect(navigate).toHaveBeenCalledWith({ to: '/firewall/guest/vm/9' })
  })

  it('withholds the console when the host cannot serve one', async () => {
    capabilities = { lifecycle: true, console: false }
    wrap(VM)
    // waitFor, because nothing is withheld until /hosts has answered: the
    // "innocent until proven guilty" rule in api/app-gates.ts.
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Console' })).toBeDisabled())
  })

  it('names the VM on the dots trigger, which has no text of its own', () => {
    wrap(VM)
    const trigger = screen.getByRole('button', { name: 'More actions for win11' })
    expect(trigger.querySelector('[data-icon="more_vert"]')).not.toBeNull()
  })

  it('lists the menu actions in order, Delete last and destructive', async () => {
    wrap({ ...VM, status: 'running' })
    openMenu()
    expect(await items()).toEqual(['Shutdown', 'Pause', 'Options', 'Clone', 'Backup', 'Delete'])
    const all = screen.getAllByRole('menuitem')
    const del = all[all.length - 1]
    // The destructive vocabulary is the text-red token, and the border above
    // it is the separator keeping it off the end of the ordinary list.
    expect(del.className).toContain('text-red')
    expect(del.className).toContain('border-t')
  })

  it('offers neither Pause nor Shutdown once the VM is stopped', async () => {
    // Shutdown used to be listed here, which is what this assertion was
    // written around. It was wrong: the VM is already off, and the backend
    // answers "already stopped; nothing to do" (services/lifecycle.py), so
    // the item cost a job row and changed nothing. Every item that acts on a
    // running guest now branches on status the way Pause always did.
    wrap({ ...VM, status: 'stopped' })
    openMenu()
    expect(await items()).toEqual(['Options', 'Clone', 'Backup', 'Delete'])
  })

  it('offers Resume only while the VM is paused, in place of Pause', async () => {
    // "paused" is the exact string the row carries in that state: the poller
    // writes PVE's own status, and services/lifecycle.py settles a finished
    // pause to the same word. No Shutdown either: PVE refuses to shut down a
    // suspended guest, so the way out is Resume and then Shutdown.
    wrap({ ...VM, status: 'paused' })
    openMenu()
    expect(await items()).toEqual(['Resume', 'Options', 'Clone', 'Backup', 'Delete'])
  })

  it('does not repeat the row buttons inside the menu', async () => {
    // This is what lifecycle={false} buys: the same menu on the Hosts icon
    // grid DOES carry Start, Stop and Restart, because there are no buttons
    // beside it there (app-icon-grid.test.tsx).
    wrap({ ...VM, status: 'running' })
    openMenu()
    const listed = await items()
    for (const repeated of ['Start', 'Stop', 'Restart', 'Console']) {
      expect(listed).not.toContain(repeated)
    }
  })

  it('opens the console in a window of its own, never a route', () => {
    wrap(VM)
    fireEvent.click(screen.getByRole('button', { name: 'Console' }))
    expect(openConsole).toHaveBeenCalledWith('vm', 9)
    expect(navigate).not.toHaveBeenCalled()
  })

  it('withholds the plan-gated items once entitlements say the plan lacks them', async () => {
    features = { 'vms.lifecycle': true }
    wrap(VM)
    openMenu()
    const clone = await screen.findByRole('menuitem', { name: /clone/i })
    // waitFor because nothing is withheld until /entitlements has actually
    // answered: api/app-gates.ts's "innocent until proven guilty" rule.
    await waitFor(() => expect(clone).toHaveAttribute('data-disabled'))
    expect(screen.getByRole('menuitem', { name: /backup/i })).toHaveAttribute('data-disabled')
    expect(screen.getByRole('menuitem', { name: /delete/i })).toHaveAttribute('data-disabled')
  })
})

describe('VmActionsMenu destroy', () => {
  beforeEach(() => {
    calls.length = 0
    deleteOutcome = 'ok'
    features = { ...ALL_FEATURES }
    capabilities = { lifecycle: true, console: true }
    vi.mocked(notify.error).mockClear()
  })

  it('sends the typed VM name as confirm, then surfaces the job', async () => {
    wrap(VM)
    openMenu()
    fireEvent.click(await screen.findByRole('menuitem', { name: /delete/i }))
    expect(await screen.findByText(/deletes the VM and every disk/i)).toBeInTheDocument()

    const input = screen.getByLabelText(/type/i)
    expect(screen.getByRole('button', { name: /^confirm$/i })).toBeDisabled()
    fireEvent.change(input, { target: { value: 'win11' } })
    fireEvent.click(screen.getByRole('button', { name: /^confirm$/i }))

    await waitFor(() => expect(calls.length).toBe(1))
    expect(calls[0]).toMatchObject({ path: '/vms/9', method: 'DELETE', body: { confirm: 'win11' } })

    // The accessible name comes from the visible heading, so it names the
    // actual VM instead of a generic "Destroying VM".
    const progress = await screen.findByRole('dialog', { name: /destroying win11/i })
    expect(progress).toHaveAttribute('aria-modal', 'true')
    // Closing needs no navigation any more: the table is already the page.
    fireEvent.click(screen.getByRole('button', { name: 'Close' }))
    await waitFor(() => expect(screen.queryByRole('dialog', { name: /destroying win11/i })).toBeNull())
  })

  it('cannot destroy a running VM from the UI, the reason is visible on the disabled item', async () => {
    wrap({ ...VM, status: 'running' })
    openMenu()
    const del = await screen.findByRole('menuitem', { name: /delete/i })
    expect(del).toHaveAttribute('data-disabled')
    expect(del).toHaveAttribute('title', 'Stop win11 before destroying it')
    fireEvent.click(del)
    expect(screen.queryByLabelText(/type/i)).toBeNull()
    expect(calls.length).toBe(0)
  })

  it('shows the guest_running 409 detail verbatim rather than a generic failure, if state raced', async () => {
    // The disabled menu item is the primary guard; this covers the backend's
    // own refusal if the VM went running in the gap between opening the dialog
    // and confirming.
    deleteOutcome = 'guest_running'
    wrap(VM)
    openMenu()
    fireEvent.click(await screen.findByRole('menuitem', { name: /delete/i }))
    fireEvent.change(await screen.findByLabelText(/type/i), { target: { value: 'win11' } })
    fireEvent.click(screen.getByRole('button', { name: /^confirm$/i }))
    await waitFor(() => expect(calls.length).toBe(1))
    expect(notify.error).toHaveBeenCalledWith('stop win11 before destroying it')
  })

  it('states plainly that Proxploy will not destroy the guest it runs inside, on a self_target 409', async () => {
    deleteOutcome = 'self_target'
    wrap(VM)
    openMenu()
    fireEvent.click(await screen.findByRole('menuitem', { name: /delete/i }))
    fireEvent.change(await screen.findByLabelText(/type/i), { target: { value: 'win11' } })
    fireEvent.click(screen.getByRole('button', { name: /^confirm$/i }))
    await waitFor(() => expect(calls.length).toBe(1))
    expect(notify.error).toHaveBeenCalledWith('Proxploy will not destroy the guest it is running inside.')
  })
})
