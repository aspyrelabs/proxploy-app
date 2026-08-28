import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useState } from 'react'
import { fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

vi.mock('../api/client', () => ({
  // GuestFirewallLine (rendered in the detail panel) reads these two; every
  // other query in this file is happy with the plain empty array.
  api: vi.fn((path: string) => {
    if (path.endsWith('/firewall/options')) {
      return Promise.resolve({ scope: 'guest', digest: null, options: { enable: 0 }, defaults: {} })
    }
    if (path.endsWith('/firewall/rules')) {
      return Promise.resolve({ scope: 'guest', digest: null, rules: [] })
    }
    return Promise.resolve([])
  }),
  ApiError: class extends Error {},
}))
const navigate = vi.fn()
vi.mock('@tanstack/react-router', async (orig) => ({
  ...(await orig() as object),
  useNavigate: () => navigate,
  // The detail panel's GuestFirewallLine renders a real Link, which needs a
  // <RouterProvider> this file never stands up; every other test mocks it
  // thin for the same reason.
  Link: ({ children }: { children?: unknown }) => <a>{children as never}</a>,
}))

import { AppTable } from '../components/AppTable'
import type { AppRow } from '../api/hooks'

const APP: AppRow = {
  id: 1, name: 'Immich', slug: 'immich', host_id: 1, host_name: 'pve-a',
  node: 'pve-a', ctid: 150, category: null, catalog_slug: 'immich',
  icon_initials: 'IM', icon_colors: null, icon_url: null,
  web_port: null, web_protocol: 'http', web_path: '/', installed_url: null,
  catalog_port: 8096,
  status: 'running', ip: '10.0.0.5', cpu_pct: 12,
  mem_bytes: 2147483648, mem_total_bytes: 4294967296, uptime_s: 86400,
  update_available: null, adopted: false,
  disk_bytes: 5368709120, disk_total_bytes: 17179869184,
  net_in_bps: 1200000, net_out_bps: 88000,
}

const OTHER: AppRow = { ...APP, id: 2, name: 'Paperless', slug: 'paperless',
                        ctid: 151, ip: '10.0.0.6' }

/** The table is controlled: AppsPage keeps the open row in the URL. This
 *  stands in for that owner so a click actually changes what is rendered. */
function Harness({ apps, initial }: { apps: AppRow[]; initial?: number }) {
  const [open, setOpen] = useState<number | undefined>(initial)
  return <AppTable apps={apps} open={open} onOpen={setOpen} />
}

const wrap = (apps: AppRow[], initial?: number) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}><Harness apps={apps} initial={initial} /></QueryClientProvider>)
}

const rowFor = (name: string) => screen.getByRole('row', { name: new RegExp(name) })
const panelIsOpen = (name: string) =>
  within(rowFor(name)).getByRole('button', { name }).getAttribute('aria-expanded') === 'true'

describe('AppTable', () => {
  it('is a real table, so a screen reader gets the column each cell belongs to', () => {
    wrap([APP])
    expect(screen.getByRole('table')).toBeInTheDocument()
    const headers = screen.getAllByRole('columnheader').map((h) => h.textContent)
    expect(headers).toEqual(['App', 'Host', 'Status', 'CPU', 'RAM', 'Storage', 'Network', ''])
  })

  it('carries the same detail as the card', () => {
    wrap([APP])
    const row = rowFor('Immich')
    expect(within(row).getByText('Immich')).toBeInTheDocument()
    expect(within(row).getByText(/CT 150/)).toBeInTheDocument()
    expect(within(row).getByText(/running/i)).toBeInTheDocument()
    // Pinned against the real formatters (frontend/src/lib/format.ts) rather
    // than against hand-typed strings, so a change to fmtBytes or fmtBps fails
    // here instead of quietly changing what every row prints:
    // fmtBytes(5368709120) = "5.0 GiB", fmtBytes(17179869184) = "16.0 GiB",
    // fmtBps(1200000) = "9.6 Mbps".
    expect(within(row).getByText(/5\.0 \/ 16\.0 GiB/)).toBeInTheDocument()
    expect(within(row).getByText(/9\.6 Mbps/)).toBeInTheDocument()
  })

  it('opens the app detail in place, with no navigation away from the table', () => {
    wrap([APP])
    expect(panelIsOpen('Immich')).toBe(false)
    fireEvent.click(rowFor('Immich'))
    expect(panelIsOpen('Immich')).toBe(true)
    expect(navigate).not.toHaveBeenCalled()
  })

  it('shows that app\'s own details in the panel', () => {
    wrap([APP, OTHER], 2)
    // 10.0.0.6 is Paperless's address and 10.0.0.5 is Immich's; only the open
    // row's KV grid should be rendering one at all.
    expect(screen.getByText('10.0.0.6')).toBeInTheDocument()
    expect(screen.queryByText('10.0.0.5')).toBeNull()
    // The CPU chart's range group: one per open panel, never two.
    expect(screen.getByRole('group', { name: 'CPU time range' })).toBeInTheDocument()
    expect(screen.getByText('CTID')).toBeInTheDocument()
  })

  it('marks an app with an update with a named dot, not a bare decoration', () => {
    // The dot carries no text, so its accessible name is the only wording a
    // screen reader gets. It has to say what the dot means, not "update".
    wrap([{ ...APP, update_available: '1.120.0' }])
    const dot = within(rowFor('Immich')).getByRole('img', { name: 'Update available' })
    expect(dot).toHaveAttribute('title', 'An update is available for this app')
    expect(dot).not.toHaveTextContent(/\S/)
  })

  it('explains the dot on focus, so a pointerless reader gets the wording too', async () => {
    wrap([{ ...APP, update_available: '1.120.0' }])
    fireEvent.focus(within(rowFor('Immich')).getByRole('img', { name: 'Update available' }))
    expect(await screen.findByRole('tooltip')).toHaveTextContent('Update available')
  })

  it('leaves an up-to-date app undotted', () => {
    wrap([APP])
    expect(screen.queryByRole('img', { name: 'Update available' })).toBeNull()
    expect(screen.queryByRole('tooltip')).toBeNull()
  })

  it('closes the first row when a second is clicked, so only one is ever open', () => {
    wrap([APP, OTHER])
    fireEvent.click(rowFor('Immich'))
    expect(panelIsOpen('Immich')).toBe(true)

    fireEvent.click(rowFor('Paperless'))
    expect(panelIsOpen('Paperless')).toBe(true)
    expect(panelIsOpen('Immich')).toBe(false)
  })

  it('closes on a click anywhere outside the table', () => {
    wrap([APP])
    fireEvent.click(rowFor('Immich'))
    expect(panelIsOpen('Immich')).toBe(true)

    // pointerdown, not click: the listener runs on the press so it cannot
    // race the row's own onClick. See AppTable's click-away comment.
    fireEvent.pointerDown(document.body)
    expect(panelIsOpen('Immich')).toBe(false)
  })

  it('stays open when the click lands inside the panel', () => {
    wrap([APP], 1)
    fireEvent.pointerDown(screen.getByRole('group', { name: 'CPU time range' }))
    expect(panelIsOpen('Immich')).toBe(true)
  })

  it('leaves the row alone when the click lands on the action bar', () => {
    wrap([APP])
    const cells = within(rowFor('Immich')).getAllByRole('cell')
    fireEvent.click(cells[cells.length - 1])
    expect(panelIsOpen('Immich')).toBe(false)
  })

  it('renders a missing reading as unknown, never as zero', () => {
    wrap([{ ...APP, disk_bytes: null, disk_total_bytes: null,
            net_in_bps: null, net_out_bps: null }])
    expect(screen.queryByText(/Mbps/)).toBeNull()
  })
})
