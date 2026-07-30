import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react'
import { useSyncExternalStore } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useCatalog, type CatalogRow } from '../api/catalog'
import { StoreCard } from '../components/StoreCard'

vi.mock('../api/client', () => ({ api: vi.fn() }))

// StorePage reads/writes category+q through router search params. Mock
// useSearch/useNavigate with a tiny external store (same shape as apps.test.tsx's
// static stub, but reactive) so a chip click's navigate() actually re-renders
// the page with the new search — needed to assert useCatalog gets re-called.
let mockSearch: { category?: string; q?: string } = {}
const searchListeners = new Set<() => void>()
vi.mock('@tanstack/react-router', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@tanstack/react-router')>()),
  useSearch: () => useSyncExternalStore(
    (cb) => { searchListeners.add(cb); return () => searchListeners.delete(cb) },
    () => mockSearch,
  ),
  useNavigate: () => (opts: { search: typeof mockSearch }) => {
    mockSearch = opts.search
    searchListeners.forEach((cb) => cb())
  },
}))

describe('useCatalog', () => {
  it('fetches with category/q query params', async () => {
    const { api } = await import('../api/client')
    vi.mocked(api).mockResolvedValue([{ slug: 'redis', name: 'Redis' }])
    const qc = new QueryClient()
    const wrapper = ({ children }: { children: React.ReactNode }) =>
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>

    const { result } = renderHook(() => useCatalog('Databases', 'redis'), { wrapper })
    await waitFor(() => expect(result.current.data).toBeDefined())
    expect(api).toHaveBeenCalledWith('/catalog?category=Databases&q=redis')
  })
})

const REDIS: CatalogRow = {
  slug: 'redis', name: 'Redis', category: 'Databases', description: null,
  icon_url: null, popularity: 42, website: 'https://redis.io/',
  default_cpu: 1, default_ram_mb: 1024, default_disk_gb: 4,
  default_os: 'debian', default_os_version: '13',
  installable: true, unsupported_reason: null, synced_at: null,
}

describe('StoreCard', () => {
  it('renders an Install button for an installable entry and fires onInstall', () => {
    const onInstall = vi.fn()
    render(<StoreCard entry={REDIS} onInstall={onInstall} installed={false} />)
    fireEvent.click(screen.getByRole('button', { name: 'Install' }))
    expect(onInstall).toHaveBeenCalledWith('redis')
  })

  it('shows a disabled Installed state', () => {
    render(<StoreCard entry={REDIS} onInstall={vi.fn()} installed />)
    expect(screen.getByRole('button', { name: 'Installed' })).toBeDisabled()
  })

  it('shows an honest note + upstream link for an unsupported entry, no Install control', () => {
    const unsupported = { ...REDIS, installable: false,
      unsupported_reason: 'install script requires interactive input, no non-interactive entrypoint' }
    render(<StoreCard entry={unsupported} onInstall={vi.fn()} installed={false} />)
    expect(screen.queryByRole('button', { name: 'Install' })).toBeNull()
    expect(screen.getByText(/Not installable/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /upstream/i })).toHaveAttribute('href', 'https://redis.io/')
  })
})

import { StorePage } from '../routes/store'

vi.mock('../api/catalog', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/catalog')>()
  // wrap (not replace) so the real-hook test above still exercises actual
  // useCatalog; StorePage tests below override it per-test via mockReturnValue.
  return { ...actual, useCatalog: vi.fn(actual.useCatalog) }
})

const withQuery = (ui: React.ReactNode) => {
  const qc = new QueryClient()
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

describe('StorePage', () => {
  beforeEach(() => { mockSearch = {} })

  it('shows the true installable/unsupported counts in the header', async () => {
    const { useCatalog } = await import('../api/catalog')
    vi.mocked(useCatalog).mockReturnValue({
      data: [
        { ...REDIS, installable: true },
        { ...REDIS, slug: 'docker', installable: false, unsupported_reason: 'x' },
      ],
    } as any)
    withQuery(<StorePage />)
    expect(screen.getByText(/showing 2 of 1 installable/i)).toBeInTheDocument()
    expect(screen.getByText(/1 unsupported/i)).toBeInTheDocument()
  })

  it('filters by category chip', async () => {
    const { useCatalog } = await import('../api/catalog')
    const mocked = vi.mocked(useCatalog)
    mocked.mockReturnValue({ data: [REDIS] } as any)
    withQuery(<StorePage />)
    fireEvent.click(screen.getByRole('button', { name: 'Databases' }))
    expect(mocked).toHaveBeenLastCalledWith('Databases', undefined)
  })
})
