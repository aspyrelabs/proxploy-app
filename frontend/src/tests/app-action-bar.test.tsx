import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

// Icon is stubbed so this file tests the BAR, not the font subset: an
// unstubbed Icon renders the ligature name as text, which would land in every
// button's textContent (app-icon-grid.test.tsx precedent). icon.test.tsx pins
// Icon's own contract.
vi.mock('../components/ui/icon', () => ({
  Icon: ({ name, size }: { name: string; size?: number }) => (
    <span data-icon={name} data-size={size ?? 18} />
  ),
}))

let features: Record<string, boolean> = {}
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

const navigate = vi.fn()
vi.mock('@tanstack/react-router', async (orig) => ({
  ...(await orig() as object),
  useNavigate: () => navigate,
}))

import { AppActionBar } from '../components/AppActionBar'
import type { AppRow } from '../api/hooks'

const APP: AppRow = {
  id: 1, name: 'Immich', slug: 'immich', host_id: 1, host_name: 'pve-a',
  node: 'pve-a', ctid: 150, category: null, catalog_slug: 'immich',
  icon_initials: 'IM', icon_colors: null, icon_url: null,
  web_port: null, web_protocol: 'http', web_path: '/', installed_url: null,
  catalog_port: 8096,
  status: 'running', ip: '10.0.0.5', cpu_pct: 12,
  mem_bytes: 1, mem_total_bytes: 2, uptime_s: 1,
  update_available: null, adopted: false,
  disk_bytes: 1, disk_total_bytes: 2, net_in_bps: 1, net_out_bps: 1,
}

const ALL_FEATURES = {
  'apps.lifecycle': true, 'apps.open_ui': true, 'apps.reconfigure': true,
  'migrate.cross_host': true, 'backups.run': true, 'apps.uninstall': true,
}

const wrap = (app: AppRow) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}><AppActionBar app={app} /></QueryClientProvider>)
}

const labels = () =>
  within(screen.getByRole('group')).getAllByRole('button')
    .map((b) => b.getAttribute('aria-label') ?? b.textContent?.trim())

// Radix opens a menu on pointerdown, not click (AccountMenu/HostActionsMenu
// precedent).
const openMenu = () =>
  fireEvent.pointerDown(screen.getByRole('button', { name: /More actions for Immich/i }),
                        { button: 0, ctrlKey: false })

describe('AppActionBar', () => {
  beforeEach(() => {
    navigate.mockClear()
    features = { ...ALL_FEATURES }
    capabilities = { lifecycle: true, console: true }
  })

  it('offers Stop, Restart and Open beside a menu while the app is running', () => {
    // Three, not four: Firewall moved into the menu, which is where a thing
    // you open once per app belongs.
    wrap(APP)
    expect(labels()).toEqual(['Stop', 'Restart', 'Open', 'More actions for Immich'])
  })

  it('offers Start instead of Stop while it is not running', () => {
    // Never both: an app is either running or it is not, and offering the
    // pair would invite the wrong one.
    wrap({ ...APP, status: 'stopped' })
    expect(labels()).toEqual(['Start', 'Open', 'More actions for Immich'])
  })

  it('colours Start green and Stop red, the two opposite outcomes', () => {
    wrap(APP)
    expect(screen.getByRole('button', { name: 'Stop' }).className).toContain('text-red')
    wrap({ ...APP, id: 2, status: 'stopped' })
    expect(screen.getByRole('button', { name: 'Start' }).className).toContain('text-green')
  })

  it('leaves Restart neutral, since it lands back where it started', () => {
    wrap(APP)
    const restart = screen.getByRole('button', { name: 'Restart' }).className
    expect(restart).not.toContain('text-red')
    expect(restart).not.toContain('text-green')
  })

  it('hides Open when there is nothing to point a tab at', () => {
    // Absent, not disabled: a dead button invites a click that cannot go
    // anywhere.
    wrap({ ...APP, catalog_port: null })
    expect(labels()).toEqual(['Stop', 'Restart', 'More actions for Immich'])
  })

  it('opens the guest firewall route from the Firewall menu item', async () => {
    // The row keeps three buttons; Firewall navigates from the menu now.
    wrap(APP)
    expect(within(screen.getByRole('group')).queryByRole('button', { name: 'Firewall' }))
      .toBeNull()
    openMenu()
    fireEvent.click(await screen.findByRole('menuitem', { name: /firewall/i }))
    expect(navigate).toHaveBeenCalledWith({ to: '/firewall/guest/app/1' })
  })

  it('welds the actions into one group rather than loose buttons', () => {
    wrap(APP)
    // ButtonGroup carries role="group"; the separators are decorative and add
    // nothing to the accessible tree.
    expect(screen.getByRole('group')).toBeInTheDocument()
  })

  it('names the app on the dots trigger, which has no text of its own', () => {
    wrap(APP)
    const trigger = screen.getByRole('button', { name: 'More actions for Immich' })
    expect(trigger.querySelector('[data-icon="more_vert"]')).not.toBeNull()
  })

  it('keeps Console out of the row and in the menu', async () => {
    wrap(APP)
    expect(within(screen.getByRole('group')).queryByRole('button', { name: 'Console' }))
      .toBeNull()
    openMenu()
    expect(await screen.findByRole('menuitem', { name: /console/i })).toBeInTheDocument()
  })

  it('lists the seven other actions in the menu, Delete last and destructive', async () => {
    wrap(APP)
    openMenu()
    const items = await screen.findAllByRole('menuitem')
    expect(items.map((i) => i.textContent?.trim()))
      .toEqual(['Console', 'Logs', 'Firewall', 'Reconfigure', 'Migrate', 'Backup', 'Delete'])
    const del = items[items.length - 1]
    // The destructive vocabulary is the text-red token, and the border above
    // it is the separator keeping it off the end of the ordinary list.
    expect(del.className).toContain('text-red')
    expect(del.className).toContain('border-t')
  })

  it('does not repeat Start, Stop, Restart or Open inside the menu', async () => {
    wrap(APP)
    openMenu()
    const items = (await screen.findAllByRole('menuitem')).map((i) => i.textContent?.trim())
    for (const repeated of ['Start', 'Stop', 'Restart', 'Open']) {
      expect(items).not.toContain(repeated)
    }
  })

  it('opens the uninstall confirmation from Delete, rather than deleting on the spot', async () => {
    wrap(APP)
    openMenu()
    fireEvent.click(await screen.findByRole('menuitem', { name: /delete/i }))
    const dialog = await screen.findByRole('alertdialog')
    expect(dialog).toHaveTextContent(/uninstall/i)
    // UninstallDialog's own type-the-name gate is the confirmation; nothing
    // is destroyed by the menu item itself.
    expect(screen.getByRole('button', { name: /destroy container/i })).toBeInTheDocument()
  })

  it('withholds the plan-gated items once entitlements say the plan lacks them', async () => {
    features = { 'apps.lifecycle': true, 'apps.open_ui': true }
    wrap(APP)
    openMenu()
    const del = await screen.findByRole('menuitem', { name: /delete/i })
    // waitFor because nothing is withheld until /entitlements has actually
    // answered: api/app-gates.ts's "innocent until proven guilty" rule.
    await waitFor(() => expect(del).toHaveAttribute('data-disabled'))
    expect(screen.getByRole('menuitem', { name: /migrate/i })).toHaveAttribute('data-disabled')
  })
})
