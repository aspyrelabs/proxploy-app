import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, renderHook, screen, waitFor, within } from '@testing-library/react'
import { useSyncExternalStore } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
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

// The Store grid is virtualized (@tanstack/react-virtual): it sizes its
// scroll container and measures each row from `offsetWidth`/`offsetHeight`
// (@tanstack/virtual-core's observeElementRect/measureElement), which jsdom
// always reports as 0, since it has no real layout engine. Without a
// generous fixed value the virtualizer would compute an empty visible range
// and mount nothing at all, the same class of fix time-chart.test.tsx
// already applies to TimeChart's own container measurement (there via
// getBoundingClientRect, here via the offset* properties virtual-core reads).
const originalOffsetHeight = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'offsetHeight')
const originalOffsetWidth = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'offsetWidth')
beforeEach(() => {
  Object.defineProperty(HTMLElement.prototype, 'offsetHeight', { configurable: true, value: 2000 })
  Object.defineProperty(HTMLElement.prototype, 'offsetWidth', { configurable: true, value: 1200 })
})
afterEach(() => {
  if (originalOffsetHeight) Object.defineProperty(HTMLElement.prototype, 'offsetHeight', originalOffsetHeight)
  if (originalOffsetWidth) Object.defineProperty(HTMLElement.prototype, 'offsetWidth', originalOffsetWidth)
})

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
    // entry_type defaults to "ct": the Store only ever browses LXC apps
    // (catalog expansion plan: non-LXC entries never appear in the Store).
    expect(api).toHaveBeenCalledWith('/catalog?category=Databases&q=redis&entry_type=ct')
  })

  it('requests a different entry_type when asked', async () => {
    const { api } = await import('../api/client')
    vi.mocked(api).mockResolvedValue([])
    const qc = new QueryClient()
    const wrapper = ({ children }: { children: React.ReactNode }) =>
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>

    const { result } = renderHook(() => useCatalog(undefined, undefined, 'vm'), { wrapper })
    await waitFor(() => expect(result.current.data).toBeDefined())
    expect(api).toHaveBeenCalledWith('/catalog?entry_type=vm')
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
  slug: 'redis', name: 'Redis', category: 'Databases', type: 'ct', description: null,
  icon_url: null, popularity: 42, website: 'https://redis.io/', docs_url: null,
  default_cpu: 1, default_ram_mb: 1024, default_disk_gb: 4,
  default_os: 'debian', default_os_version: '13',
  installable: true, unsupported_reason: null, upstream_state: 'listed', synced_at: null,
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

  it('renders cleanly with just name, type and an initial tile when nothing was scraped', () => {
    // Scripts are the source of truth; the community-scripts.org scrape is
    // best-effort decoration only (catalog expansion plan, decision 1). A
    // card must never look broken just because none of it landed.
    const bare = { ...REDIS, description: null, icon_url: null, popularity: null,
      category: null, name: null }
    render(<StoreCard entry={bare} onInstall={vi.fn()} installed={false} />)
    expect(screen.getByText('redis')).toBeInTheDocument()  // falls back to slug
    expect(screen.getByText('Uncategorized')).toBeInTheDocument()
    expect(screen.getByText('LXC')).toBeInTheDocument()  // the type badge
    expect(screen.getByText('RE')).toBeInTheDocument()  // initials tile, no <img>
    expect(screen.queryByRole('img')).toBeNull()
    // still fully interactive despite having nothing scraped
    expect(screen.getByRole('button', { name: 'Install' })).toBeEnabled()
  })

  it('still shows the Install button while a ct entry has not been classified yet', () => {
    // installable is tri-state: null means "not yet classified" (decision 2,
    // lazy classification). The card must not look broken or block install.
    const unclassified = { ...REDIS, installable: null }
    render(<StoreCard entry={unclassified} onInstall={vi.fn()} installed={false} />)
    expect(screen.getByRole('button', { name: 'Install' })).toBeEnabled()
    expect(screen.queryByText(/Not installable/)).toBeNull()
  })

  it('renders the real upstream icon and description when metadata matched', () => {
    // 547 of the 584 ct rows get real upstream metadata, so this is the
    // common card, not the exotic one: the icon is upstream's own CDN URL
    // rendered directly (no local binary cache) and the description block
    // finally has something in it.
    const enriched = { ...REDIS,
      icon_url: 'https://cdn.jsdelivr.net/gh/selfhst/icons@main/webp/redis.webp',
      description: 'Redis is an open source, in-memory data structure store.' }
    render(<StoreCard entry={enriched} onInstall={vi.fn()} installed={false} />)
    const img = screen.getByRole('img')
    expect(img).toHaveAttribute('src', enriched.icon_url)
    expect(img).toHaveAttribute('alt', 'Redis')
    expect(screen.queryByText('RE')).toBeNull()  // the initials tile stays out of the way
    expect(screen.getByText(/in-memory data structure store/)).toBeInTheDocument()
  })

  it('falls back to the initials tile when the scraped logo fails to load', () => {
    const withLogo = { ...REDIS, icon_url: 'https://example.com/redis.webp' }
    render(<StoreCard entry={withLogo} onInstall={vi.fn()} installed={false} />)
    const img = screen.getByRole('img')
    fireEvent.error(img)
    expect(screen.queryByRole('img')).toBeNull()
    expect(screen.getByText('RE')).toBeInTheDocument()
  })

  const BADGE = 'Not listed upstream'

  it('badges nothing for a row upstream still lists, or has not classified', () => {
    const { rerender } = render(<StoreCard entry={REDIS} onInstall={vi.fn()} installed={false} />)
    expect(screen.queryByText(BADGE)).toBeNull()
    // null is the pre-sync state, not a signal: it must not badge either.
    rerender(<StoreCard entry={{ ...REDIS, upstream_state: null }}
                        onInstall={vi.fn()} installed={false} />)
    expect(screen.queryByText(BADGE)).toBeNull()
  })

  it('badges an unlisted row, and still lets you install it', () => {
    // The 9 rows upstream dropped outright: no metadata to have, so the card
    // is bare apart from the badge. The script is still in the repo, so the
    // badge is a fact about upstream, never a block on installing.
    const gone = { ...REDIS, upstream_state: 'unlisted' as const,
      name: null, description: null, icon_url: null, category: null, popularity: null }
    render(<StoreCard entry={gone} onInstall={vi.fn()} installed={false} />)
    expect(screen.getByText(BADGE)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Install' })).toBeEnabled()
    expect(screen.getByText('RE')).toBeInTheDocument()  // initials tile, no icon to show
    expect(screen.queryByRole('img')).toBeNull()
    expect(screen.getByText('LXC')).toBeInTheDocument()  // the type badge keeps its place
    // Honest about what we actually know, and never the word "deprecated".
    expect(screen.getByTitle(/no longer lists this app/i)).toBeInTheDocument()
    expect(screen.queryByText(/deprecated/i)).toBeNull()
  })

  it('badges a delisted row that still has all its metadata', () => {
    // The 5 soft-deleted upstream rows arrive fully populated, so the badge
    // has to read correctly next to a real icon and description too, not just
    // on a blank card.
    const soft = { ...REDIS, upstream_state: 'delisted' as const,
      icon_url: 'https://cdn.jsdelivr.net/gh/selfhst/icons@main/webp/minio.webp',
      name: 'MinIO', description: 'S3 compatible object storage.' }
    render(<StoreCard entry={soft} onInstall={vi.fn()} installed={false} />)
    expect(screen.getByText(BADGE)).toBeInTheDocument()
    expect(screen.getByRole('img')).toHaveAttribute('src', soft.icon_url)
    expect(screen.getByText('S3 compatible object storage.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Install' })).toBeEnabled()
  })

  it('reads coherently when a row is both unlisted and not installable', () => {
    // Two different facts, kept in two different places rather than argued
    // out on one line: the badge sits with the type chip and speaks about
    // upstream's catalog, the note sits in the action row and speaks about
    // whether we can run the script unattended. The existing upstream link
    // still works.
    const both = { ...REDIS, upstream_state: 'unlisted' as const, installable: false,
      unsupported_reason: 'install script requires interactive input, no non-interactive entrypoint' }
    render(<StoreCard entry={both} onInstall={vi.fn()} installed={false} />)
    expect(screen.getByText(BADGE)).toBeInTheDocument()
    expect(screen.getByText(/Not installable/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Install' })).toBeNull()
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

  it('filters by category chip, client-side over the one fetched list', async () => {
    // The Store fetches its ct/ catalog once and filters locally (fast chip
    // clicks over ~533 rows, no round trip per click), unlike the old
    // server-filtered design this replaces.
    const { useCatalog } = await import('../api/catalog')
    const mocked = vi.mocked(useCatalog)
    const gitea = { ...REDIS, slug: 'gitea', name: 'Gitea', category: 'Dev Tools' }
    mocked.mockReturnValue({ data: [REDIS, gitea] } as any)
    mocked.mockClear()  // drop call history from other tests sharing this module-level mock
    withQuery(<StorePage />)

    expect(screen.getByText('Redis')).toBeInTheDocument()
    expect(screen.getByText('Gitea')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Databases' }))

    expect(screen.getByText('Redis')).toBeInTheDocument()
    expect(screen.queryByText('Gitea')).not.toBeInTheDocument()
    // the chip click never changes what's fetched: every call asked for the
    // whole ct/ catalog, filtering happened in the browser, not the server
    for (const call of mocked.mock.calls) {
      expect(call).toEqual([undefined, undefined, 'ct'])
    }
  })

  it('searches by name, client-side', async () => {
    const { useCatalog } = await import('../api/catalog')
    const mocked = vi.mocked(useCatalog)
    const gitea = { ...REDIS, slug: 'gitea', name: 'Gitea', category: 'Dev Tools' }
    mocked.mockReturnValue({ data: [REDIS, gitea] } as any)
    withQuery(<StorePage />)

    fireEvent.change(screen.getByPlaceholderText(/search the store/i), { target: { value: 'git' } })

    expect(screen.queryByText('Redis')).not.toBeInTheDocument()
    expect(screen.getByText('Gitea')).toBeInTheDocument()
  })

  it('searches descriptions too, not just the name and slug', async () => {
    // Descriptions are populated now, so the thing an operator actually
    // remembers about an app ("the one that organizes your media") has to be
    // findable. A row with a null description must not blow up the filter.
    const { useCatalog } = await import('../api/catalog')
    const plex = { ...REDIS, slug: 'plex', name: 'Plex Media Server',
      description: 'Plex magically scans and organizes your files.' }
    vi.mocked(useCatalog).mockReturnValue({ data: [REDIS, plex] } as any)
    withQuery(<StorePage />)

    fireEvent.change(screen.getByPlaceholderText(/search the store/i),
                     { target: { value: 'organizes' } })

    expect(screen.getByText('Plex Media Server')).toBeInTheDocument()
    expect(screen.queryByText('Redis')).not.toBeInTheDocument()
  })

  it('handles the real upstream category vocabulary in the chips and the filter', async () => {
    // The upstream vocabulary of 26 is longer and more punctuated than the
    // slug heuristic it replaces: a leading asterisk, slashes, commas and
    // ampersands all have to survive chip rendering, the default sort and
    // the client-side equality filter.
    const { useCatalog } = await import('../api/catalog')
    vi.mocked(useCatalog).mockReturnValue({
      data: [
        { ...REDIS, slug: 'plex', name: 'Plex', category: 'Media & Streaming' },
        { ...REDIS, slug: 'sonarr', name: 'Sonarr', category: '*Arr Suite' },
        { ...REDIS, slug: 'ollama', name: 'Ollama', category: 'AI / Coding & Dev-Tools' },
        { ...REDIS, slug: 'z2m', name: 'Zigbee2MQTT', category: 'ZigBee, Z-Wave & Matter' },
      ],
    } as any)
    withQuery(<StorePage />)

    const chips = ['All', '*Arr Suite', 'AI / Coding & Dev-Tools',
                   'Media & Streaming', 'ZigBee, Z-Wave & Matter']
    for (const c of chips) expect(screen.getByRole('button', { name: c })).toBeInTheDocument()
    // "All" stays pinned first and the rest sort lexicographically, which puts
    // the asterisk ahead of the letters rather than anywhere surprising.
    const rendered = screen.getAllByRole('button')
      .map((b) => b.textContent ?? '').filter((t) => chips.includes(t))
    expect(rendered).toEqual(chips)

    fireEvent.click(screen.getByRole('button', { name: 'AI / Coding & Dev-Tools' }))
    expect(screen.getByText('Ollama')).toBeInTheDocument()
    expect(screen.queryByText('Plex')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '*Arr Suite' }))
    expect(screen.getByText('Sonarr')).toBeInTheDocument()
    expect(screen.queryByText('Ollama')).not.toBeInTheDocument()
  })

  it('derives category chips from the real data rather than a fixed list', async () => {
    const { useCatalog } = await import('../api/catalog')
    vi.mocked(useCatalog).mockReturnValue({
      data: [REDIS, { ...REDIS, slug: 'haos-vm', category: 'VM Scripts' }],
    } as any)
    withQuery(<StorePage />)
    expect(screen.getByRole('button', { name: 'All' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Databases' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'VM Scripts' })).toBeInTheDocument()
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

import { applyJob } from '../api/live'

/**
 * The Refresh button's progress bar. POST /catalog/refresh only enqueues
 * `catalog.refresh`, so the bar is driven by the job itself: useJob's
 * ['jobs', id] cache entry, patched live by api/live.ts::applyJob from the
 * one SSE stream LiveProvider already runs. These tests drive applyJob
 * directly for exactly that reason, it is the real production path, not a
 * stand-in for one.
 */
describe('Store refresh progress', () => {
  const FRESH_STATUS: CatalogStatus = {
    synced_at: '2026-08-13T00:00:00Z', age_s: 30, entries: 1,
    stale_after_s: 172_800, stale: false,
  }
  let jobRow: Record<string, unknown>
  let refreshResponse: () => Promise<unknown>

  beforeEach(async () => {
    mockSearch = {}
    const { useCatalog } = await import('../api/catalog')
    vi.mocked(useCatalog).mockReturnValue({ data: [REDIS] } as any)
    jobRow = { id: 7, kind: 'catalog.refresh', status: 'running', progress_pct: null }
    refreshResponse = () => Promise.resolve({ job: { id: 7, kind: 'catalog.refresh' } })
  })

  const mockApi = async (
    features: Record<string, boolean> = { 'store.refresh': true },
    status: CatalogStatus = FRESH_STATUS,
  ) => {
    const { api } = await import('../api/client')
    vi.mocked(api).mockImplementation((path: string) => {
      if (path === '/catalog/refresh') return refreshResponse()
      if (path === '/jobs/7') return Promise.resolve(jobRow)
      if (path === '/catalog/status') return Promise.resolve(status)
      if (path === '/entitlements') {
        return Promise.resolve({ tier: 'builtin', features, grace: null, clock_skew: false })
      }
      return Promise.resolve(null)
    })
  }

  const renderStore = () => {
    const qc = new QueryClient()
    render(<QueryClientProvider client={qc}><StorePage /></QueryClientProvider>)
    return qc
  }

  const clickHeaderRefresh = () =>
    fireEvent.click(screen.getAllByRole('button', { name: 'Refresh' })[0])

  it('goes indeterminate first, then follows the job\'s real progress', async () => {
    await mockApi()
    const qc = renderStore()
    expect(screen.queryByRole('progressbar')).toBeNull()

    clickHeaderRefresh()

    const bar = await screen.findByRole('progressbar', { name: /refreshing the catalog/i })
    // Queued with progress_pct null, and services/catalog.py publishes nothing
    // at all until discovery returns: there is no number yet, so the bar
    // claims none rather than animating up from a made-up zero.
    expect(bar).toHaveAttribute('aria-busy', 'true')
    expect(bar).not.toHaveAttribute('aria-valuenow')
    await waitFor(() => expect(qc.getQueryData(['jobs', 7])).toBeDefined())

    // 45 then 85 are the first two values refresh_catalog actually emits
    // (discovery done, upstream metadata sync done).
    act(() => applyJob(qc, { id: 7, kind: 'catalog.refresh', status: 'running', progress_pct: 45 }))
    await waitFor(() =>
      expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '45'))
    expect(screen.getByText('45%')).toBeInTheDocument()

    act(() => applyJob(qc, { id: 7, kind: 'catalog.refresh', status: 'running', progress_pct: 85 }))
    await waitFor(() =>
      expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '85'))
  })

  it('drops the bar when the job succeeds, and re-arms the button', async () => {
    await mockApi()
    const qc = renderStore()
    clickHeaderRefresh()
    await screen.findByRole('progressbar')
    await waitFor(() => expect(qc.getQueryData(['jobs', 7])).toBeDefined())

    jobRow = { ...jobRow, status: 'succeeded', progress_pct: 100 }
    act(() => applyJob(qc, { id: 7, kind: 'catalog.refresh', status: 'succeeded', progress_pct: 100 }))

    await waitFor(() => expect(screen.queryByRole('progressbar')).toBeNull())
    expect(screen.getAllByRole('button', { name: 'Refresh' })[0]).toBeEnabled()
  })

  it('drops the bar when the job fails rather than parking it at a percentage', async () => {
    await mockApi()
    const qc = renderStore()
    clickHeaderRefresh()
    await screen.findByRole('progressbar')
    await waitFor(() => expect(qc.getQueryData(['jobs', 7])).toBeDefined())

    act(() => applyJob(qc, { id: 7, kind: 'catalog.refresh', status: 'running', progress_pct: 45 }))
    await waitFor(() =>
      expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '45'))

    jobRow = { ...jobRow, status: 'failed', progress_pct: 45 }
    act(() => applyJob(qc, { id: 7, kind: 'catalog.refresh', status: 'failed', progress_pct: 45 }))

    await waitFor(() => expect(screen.queryByRole('progressbar')).toBeNull())
  })

  it('starts one job and one bar however many Refresh buttons are clicked', async () => {
    // Both the header control and the staleness banner's own Refresh drive
    // the same job, so a second click while one is in flight must not enqueue
    // a second refresh or draw a second bar.
    await mockApi({ 'store.refresh': true },
                  { synced_at: null, age_s: null, entries: 0, stale_after_s: 172_800, stale: true })
    const { api } = await import('../api/client')
    renderStore()
    const banner = await screen.findByRole('alert')

    clickHeaderRefresh()
    await screen.findByRole('progressbar')
    fireEvent.click(within(banner).getByRole('button', { name: 'Refresh' }))

    expect(screen.getAllByRole('progressbar')).toHaveLength(1)
    expect(vi.mocked(api).mock.calls.filter((c) => c[0] === '/catalog/refresh')).toHaveLength(1)
    for (const b of screen.getAllByRole('button', { name: 'Refresh' })) expect(b).toBeDisabled()
  })

  it('shows no bar at all for a refresh the plan does not include', async () => {
    // The POST is going to 403, so there will be no job to report on. The
    // in-flight mutation alone must not put a bar on screen.
    refreshResponse = () => new Promise(() => {})  // never settles: still in flight
    await mockApi({ 'store.refresh': false },
                  { synced_at: null, age_s: null, entries: 0, stale_after_s: 172_800, stale: true })
    renderStore()
    const banner = await screen.findByRole('alert')
    await waitFor(() =>
      expect(within(banner).getByRole('button', { name: 'Refresh' })).toBeDisabled())

    clickHeaderRefresh()

    await waitFor(() => expect(screen.getByText(/never synced/i)).toBeInTheDocument())
    expect(screen.queryByRole('progressbar')).toBeNull()
  })
})
