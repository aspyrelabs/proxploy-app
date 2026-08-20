import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

vi.mock('../api/client', () => ({
  api: vi.fn(() => Promise.resolve([])),
  ApiError: class extends Error {},
}))
const navigate = vi.fn()
vi.mock('@tanstack/react-router', async (orig) => ({
  ...(await orig() as object),
  useNavigate: () => navigate,
}))

import { AppTable } from '../components/AppTable'
import type { AppRow } from '../api/hooks'

const APP: AppRow = {
  id: 1, name: 'Immich', slug: 'immich', host_id: 1, host_name: 'pve-a',
  node: 'pve-a', ctid: 150, category: null, catalog_slug: 'immich',
  icon_initials: 'IM', icon_colors: null, icon_url: null,
  web_port: null, web_protocol: 'http', web_path: '/', catalog_port: 8096,
  status: 'running', ip: '10.0.0.5', cpu_pct: 12,
  mem_bytes: 2147483648, mem_total_bytes: 4294967296, uptime_s: 86400,
  update_available: null, adopted: false,
  disk_bytes: 5368709120, disk_total_bytes: 17179869184,
  net_in_bps: 1200000, net_out_bps: 88000,
}

const wrap = (apps: AppRow[]) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}><AppTable apps={apps} /></QueryClientProvider>)
}

describe('AppTable', () => {
  it('is a real table, so a screen reader gets the column each cell belongs to', () => {
    wrap([APP])
    expect(screen.getByRole('table')).toBeInTheDocument()
    const headers = screen.getAllByRole('columnheader').map((h) => h.textContent)
    expect(headers).toEqual(['App', 'Host', 'Status', 'CPU', 'RAM', 'Storage', 'Network', ''])
  })

  it('carries the same detail as the card', () => {
    wrap([APP])
    const row = screen.getByRole('row', { name: /Immich/ })
    expect(within(row).getByText('Immich')).toBeInTheDocument()
    expect(within(row).getByText(/CT 150/)).toBeInTheDocument()
    expect(within(row).getByText(/running/i)).toBeInTheDocument()
    // Pinned against the real formatters (frontend/src/lib/format.ts), same
    // fixture values Task 5 pinned for AppCard: fmtBytes(5368709120) = "5.0
    // GiB", fmtBytes(17179869184) = "16.0 GiB", fmtBps(1200000) = "9.6 Mbps".
    expect(within(row).getByText(/5\.0 GiB \/ 16\.0 GiB/)).toBeInTheDocument()
    expect(within(row).getByText(/9\.6 Mbps/)).toBeInTheDocument()
  })

  it('opens the app detail page from the name', () => {
    wrap([APP])
    fireEvent.click(screen.getByRole('button', { name: 'Immich' }))
    expect(navigate).toHaveBeenCalledWith(expect.objectContaining({
      params: expect.objectContaining({ appId: '1' }),
    }))
  })

  it('renders a missing reading as unknown, never as zero', () => {
    wrap([{ ...APP, disk_bytes: null, disk_total_bytes: null,
            net_in_bps: null, net_out_bps: null }])
    expect(screen.queryByText(/Mbps/)).toBeNull()
  })
})
