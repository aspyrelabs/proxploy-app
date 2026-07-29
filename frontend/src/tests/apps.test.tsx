import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

const APP = {
  id: 1, name: 'Immich', slug: 'immich', host_id: 1, host_name: 'host-01',
  node: 'pve1', ctid: 150, category: 'Media', icon_initials: 'IM',
  icon_colors: null, web_port: 8080, web_protocol: 'http', web_path: '/',
  status: 'running', ip: '10.0.0.5', cpu_pct: 12, mem_bytes: 100,
  mem_total_bytes: 400, uptime_s: 86400, update_available: null, adopted: false,
}

vi.mock('../api/client', () => ({
  api: vi.fn((path: string) => {
    if (path.startsWith('/apps/discovered')) {
      return Promise.resolve([{ host_id: 1, host_name: 'host-01', ctid: 200,
        name: 'plex', node: 'pve1', status: 'running', suggestion: 'plex' }])
    }
    if (path.startsWith('/apps?') || path === '/apps') return Promise.resolve([APP])
    if (path.startsWith('/hosts')) {
      return Promise.resolve([{ id: 1, name: 'host-01' }])
    }
    return Promise.resolve(null)
  }),
  ApiError: class extends Error {},
}))

vi.mock('@tanstack/react-router', async (orig) => ({
  ...(await orig() as object),
  Link: ({ children }: { children?: unknown }) => <a>{children as never}</a>,
  useNavigate: () => () => {},
  useSearch: () => ({}),
}))

import { AppsPage } from '../routes/apps'

describe('AppsPage', () => {
  it('renders the grid, the shown-count and the discovered panel', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={qc}><AppsPage /></QueryClientProvider>)
    expect(await screen.findByText('Immich')).toBeInTheDocument()
    expect(screen.getByText('1 shown')).toBeInTheDocument()
    // name and suggestion are both "plex" in this fixture, so two elements
    // legitimately match /plex/ (the CT name and the "matches" badge) —
    // findAllByText avoids the ambiguous-match error findByText would throw.
    expect((await screen.findAllByText(/plex/)).length).toBeGreaterThan(0)
    expect(screen.getByText(/Adoption arrives with the App Store phase/)).toBeInTheDocument()
  })
})
