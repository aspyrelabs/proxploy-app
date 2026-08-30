import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

// Icon is stubbed so this file tests the GRID, not the font subset;
// icon.test.tsx pins Icon's own contract (host-actions-menu.test.tsx
// precedent).
vi.mock('../components/ui/icon', () => ({
  Icon: ({ name, size }: { name: string; size?: number }) => (
    <span data-icon={name} data-size={size ?? 18} />
  ),
}))

const ALL_FEATURES = {
  'apps.lifecycle': true, 'apps.open_ui': true, 'apps.reconfigure': true,
  'migrate.cross_host': true, 'backups.run': true, 'apps.uninstall': true,
}
let features: Record<string, boolean> = { ...ALL_FEATURES }
let capabilities: Record<string, boolean> = { lifecycle: true, console: true }

vi.mock('../api/client', () => ({
  api: vi.fn((path: string) => {
    if (path === '/entitlements') {
      return Promise.resolve({ tier: 'builtin', grace: null, clock_skew: false, features })
    }
    if (path.startsWith('/hosts')) {
      return Promise.resolve([{ id: 1, name: 'pve-a', capabilities }])
    }
    return Promise.resolve(null)
  }),
  ApiError: class extends Error {},
}))

const openConsole = vi.fn()
vi.mock('../lib/console-window', () => ({
  openConsoleWindow: (...a: unknown[]) => openConsole(...a),
  openLogsWindow: vi.fn(),
}))

const navigate = vi.fn()
vi.mock('@tanstack/react-router', async (orig) => ({
  ...(await orig() as object),
  useNavigate: () => navigate,
}))

import { AppIconGrid, VmIconGrid } from '../components/IconGrid'
import type { AppRow, VmRow } from '../api/hooks'

const APP: AppRow = {
  id: 1, name: 'Immich', slug: 'immich', host_id: 1, host_name: 'pve-a',
  node: 'pve-a', ctid: 150, category: null, catalog_slug: 'immich',
  icon_initials: 'IM', icon_colors: null, icon_url: null,
  web_port: null, web_protocol: 'http', web_path: '/', installed_url: null,
  catalog_port: 8096,
  status: 'running', ip: '10.0.0.5', cpu_pct: 12,
  mem_bytes: 1, mem_total_bytes: 2, uptime_s: 86400,
  update_available: null, adopted: false,
  disk_bytes: 1, disk_total_bytes: 2, net_in_bps: 1, net_out_bps: 1,
}

const VM: VmRow = {
  id: 1, host_id: 1, host_name: 'pve-a', vmid: 201, name: 'win11-lab',
  status: 'running', os_type: 'win11', cpu_cores: 4, cpu_pct: 3,
  mem_bytes: 1, mem_total_bytes: 2, disk_bytes: null, disk_total_bytes: 2,
  net_in_bps: 1, net_out_bps: 1, uptime_s: 500, guest_agent_ok: null,
  node: 'pve-a',
}

const mount = (ui: React.ReactNode) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

const wrap = (apps: AppRow[]) => mount(<AppIconGrid apps={apps} />)
const wrapVms = (vms: VmRow[]) => mount(<VmIconGrid vms={vms} />)

// Radix opens a menu on pointerdown, not click (AccountMenu/HostActionsMenu
// precedent).
const openMenu = (trigger: HTMLElement) =>
  fireEvent.pointerDown(trigger, { button: 0, ctrlKey: false })

describe('AppIconGrid', () => {
  beforeEach(() => {
    navigate.mockClear()
    openConsole.mockClear()
    features = { ...ALL_FEATURES }
    capabilities = { lifecycle: true, console: true }
  })

  it('shows the state beside the name, never drawn on the logo', () => {
    wrap([APP])
    // Exact case: statusLabel('running') is 'Running', not any other casing.
    const status = screen.getByText('Running')
    expect(status).toBeInTheDocument()
    // The class that makes every status word read in the same case on the
    // grid: statusLabel returns 'Running' but 'stopped' verbatim, so without
    // this class the grid would mix cases. jsdom does not apply Tailwind's
    // compiled CSS, so this checks the class is present rather than the
    // rendered glyphs, which is the part that would actually regress.
    expect(status).toHaveClass('uppercase')
    expect(screen.getByTestId('app-icon-1').querySelector('[data-icon]')).toBeNull()
  })

  it('keeps paused distinguishable from stopped, in the same case', () => {
    wrap([{ ...APP, status: 'paused' }, { ...APP, id: 2, name: 'Plex', status: 'stopped' }])
    // statusLabel has no entries for paused or stopped, so these come back
    // lowercase verbatim: the exact text pins that, and the uppercase class
    // is what makes them read the same case as 'Running' on screen.
    const paused = screen.getByText('paused')
    const stopped = screen.getByText('stopped')
    expect(paused).toBeInTheDocument()
    expect(stopped).toBeInTheDocument()
    expect(paused).toHaveClass('uppercase')
    expect(stopped).toHaveClass('uppercase')
  })

  it('leaves room for a long app name rather than cutting it to a few characters', () => {
    // jsdom does no layout, so this pins the RULE that guarantees the room:
    // a column floor, not a fixed column count. A count let each column be
    // whatever was left over, which is how names got cut. The floor is sized
    // for the 32px tile, its gap, and roughly 20 characters at 13px.
    const { container } = wrap([{ ...APP, name: 'a-twenty-char-name!!' }])
    const grid = container.querySelector('div[class*="grid-cols"]') as HTMLElement
    expect(grid.className).toContain('auto-fill')
    // 10rem, measured: at the 570px a half page column really gets, this fits
    // 3 columns of 171px where 13rem fitted 2 of 256px, and no name on the
    // reference fleet truncates at that width.
    expect(grid.className).toMatch(/minmax\(10rem,\s*1fr\)/)
    expect(grid.className).not.toMatch(/grid-cols-\d/)
    // Past the floor it still ellipses rather than blowing the column open,
    // and the full name stays reachable on hover.
    const name = screen.getByRole('button', { name: 'a-twenty-char-name!!' })
    expect(name.className).toContain('truncate')
    expect(name).toHaveAttribute('title', 'a-twenty-char-name!!')
  })

  it('opens the app detail from the name, which is a row on the Apps table now', () => {
    wrap([APP])
    fireEvent.click(screen.getByRole('button', { name: 'Immich' }))
    expect(navigate).toHaveBeenCalledWith(expect.objectContaining({
      to: '/apps', search: expect.objectContaining({ open: 1 }),
    }))
  })

  it('keeps the lifecycle actions here, since the tile menu is the only way to act', async () => {
    wrap([APP])
    openMenu(screen.getByRole('button', { name: /actions for Immich/i }))
    const items = await screen.findAllByRole('menuitem')
    // trim(): each item renders `<Icon /> {label}`, so its textContent
    // carries a leading space the stubbed Icon leaves behind.
    // Running, so Stop and Restart show and Start does not: the same action
    // set LifecycleActions already picks from status. The Apps table row
    // passes lifecycle={false} instead, because it carries those as buttons.
    expect(items.map((i) => i.textContent?.trim()))
      .toEqual(['Stop', 'Restart', 'Console', 'Open',
                'Logs', 'Firewall', 'Reconfigure', 'Migrate', 'Backup', 'Delete'])
  })

  it('offers Start instead of Stop when the app is stopped', async () => {
    wrap([{ ...APP, status: 'stopped' }])
    openMenu(screen.getByRole('button', { name: /actions for Immich/i }))
    const items = await screen.findAllByRole('menuitem')
    expect(items.map((i) => i.textContent?.trim()))
      .toEqual(['Start', 'Console', 'Open',
                'Logs', 'Firewall', 'Reconfigure', 'Migrate', 'Backup', 'Delete'])
  })

  it('puts Delete last, below a separator and styled as destructive', async () => {
    wrap([APP])
    openMenu(screen.getByRole('button', { name: /actions for Immich/i }))
    const items = await screen.findAllByRole('menuitem')
    const del = items[items.length - 1]
    expect(del.textContent?.trim()).toBe('Delete')
    // The destructive vocabulary is the text-red token (HostActionsMenu's
    // Power off item), and the border above it is the separator that keeps a
    // slip from Restart landing here.
    expect(del.className).toContain('text-red')
    expect(del.className).toContain('border-t')
  })

  it('opens the uninstall confirmation from Delete, rather than deleting on the spot', async () => {
    wrap([APP])
    openMenu(screen.getByRole('button', { name: /actions for Immich/i }))
    fireEvent.click(await screen.findByRole('menuitem', { name: /delete/i }))
    expect(await screen.findByRole('alertdialog')).toHaveTextContent(/uninstall/i)
    expect(screen.getByRole('button', { name: /destroy container/i })).toBeInTheDocument()
  })

  it('hides Open when the app has no catalog port to point at', async () => {
    wrap([{ ...APP, catalog_port: null }])
    openMenu(screen.getByRole('button', { name: /actions for Immich/i }))
    const items = await screen.findAllByRole('menuitem')
    expect(items.map((i) => i.textContent?.trim())).not.toContain('Open')
  })

  it('withholds lifecycle actions on a host with no lifecycle token', async () => {
    capabilities = { lifecycle: false, console: true }
    wrap([APP])
    openMenu(screen.getByRole('button', { name: /actions for Immich/i }))
    const stop = await screen.findByRole('menuitem', { name: 'Stop' })
    await waitFor(() => expect(stop).toHaveAttribute('data-disabled'))
  })

  it('groups by the node the app runs on, not the host it was read through', () => {
    // Both of these came in through host pve-a, which is one API endpoint into
    // a cluster; they are running on two different machines. Grouping on
    // host_name would file both under one heading and answer the wrong
    // question.
    wrap([APP, { ...APP, id: 2, name: 'Plex', node: 'pve-c' }])
    expect(screen.getByRole('heading', { name: 'pve-a' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'pve-c' })).toBeInTheDocument()
    expect(screen.getAllByText(/1 app$/)).toHaveLength(2)
  })

  it('names the host under a node heading that is not already the host', () => {
    // pve-c is read through host pve-a, so the section says which endpoint
    // answers for it. The pve-a section does not repeat its own name.
    wrap([APP, { ...APP, id: 2, name: 'Plex', node: 'pve-c' }])
    expect(screen.getByText('on pve-a · 1 app')).toBeInTheDocument()
  })

  it('does not repeat the machine when the host is the node\'s fully qualified name', () => {
    // The real shape on the reference cluster: PVE reports the node as `node1`
    // while the host is registered as `node1.lab.local`. An exact string
    // compare called those two different machines and every heading read
    // "node1 · on node1.lab.local · 4 apps", naming one box twice.
    wrap([{ ...APP, node: 'node1', host_name: 'node1.lab.local' }])
    expect(screen.getByText('node1')).toBeInTheDocument()
    expect(screen.getByText('1 app')).toBeInTheDocument()
    expect(screen.queryByText(/lab\.local/)).toBeNull()
  })

  it('falls back to the host name for an app whose node is not reported', () => {
    // '' is what a row carries before the poller has filled the node in. The
    // host name is all it can say about where it lives, and on a standalone
    // machine that is the same name, so it joins that section rather than
    // drawing a second one with the same heading.
    wrap([{ ...APP, id: 2, name: 'Plex', node: '' }, APP])
    expect(screen.getAllByRole('heading', { name: 'pve-a' })).toHaveLength(1)
    expect(screen.getByText('2 apps')).toBeInTheDocument()
  })

  it('keeps an app with neither a node nor a host, in a section of its own', () => {
    const { container } = wrap([{ ...APP, id: 2, name: 'Plex', node: '', host_name: '' }, APP])
    expect(screen.getByTestId('app-icon-2')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /node not reported/i })).toBeInTheDocument()
    // Last, after every section that knows where it is.
    const text = container.textContent!
    expect(text.indexOf('Immich')).toBeLessThan(text.indexOf('Plex'))
  })

  it('shows every app under the cap, not the first eight', () => {
    // The Hosts page used to slice(0, 8), so a missing app could equally be
    // stopped, gone, or simply the ninth.
    const apps = Array.from({ length: 12 }, (_, i) => (
      { ...APP, id: i + 1, name: `app-${String(i + 1).padStart(2, '0')}` }
    ))
    wrap(apps)
    expect(screen.getAllByRole('button', { name: /^Actions for app-/ })).toHaveLength(12)
    expect(screen.getByText('12 apps')).toBeInTheDocument()
  })

  it('caps one node at 50 apps and says so rather than trimming quietly', () => {
    // 50 is a total for the section, not a per-node allowance. The count is
    // the only thing on the page that can admit the list is short, so the
    // assertion is on the words as much as on the tile count.
    const apps = Array.from({ length: 64 }, (_, i) => (
      { ...APP, id: i + 1, name: `app-${String(i + 1).padStart(2, '0')}` }
    ))
    wrap(apps)
    expect(screen.getAllByRole('button', { name: /^Actions for app-/ })).toHaveLength(50)
    expect(screen.getByText('50 of 64 apps')).toBeInTheDocument()
  })

  it('deals the 50 across nodes rather than letting the first node take them all', () => {
    // A slice off the front would give pve1 all 50 and draw pve2 empty, which
    // is indistinguishable from a node with nothing installed on it. Two nodes
    // with 40 apiece get 25 apiece.
    const apps = [
      ...Array.from({ length: 40 }, (_, i) => (
        { ...APP, id: i + 1, name: `one-${String(i + 1).padStart(2, '0')}`, node: 'pve1' }
      )),
      ...Array.from({ length: 40 }, (_, i) => (
        { ...APP, id: 100 + i, name: `two-${String(i + 1).padStart(2, '0')}`, node: 'pve2' }
      )),
    ]
    wrap(apps)
    expect(screen.getAllByRole('button', { name: /^Actions for one-/ })).toHaveLength(25)
    expect(screen.getAllByRole('button', { name: /^Actions for two-/ })).toHaveLength(25)
    // The line is "on host-01 · 25 of 40 apps": these fixtures name the node
    // and the host differently, so the count is matched, not the whole line.
    expect(screen.getAllByText(/25 of 40 apps/)).toHaveLength(2)
  })

  it('spends the remainder on the node that still has rows, not on empty seats', () => {
    // pve1 has 10 and cannot use half of 50, so pve2 takes the other 40 rather
    // than the section stopping short at 20.
    const apps = [
      ...Array.from({ length: 10 }, (_, i) => (
        { ...APP, id: i + 1, name: `one-${String(i + 1).padStart(2, '0')}`, node: 'pve1' }
      )),
      ...Array.from({ length: 60 }, (_, i) => (
        { ...APP, id: 100 + i, name: `two-${String(i + 1).padStart(2, '0')}`, node: 'pve2' }
      )),
    ]
    wrap(apps)
    expect(screen.getAllByRole('button', { name: /^Actions for one-/ })).toHaveLength(10)
    expect(screen.getAllByRole('button', { name: /^Actions for two-/ })).toHaveLength(40)
    expect(screen.getByText(/· 10 apps$/)).toBeInTheDocument()
    expect(screen.getByText(/40 of 60 apps/)).toBeInTheDocument()
  })
})

describe('VmIconGrid', () => {
  beforeEach(() => {
    navigate.mockClear()
    openConsole.mockClear()
    features = { ...ALL_FEATURES }
    capabilities = { lifecycle: true, console: true }
  })

  it('draws a VM as the same cell an app gets, wearing its OS', () => {
    wrapVms([VM])
    const tile = screen.getByTestId('vm-icon-1').querySelector('img')!
    expect(tile).toHaveAttribute('src', '/windows.svg')
    expect(screen.getByText('Running')).toHaveClass('uppercase')
  })

  it('falls back to initials for an OS Proxmox has not named', () => {
    // osIconUrl returns null both for an ostype we do not recognise and for
    // one PVE has not reported, and IconTile draws the initials tile for it,
    // so an unknown OS looks like an app with no logo, not a broken image.
    wrapVms([{ ...VM, os_type: null, name: 'solaris-box' }])
    const tile = screen.getByTestId('vm-icon-1')
    expect(tile.querySelector('img')).toBeNull()
    expect(tile).toHaveTextContent('SO')
  })

  it('groups VMs by node, the same as the apps beside them', () => {
    wrapVms([VM, { ...VM, id: 2, name: 'debian-lab', node: 'pve-c' }])
    expect(screen.getByRole('heading', { name: 'pve-a' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'pve-c' })).toBeInTheDocument()
    expect(screen.getAllByText(/1 VM$/)).toHaveLength(2)
  })

  it('opens the VM actions off the tile, not the app ones', async () => {
    wrapVms([VM])
    openMenu(screen.getByRole('button', { name: /actions for win11-lab/i }))
    const items = await screen.findAllByRole('menuitem')
    const labels = items.map((i) => i.textContent?.trim())
    expect(labels).toContain('Clone')
    expect(labels).not.toContain('Reconfigure')
  })

  it('opens the VM detail from the name, which is a row on the VMs table', () => {
    wrapVms([VM])
    fireEvent.click(screen.getByRole('button', { name: 'win11-lab' }))
    expect(navigate).toHaveBeenCalledWith(expect.objectContaining({
      to: '/vms', search: expect.objectContaining({ open: 1 }),
    }))
  })

  it('offers Start on a stopped VM, since the tile menu is the only way to act', async () => {
    // The bug: this menu was written as the three-dots HALF of VmActionBar,
    // where Start, Stop and Console are controls beside it, then reused whole
    // on the Hosts grid where that other half does not exist. A stopped VM's
    // tile offered Shutdown, no way to start it, and no way into it at all.
    // AppIconMenu already solved this with a `lifecycle` switch; this is the
    // VM half of it. Asserted as the WHOLE list, so the order is pinned and a
    // later addition cannot slip in unnoticed.
    wrapVms([{ ...VM, status: 'stopped' }])
    openMenu(screen.getByTestId('vm-icon-1'))
    const labels = (await screen.findAllByRole('menuitem'))
      .map((i) => i.textContent?.trim())
    expect(labels).toEqual(['Start', 'Console', 'Firewall', 'Options', 'Clone',
                            'Backup', 'Delete'])
  })

  it('offers Console on the tile, the only way into a VM at all', async () => {
    // Console is absent from VmActionsMenu because VmActionBar spends its
    // third button slot on it, which is true of the VMs table and false of
    // this grid. It is not a nice-to-have here: Proxploy opens no web UI and
    // reads no logs for a QEMU guest, so the console is the ONLY way in.
    wrapVms([VM])
    openMenu(screen.getByTestId('vm-icon-1'))
    const labels = (await screen.findAllByRole('menuitem'))
      .map((i) => i.textContent?.trim())
    expect(labels).toContain('Console')
    fireEvent.click(await screen.findByRole('menuitem', { name: /console/i }))
    expect(openConsole).toHaveBeenCalledWith('vm', 1)
  })

  it('withholds Console on a host with no console token', async () => {
    // The same host capability ConsoleButton reads, through the same hook, so
    // the menu item and the button cannot disagree about one host.
    capabilities = { lifecycle: true, console: false }
    wrapVms([VM])
    openMenu(screen.getByTestId('vm-icon-1'))
    const item = await screen.findByRole('menuitem', { name: /console/i })
    await waitFor(() => expect(item).toHaveAttribute('data-disabled'))
  })

  it('does not offer Start to a paused VM, which is suspended and not stopped', async () => {
    // 'paused' is not 'stopped': the guest is still running, just suspended,
    // so PVE refuses a start and Resume is the way back. Falling through to
    // the stopped table drew both Start and Resume on one menu.
    wrapVms([{ ...VM, status: 'paused' }])
    openMenu(screen.getByTestId('vm-icon-1'))
    const labels = (await screen.findAllByRole('menuitem'))
      .map((i) => i.textContent?.trim())
    expect(labels).toEqual(['Resume', 'Console', 'Firewall', 'Options', 'Clone',
                            'Backup', 'Delete'])
  })

  it('does not offer to shut down a VM that is already stopped', async () => {
    // Shutdown had no status guard at all while Pause and Resume did, so it
    // rendered on every VM in every state. The backend turns it into a no-op
    // ("already stopped; nothing to do" in services/lifecycle.py), so the
    // click cost a job row and changed nothing.
    wrapVms([{ ...VM, status: 'stopped' }])
    openMenu(screen.getByTestId('vm-icon-1'))
    const labels = (await screen.findAllByRole('menuitem'))
      .map((i) => i.textContent?.trim())
    expect(labels).not.toContain('Shutdown')
    expect(labels).not.toContain('Pause')
  })

  it('offers Stop, Restart and Shutdown on a running VM, never Start', async () => {
    wrapVms([VM])
    openMenu(screen.getByTestId('vm-icon-1'))
    const labels = (await screen.findAllByRole('menuitem'))
      .map((i) => i.textContent?.trim())
    expect(labels).toEqual(['Stop', 'Restart', 'Shutdown', 'Pause', 'Console',
                            'Firewall', 'Options', 'Clone', 'Backup', 'Delete'])
  })

  it('says Working rather than guessing an action set while a job is in flight', async () => {
    // 'pending' is the optimistic patch useLifecycle writes between the click
    // and the job resolving, not a PVE state. LifecycleActions already
    // refuses to guess from it; falling through to the stopped set here would
    // draw Start on a VM that is still running.
    wrapVms([{ ...VM, status: 'pending' }])
    openMenu(screen.getByTestId('vm-icon-1'))
    const labels = (await screen.findAllByRole('menuitem'))
      .map((i) => i.textContent?.trim())
    expect(labels).not.toContain('Start')
    expect(labels).not.toContain('Stop')
    expect(labels).not.toContain('Shutdown')
  })
})
