import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, renderHook, screen, waitFor, within } from '@testing-library/react'
import { useSyncExternalStore } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useCatalog, type CatalogRow, type CatalogStatus } from '../api/catalog'
import { api } from '../api/client'
import { StoreCard } from '../components/StoreCard'

vi.mock('../api/client', () => ({ api: vi.fn() }))

// StorePage now also fires /catalog/status and /entitlements (staleness
// banner + refresh gating). Without a reset, a mockResolvedValue/
// mockImplementation left behind by an earlier test in this file (several
// describes above set one) leaks into a later test that never touches `api`
// itself, e.g. handing useEntitlements' has() an object with no `.features`
// and throwing. Every test that cares about a response sets it itself, so a
// clean slate before each is a pure isolation fix, not a behavior change.
beforeEach(() => { vi.mocked(api).mockReset() })

// StorePage reads/writes category+q through router search params. Mock
// useSearch/useNavigate with a tiny external store (same shape as apps.test.tsx's
// static stub, but reactive) so a chip click's navigate() actually re-renders
// the page with the new search, needed to assert useCatalog gets re-called.
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

describe('cache invalidation keys', () => {
  const withQc = <T,>(hook: () => T) => {
    const qc = new QueryClient()
    const spy = vi.spyOn(qc, 'invalidateQueries')
    const wrapper = ({ children }: { children: React.ReactNode }) =>
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    const { result } = renderHook(hook, { wrapper })
    return { result, spy }
  }

  it('useRefreshCatalog invalidates catalog (a refresh is what rewrites it)', async () => {
    const { api } = await import('../api/client')
    const { useRefreshCatalog } = await import('../api/catalog')
    vi.mocked(api).mockResolvedValue({ job: { id: 1, kind: 'catalog.refresh' } })
    const { result, spy } = withQc(useRefreshCatalog)
    result.current.mutate()
    await waitFor(() => expect(spy).toHaveBeenCalledWith({ queryKey: ['catalog'] }))
    expect(spy).toHaveBeenCalledWith({ queryKey: ['jobs'] })
  })

  it('useInstall invalidates apps, not catalog (an install adds an App row)', async () => {
    const { api } = await import('../api/client')
    const { useInstall } = await import('../api/catalog')
    vi.mocked(api).mockResolvedValue({ job: { id: 2, kind: 'app.install' } })
    const { result, spy } = withQc(useInstall)
    result.current.mutate({ slug: 'redis', host_id: 1, name: 'Redis', ctid: 150,
                            overrides: {}, consent: true })
    await waitFor(() => expect(spy).toHaveBeenCalledWith({ queryKey: ['apps'] }))
    expect(spy).toHaveBeenCalledWith({ queryKey: ['jobs'] })
    expect(spy).not.toHaveBeenCalledWith({ queryKey: ['catalog'] })
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
    expect(screen.getByText(/1 of 2 scripts installable/i)).toBeInTheDocument()
    expect(screen.getByText(/1 unsupported/i)).toBeInTheDocument()
  })

  it('derives the real installed state per entry from the /apps list', async () => {
    const { useCatalog } = await import('../api/catalog')
    vi.mocked(useCatalog).mockReturnValue({
      data: [REDIS, { ...REDIS, slug: 'gitea', name: 'Gitea' }],
    } as any)
    const { api } = await import('../api/client')
    // Path-aware, not a blanket mockResolvedValue: the page now also fires
    // /catalog/status and /entitlements (staleness banner + refresh gating),
    // and a blanket app-array response for those would hand useEntitlements'
    // has() a `.features`-less object and throw.
    vi.mocked(api).mockImplementation((path: string) => {
      if (path === '/apps' || path.startsWith('/apps?')) {
        return Promise.resolve([{ id: 1, name: 'Redis', catalog_slug: 'redis', ctid: 150, host_id: 1 }])
      }
      return Promise.resolve(null)
    })

    withQuery(<StorePage />)

    // redis is installed -> disabled "Installed"; gitea is not -> "Install"
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Installed' })).toBeDisabled())
    expect(screen.getByRole('button', { name: 'Install' })).toBeEnabled()
  })

  it('says the catalog could not be read rather than showing "no store entries"', async () => {
    const { useCatalog } = await import('../api/catalog')
    vi.mocked(useCatalog).mockReturnValue({
      isError: true, isPending: false, data: undefined,
    } as any)
    withQuery(<StorePage />)
    expect(await screen.findByText(/store catalog not readable/i)).toBeInTheDocument()
    expect(screen.queryByText('No store entries match your filter.')).not.toBeInTheDocument()
  })

  it('shows the real empty-filter copy when there genuinely are no matches', async () => {
    const { useCatalog } = await import('../api/catalog')
    vi.mocked(useCatalog).mockReturnValue({
      isError: false, isPending: false, data: [],
    } as any)
    withQuery(<StorePage />)
    expect(await screen.findByText('No store entries match your filter.')).toBeInTheDocument()
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

describe('Store catalog staleness banner', () => {
  beforeEach(async () => {
    mockSearch = {}
    const { useCatalog } = await import('../api/catalog')
    vi.mocked(useCatalog).mockReturnValue({ data: [REDIS] } as any)
  })

  const mockStatus = async (status: CatalogStatus, features: Record<string, boolean> = { 'store.refresh': true }) => {
    const { api } = await import('../api/client')
    vi.mocked(api).mockImplementation((path: string) => {
      if (path === '/catalog/status') return Promise.resolve(status)
      if (path === '/entitlements') return Promise.resolve({ tier: 'builtin', features, grace: null, clock_skew: false })
      return Promise.resolve(null)
    })
  }

  it('shows the stale banner with a humanized age and a working Refresh button', async () => {
    await mockStatus({
      synced_at: '2026-07-01T00:00:00Z', age_s: 200_000, entries: 12,
      stale_after_s: 172_800, stale: true,
    })
    withQuery(<StorePage />)
    const banner = await screen.findByRole('alert')
    expect(banner).toHaveTextContent(/has not synced in/i)
    expect(banner).toHaveTextContent('2d 7h')
    expect(within(banner).getByRole('button', { name: 'Refresh' })).toBeEnabled()
  })

  it('renders "never synced" wording when synced_at is null', async () => {
    await mockStatus({ synced_at: null, age_s: null, entries: 0, stale_after_s: 172_800, stale: true })
    withQuery(<StorePage />)
    expect(await screen.findByRole('alert')).toHaveTextContent(/never synced/i)
  })

  it('shows no banner when not stale, and shows the last-synced time instead', async () => {
    await mockStatus({
      synced_at: '2026-08-08T00:00:00Z', age_s: 500, entries: 12,
      stale_after_s: 172_800, stale: false,
    })
    withQuery(<StorePage />)
    expect(await screen.findByText(/catalog synced 8m ago/i)).toBeInTheDocument()
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('disables the banner Refresh button when store.refresh is not entitled', async () => {
    await mockStatus({
      synced_at: null, age_s: null, entries: 0, stale_after_s: 172_800, stale: true,
    }, { 'store.refresh': false })
    withQuery(<StorePage />)
    const banner = await screen.findByRole('alert')
    expect(within(banner).getByRole('button', { name: 'Refresh' })).toBeDisabled()
  })
})
