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

let features: Record<string, boolean> = { 'apps.lifecycle': true, 'apps.open_ui': true }
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

import { AppIconGrid } from '../components/AppIconGrid'
import type { AppRow } from '../api/hooks'

const APP: AppRow = {
  id: 1, name: 'Immich', slug: 'immich', host_id: 1, host_name: 'pve-a',
  node: 'pve-a', ctid: 150, category: null, catalog_slug: 'immich',
  icon_initials: 'IM', icon_colors: null, icon_url: null,
  web_port: null, web_protocol: 'http', web_path: '/', catalog_port: 8096,
  status: 'running', ip: '10.0.0.5', cpu_pct: 12,
  mem_bytes: 1, mem_total_bytes: 2, uptime_s: 86400,
  update_available: null, adopted: false,
  disk_bytes: 1, disk_total_bytes: 2, net_in_bps: 1, net_out_bps: 1,
}

const wrap = (apps: AppRow[]) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}><AppIconGrid apps={apps} /></QueryClientProvider>)
}

// Radix opens a menu on pointerdown, not click (AccountMenu/HostActionsMenu
// precedent).
const openMenu = (trigger: HTMLElement) =>
  fireEvent.pointerDown(trigger, { button: 0, ctrlKey: false })

describe('AppIconGrid', () => {
  beforeEach(() => {
    navigate.mockClear()
    features = { 'apps.lifecycle': true, 'apps.open_ui': true }
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
    expect(grid.className).toMatch(/minmax\(13rem,\s*1fr\)/)
    expect(grid.className).not.toMatch(/grid-cols-\d/)
    // Past the floor it still ellipses rather than blowing the column open,
    // and the full name stays reachable on hover.
    const name = screen.getByRole('button', { name: 'a-twenty-char-name!!' })
    expect(name.className).toContain('truncate')
    expect(name).toHaveAttribute('title', 'a-twenty-char-name!!')
  })

  it('opens the app detail page from the name', () => {
    wrap([APP])
    fireEvent.click(screen.getByRole('button', { name: 'Immich' }))
    expect(navigate).toHaveBeenCalledWith(expect.objectContaining({
      params: expect.objectContaining({ appId: '1' }),
    }))
  })

  it('offers exactly the five actions on the logo, and no more', async () => {
    wrap([APP])
    openMenu(screen.getByRole('button', { name: /actions for Immich/i }))
    const items = await screen.findAllByRole('menuitem')
    // trim(): each item renders `<Icon /> {label}`, so its textContent
    // carries a leading space the stubbed Icon leaves behind.
    // Running, so Stop and Restart show and Start does not: the same action
    // set LifecycleActions already picks from status.
    expect(items.map((i) => i.textContent?.trim()))
      .toEqual(['Stop', 'Restart', 'Console', 'Open'])
  })

  it('offers Start instead of Stop when the app is stopped', async () => {
    wrap([{ ...APP, status: 'stopped' }])
    openMenu(screen.getByRole('button', { name: /actions for Immich/i }))
    const items = await screen.findAllByRole('menuitem')
    expect(items.map((i) => i.textContent?.trim())).toEqual(['Start', 'Console', 'Open'])
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
})
