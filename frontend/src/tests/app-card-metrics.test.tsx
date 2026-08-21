import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

vi.mock('../api/client', () => ({
  api: vi.fn(() => Promise.resolve([])),
  ApiError: class extends Error {},
}))
vi.mock('@tanstack/react-router', async (orig) => ({
  ...(await orig() as object),
  useNavigate: () => () => {},
}))

import { AppCard } from '../components/AppCard'
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

const wrap = (app: AppRow) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}><AppCard app={app} /></QueryClientProvider>)
}

describe('AppCard storage and network', () => {
  it('shows storage as used against allocated', () => {
    wrap(APP)
    expect(screen.getByText(/5\.0 GiB \/ 16\.0 GiB/)).toBeInTheDocument()
  })

  it('shows both network directions as rates', () => {
    wrap(APP)
    // fmtBps takes bytes/s and renders bits/s, the vocabulary the node
    // network charts already use.
    expect(screen.getByText(/9\.6 Mbps/)).toBeInTheDocument()
    expect(screen.getByText(/704\.0 kbps/)).toBeInTheDocument()
  })

  it('renders a missing reading as unknown, never as zero', () => {
    // An unpolled app, a stopped container, and the cycle after a counter
    // reset all land here. "0 Mbps" would claim the container is idle when
    // nothing has measured it.
    wrap({ ...APP, disk_bytes: null, disk_total_bytes: null,
           net_in_bps: null, net_out_bps: null })
    expect(screen.queryByText(/Mbps/)).toBeNull()
    expect(screen.getAllByText(/unknown/i).length).toBeGreaterThan(0)
  })
})

describe('AppCard update mark', () => {
  it('names and explains the dot, which carries no text of its own', async () => {
    wrap({ ...APP, update_available: '1.120.0' })
    const dot = screen.getByRole('img', { name: 'Update available' })
    expect(dot).toHaveAttribute('title', 'An update is available for this app')
    fireEvent.focus(dot)
    expect(await screen.findByRole('tooltip')).toHaveTextContent('Update available')
  })

  it('draws no dot and no tooltip for an app that is up to date', () => {
    wrap(APP)
    expect(screen.queryByRole('img', { name: 'Update available' })).toBeNull()
    expect(screen.queryByRole('tooltip')).toBeNull()
  })
})
