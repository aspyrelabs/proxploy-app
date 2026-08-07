import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const APP = {
  id: 1, name: 'Immich', slug: 'immich', host_id: 1, host_name: 'host-01',
  node: 'pve1', ctid: 150, category: 'Media', icon_initials: 'IM',
  icon_colors: null, web_port: 8080, web_protocol: 'http', web_path: '/',
  status: 'running', ip: '10.0.0.5', cpu_pct: 12, mem_bytes: 100,
  mem_total_bytes: 400, uptime_s: 86400, update_available: null, adopted: false,
}

let appsResult: 'ok' | 'empty' | 'error' = 'ok'

vi.mock('../api/client', () => ({
  api: vi.fn((path: string) => {
    if (path.startsWith('/apps/discovered')) {
      return Promise.resolve([{ host_id: 1, host_name: 'host-01', ctid: 200,
        name: 'plex', node: 'pve1', status: 'running', suggestion: 'plex' }])
    }
    if (path.startsWith('/apps?') || path === '/apps') {
      if (appsResult === 'error') return Promise.reject(new Error('boom'))
      return Promise.resolve(appsResult === 'empty' ? [] : [APP])
    }
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

const withQuery = (ui: React.ReactNode) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

describe('AppsPage', () => {
  beforeEach(() => { appsResult = 'ok' })

  it('renders the grid, the shown-count and the discovered panel', async () => {
    withQuery(<AppsPage />)
    expect(await screen.findByText('Immich')).toBeInTheDocument()
    expect(screen.getByText('1 shown')).toBeInTheDocument()
    // name and suggestion are both "plex" in this fixture, so two elements
    // legitimately match /plex/ (the CT name and the "matches" badge), 
    // findAllByText avoids the ambiguous-match error findByText would throw.
    expect((await screen.findAllByText(/plex/)).length).toBeGreaterThan(0)
    expect(screen.getByRole('button', { name: /Adopt 1 container/i })).toBeInTheDocument()
  })

  it('says the apps could not be read rather than showing "no apps match"', async () => {
    appsResult = 'error'
    withQuery(<AppsPage />)
    expect(await screen.findByText(/apps not readable/i)).toBeInTheDocument()
    expect(screen.queryByText('No apps match your filter.')).not.toBeInTheDocument()
  })

  it('shows the real empty-filter copy when there genuinely are no matches', async () => {
    appsResult = 'empty'
    withQuery(<AppsPage />)
    expect(await screen.findByText('No apps match your filter.')).toBeInTheDocument()
    expect(screen.queryByText(/apps not readable/i)).not.toBeInTheDocument()
  })
})
