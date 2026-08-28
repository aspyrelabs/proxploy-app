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

import { VmTable } from '../components/VmTable'
import type { VmRow } from '../api/hooks'

const VM: VmRow = {
  id: 9, host_id: 1, host_name: 'pve-a', vmid: 201, name: 'win11',
  status: 'running', os_type: 'win11', cpu_cores: 2, cpu_pct: 12,
  // Used and allocated, the same meaning these names carry on an app row.
  mem_bytes: 2147483648, mem_total_bytes: 4294967296,
  disk_bytes: 53687091200, disk_total_bytes: 107374182400,
  net_in_bps: 1250000, net_out_bps: 125000,
  uptime_s: 86400, guest_agent_ok: null,
}

const OTHER: VmRow = { ...VM, id: 10, name: 'debian', vmid: 202 }

/** The table is controlled: VmsPage keeps the open row in the URL. This
 *  stands in for that owner so a click actually changes what is rendered. */
function Harness({ vms, initial }: { vms: VmRow[]; initial?: number }) {
  const [open, setOpen] = useState<number | undefined>(initial)
  return <VmTable vms={vms} open={open} onOpen={setOpen} />
}

const wrap = (vms: VmRow[], initial?: number) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}><Harness vms={vms} initial={initial} /></QueryClientProvider>)
}

// The first match, not the only one: once a row is open its detail panel is a
// row of the table too, and the panel names the VM as well (the snapshot list
// does). The guest's own row is always the earlier of the two in the DOM.
const rowFor = (name: string) => screen.getAllByRole('row', { name: new RegExp(name) })[0]
const panelIsOpen = (name: string) =>
  within(rowFor(name)).getByRole('button', { name }).getAttribute('aria-expanded') === 'true'

describe('VmTable', () => {
  it('is a real table, so a screen reader gets the column each cell belongs to', () => {
    wrap([VM])
    expect(screen.getByRole('table')).toBeInTheDocument()
    const headers = screen.getAllByRole('columnheader').map((h) => h.textContent)
    // The Apps table's own column set, in its order: the two lists are twins
    // and an operator should not have to relearn them halfway across.
    expect(headers).toEqual(
      ['Name', 'Host', 'Status', 'CPU', 'RAM', 'Storage', 'Network', ''])
  })

  it('carries the same measurements the apps row does', () => {
    wrap([VM])
    const row = rowFor('win11')
    expect(within(row).getByText('win11')).toBeInTheDocument()
    // Two lines since the host cell truncates the fully qualified name and
    // keeps the guest id under it.
    expect(within(row).getByText('pve-a')).toBeInTheDocument()
    expect(within(row).getByText(/VM 201/)).toBeInTheDocument()
    expect(within(row).getByText(/running/i)).toBeInTheDocument()
    // Pinned against the real formatters (frontend/src/lib/format.ts).
    // CPU is the raw percentage; RAM and Storage are used over allocated, so
    // both land on 50%; the storage cell also spells the bytes out.
    expect(within(row).getByText('12%')).toBeInTheDocument()
    expect(within(row).getAllByText('50%')).toHaveLength(2)
    // One unit, not two: fmtBytesPair drops the repeated GiB.
    expect(within(row).getByText('50.0 / 100.0 GiB')).toBeInTheDocument()
    // fmtBps multiplies by 8: 1250000 B/s = 10.0 Mbps, 125000 = 1.0 Mbps.
    // Down and up are their own elements now, stacked with a rule between, so
    // they are matched separately rather than as one run of text.
    expect(within(row).getByText(/↓ 10\.0 Mbps/)).toBeInTheDocument()
    expect(within(row).getByText(/↑ 1\.0 Mbps/)).toBeInTheDocument()
  })

  it('wears its OS as the tile the apps row uses for a logo', () => {
    // An app wears the logo of the Store entry it came from. A VM has no such
    // entry, so it wears its operating system instead. The fixture's ostype is
    // win11.
    wrap([VM])
    const row = rowFor('win11')
    expect(within(row).getByRole('img')).toHaveAttribute('src', '/windows.svg')
  })

  it('uses the linux tile for a linux ostype', () => {
    wrap([{ ...VM, os_type: 'l26' }])
    expect(within(rowFor('win11')).getByRole('img'))
      .toHaveAttribute('src', '/linux.svg')
  })

  it('falls back to the name initials when the ostype is unknown', () => {
    // Both the not-told-us-yet case (null, normal on a fleet the poller has
    // only just met) and an OS in neither family. Neither may render an <img>
    // pointing nowhere, which is what a broken tile would look like.
    for (const os_type of [null, 'solaris']) {
      const { unmount } = wrap([{ ...VM, os_type }])
      const row = rowFor('win11')
      expect(within(row).queryByRole('img')).toBeNull()
      expect(within(row).getByText('WIN')).toBeInTheDocument()
      unmount()
    }
  })

  it('reads storage as unknown, not as zero, on a VM with no guest agent', () => {
    // PVE cannot see inside the disk image without the QEMU guest agent, so
    // disk_bytes arrives null. A nought here would claim an empty disk, which
    // is a measurement nobody took.
    wrap([{ ...VM, disk_bytes: null }])
    const row = rowFor('win11')
    // Just the word, and the (i) that explains it. No bar drawn at nought and
    // no "unknown / 100.0 GiB", which pairs a non-answer with an answer as
    // though the two were the same kind of thing.
    expect(within(row).getByText('unknown')).toBeInTheDocument()
    expect(within(row).queryByText(/unknown \/ /)).toBeNull()
    expect(within(row).getByRole('button', { name: /QEMU guest agent/i }))
      .toBeInTheDocument()
    // CPU and RAM still read as percentages, so exactly one cell is unknown.
    expect(within(row).getAllByText('unknown')).toHaveLength(1)
  })

  it('opens the VM detail in place, with no navigation away from the table', () => {
    wrap([VM])
    expect(panelIsOpen('win11')).toBe(false)
    fireEvent.click(rowFor('win11'))
    expect(panelIsOpen('win11')).toBe(true)
    expect(navigate).not.toHaveBeenCalled()
  })

  it('shows that VM\'s own details in the panel', () => {
    wrap([VM, OTHER], 10)
    // 202 is debian's vmid and 201 is win11's; only the open row's KV grid
    // should be rendering one at all.
    expect(screen.getByText('202')).toBeInTheDocument()
    expect(screen.queryByText('201')).toBeNull()
    expect(screen.getByText('Snapshots')).toBeInTheDocument()
  })

  it('closes the first row when a second is clicked, so only one is ever open', () => {
    wrap([VM, OTHER])
    fireEvent.click(rowFor('win11'))
    expect(panelIsOpen('win11')).toBe(true)

    fireEvent.click(rowFor('debian'))
    expect(panelIsOpen('debian')).toBe(true)
    expect(panelIsOpen('win11')).toBe(false)
  })

  it('closes on a click anywhere outside the table', () => {
    wrap([VM])
    fireEvent.click(rowFor('win11'))
    expect(panelIsOpen('win11')).toBe(true)

    // pointerdown, not click: the listener runs on the press so it cannot
    // race the row's own onClick. See VmTable's click-away comment.
    fireEvent.pointerDown(document.body)
    expect(panelIsOpen('win11')).toBe(false)
  })

  it('stays open when the click lands inside the panel', () => {
    wrap([VM], 9)
    fireEvent.pointerDown(screen.getByText('Snapshots'))
    expect(panelIsOpen('win11')).toBe(true)
  })

  it('leaves the row alone when the click lands on the action bar', () => {
    wrap([VM])
    const cells = within(rowFor('win11')).getAllByRole('cell')
    fireEvent.click(cells[cells.length - 1])
    expect(panelIsOpen('win11')).toBe(false)
  })

  it('renders a missing reading as unknown, never as zero', () => {
    wrap([{ ...VM, cpu_pct: null, mem_bytes: null, net_in_bps: null, net_out_bps: null }])
    const row = rowFor('win11')
    // The CPU and RAM meters, plus both halves of the network cell, all say so
    // rather than drawing a nought. The two network figures are their own
    // stacked elements now, so they are two more matches rather than one
    // element carrying both.
    expect(within(row).getAllByText('unknown')).toHaveLength(2)
    expect(within(row).getByText(/↓ unknown/)).toBeInTheDocument()
    expect(within(row).getByText(/↑ unknown/)).toBeInTheDocument()
  })
})
