import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, renderHook, screen, waitFor, within } from '@testing-library/react'
import { useSyncExternalStore } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useCatalog, type CatalogRow, type CatalogStatus } from '../api/catalog'
import { api } from '../api/client'
import { StoreCard } from '../components/StoreCard'
import { popularityBand } from '../lib/store-order'

vi.mock('../api/client', () => ({ api: vi.fn() }))

// StorePage now also fires /catalog/status and /entitlements (staleness
// banner + refresh gating). Without a reset, a mockResolvedValue/
// mockImplementation left behind by an earlier test in this file (several
// describes above set one) leaks into a later test that never touches `api`
// itself, e.g. handing useEntitlements' has() an object with no `.features`
// and throwing. Every test that cares about a response sets it itself, so a
// clean slate before each is a pure isolation fix, not a behavior change.
beforeEach(() => { vi.mocked(api).mockReset() })

// The grid used to be virtualized and needed jsdom offsetWidth/offsetHeight
// stubs to mount anything at all. It renders one page of plain grid cells
// now, so there is no measurement to fake: what the DOM contains is exactly
// the page the user is on, which is also what makes the card counts below
// assertable rather than a function of a simulated viewport.
//
// The Select in the pagination bar is Radix, and Radix's dismissable layer
// drives its trigger through Pointer Events that jsdom does not implement.
// These three are the standard jsdom gap fillers for it, nothing more: they
// let the listbox open so the real widget can be exercised.
const pointerStubs: Array<[string, unknown]> = [
  ['hasPointerCapture', () => false],
  ['setPointerCapture', () => {}],
  ['releasePointerCapture', () => {}],
  ['scrollIntoView', () => {}],
]
beforeEach(() => {
  for (const [name, impl] of pointerStubs) {
    Object.defineProperty(Element.prototype, name, { configurable: true, writable: true, value: impl })
  }
})

// StorePage reads/writes category+sort+page+pageSize through router search
// params. Mock useSearch/useNavigate with a tiny external store (same shape as
// apps.test.tsx's static stub, but reactive) so a chip click's navigate()
// actually re-renders the page with the new search, needed to assert
// useCatalog gets re-called and that paging and ordering survive in the URL.
let mockSearch: { category?: string; page?: number; pageSize?: number; sort?: string } = {}
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
  // StoreCard's title and Read more are real <Link>s now, and a Link outside a
  // RouterProvider throws on the router context. Same stand-in
  // icon-names-coverage.test.tsx uses, plus param interpolation, so the tests
  // below can assert the real resolved path ("/store/redis") rather than just
  // that some anchor exists: a wrong param name shows up here as an empty
  // segment instead of passing silently.
  Link: ({ to, params, children, ...rest }: {
    to: string; params?: Record<string, string>; children?: React.ReactNode
  }) => (
    <a href={String(to).replace(/\$(\w+)/g, (_m, k: string) => params?.[k] ?? '')} {...rest}>
      {children}
    </a>
  ),
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
  // The default fixture is a fully-known listed row: real booleans, not
  // nulls, so a test that wants the "upstream told us nothing" case has to
  // ask for it explicitly rather than getting it by accident.
  popularity_synced_at: '2026-08-13T00:00:00', script_created: '2024-05-02T00:00:00',
  script_updated: '2026-06-11T00:00:00', has_arm: true, updateable: true,
  privileged: false, architectures: ['amd64', 'arm64'], port: 6379,
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

  it('links the title and a Read more to this row\'s detail route', () => {
    render(<StoreCard entry={REDIS} onInstall={vi.fn()} installed={false} />)
    const readMore = screen.getByRole('link', { name: 'Read more' })
    expect(readMore).toHaveAttribute('href', '/store/redis')
    // The name is the other way in, for anyone who reaches for the title
    // rather than the explicit link.
    expect(screen.getByRole('link', { name: 'Redis' })).toHaveAttribute('href', '/store/redis')
  })

  it('shows Read more even on a row with no description to read', () => {
    // The user chose this explicitly, for visual consistency, knowing it puts
    // the link on cards with nothing more to show. It is still defensible:
    // the detail page carries availability, resource defaults and popularity
    // for these rows even when upstream gave us no prose.
    const bare = { ...REDIS, slug: 'readarr', name: null, description: null,
      upstream_state: 'unlisted' as const }
    render(<StoreCard entry={bare} onInstall={vi.fn()} installed={false} />)
    expect(screen.getByRole('link', { name: 'Read more' })).toHaveAttribute('href', '/store/readarr')
  })

  it('nests no interactive element inside another', () => {
    // An <a> wrapping the Install <button> would be invalid HTML and would
    // break both keyboard and screen-reader behaviour, which is why the card
    // itself is not a link. Asserted structurally so a later "make the whole
    // card clickable" change has to deal with this test rather than silently
    // reintroducing the nesting.
    const { container } = render(
      <StoreCard entry={REDIS} onInstall={vi.fn()} installed={false} band="top10" />)
    const interactive = Array.from(container.querySelectorAll('a, button'))
    expect(interactive.length).toBeGreaterThan(2)
    for (const el of interactive) {
      expect(el.querySelector('a, button'), `${el.tagName} contains another control`).toBeNull()
    }
  })

  const BADGE_TOP = 'Top 10%'

  it('shows the gold star band only when the page says this row is in the top tier', () => {
    // The raw install count is gone from the card on purpose: 126196 against a
    // median of 1001 is a figure nobody can place. The band is a percentile,
    // and the percentile can only be computed against the whole corpus, so the
    // page resolves it and hands the card the answer.
    const { rerender } = render(
      <StoreCard entry={REDIS} onInstall={vi.fn()} installed={false} band="top10" />)
    expect(screen.getByText(BADGE_TOP)).toBeInTheDocument()
    // star_shine, written as a literal so scripts/icon-names.mjs can extract
    // it into the Google Fonts link; a Material Symbols glyph renders as its
    // own ligature text.
    expect(screen.getByText('star_shine')).toBeInTheDocument()

    rerender(<StoreCard entry={REDIS} onInstall={vi.fn()} installed={false} band={null} />)
    expect(screen.queryByText(BADGE_TOP)).toBeNull()
    expect(screen.queryByText('star_shine')).toBeNull()
  })

  it('never puts the raw popularity number on the card', () => {
    const popular = { ...REDIS, popularity: 126196 }
    render(<StoreCard entry={popular} onInstall={vi.fn()} installed={false} band="top10" />)
    expect(screen.queryByText(/126196/)).toBeNull()
    expect(screen.queryByText(/126,196/)).toBeNull()
    // and never this word, which is not what the number counts
    expect(document.body.textContent).not.toMatch(/downloads/i)
  })

  it('renders no band at all for a row with no popularity measurement', () => {
    const unmeasured = { ...REDIS, popularity: null }
    render(<StoreCard entry={unmeasured} onInstall={vi.fn()} installed={false}
                      band={popularityBand(null, 9186)} />)
    expect(screen.queryByText(BADGE_TOP)).toBeNull()
    expect(screen.queryByText('star_shine')).toBeNull()
  })

  it('chips only the rare, actionable side of each upstream boolean', () => {
    // has_arm is true on 87% of rows and updateable on 97%, so chipping those
    // would be furniture. The exceptions carry the information.
    const ordinary = { ...REDIS, privileged: false, has_arm: true, updateable: true }
    const { rerender } = render(
      <StoreCard entry={ordinary} onInstall={vi.fn()} installed={false} />)
    expect(screen.queryByText('Privileged')).toBeNull()
    expect(screen.queryByText('Unprivileged')).toBeNull()  // dropped deliberately
    expect(screen.queryByText('x86 only')).toBeNull()
    expect(screen.queryByText('No in-place update')).toBeNull()

    rerender(<StoreCard entry={{ ...REDIS, privileged: true, has_arm: false, updateable: false }}
                        onInstall={vi.fn()} installed={false} />)
    expect(screen.getByText('Privileged')).toBeInTheDocument()
    expect(screen.getByText('x86 only')).toBeInTheDocument()
    expect(screen.getByText('No in-place update')).toBeInTheDocument()
  })

  it('claims nothing about a row upstream has no record for', () => {
    // THE null case. All three booleans are null on the 9 unlisted rows, and
    // null means "we do not know", never "no". A falsiness check here would
    // label every one of them x86 only and un-updatable, which upstream has
    // not said and we cannot know.
    const unknown = { ...REDIS, upstream_state: 'unlisted' as const,
      privileged: null, has_arm: null, updateable: null }
    render(<StoreCard entry={unknown} onInstall={vi.fn()} installed={false} />)
    expect(screen.queryByText('x86 only')).toBeNull()
    expect(screen.queryByText('No in-place update')).toBeNull()
    expect(screen.queryByText('Privileged')).toBeNull()
    // the one thing we DO know about it still shows
    expect(screen.getByText('Not listed upstream')).toBeInTheDocument()
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

  it('has no search box of its own: text search is the global palette now', async () => {
    // The two tests that used to live here asserted client-side matching on
    // name and on description. That capability did not disappear, it moved
    // server-side to GET /search (name OR slug OR description) and is
    // asserted in command-palette.test.tsx, where the surface now is. What
    // survives here is the negative: this page must not grow a second,
    // narrower search that only filters the rows it happens to have fetched.
    const { useCatalog } = await import('../api/catalog')
    vi.mocked(useCatalog).mockReturnValue({
      data: [REDIS, { ...REDIS, slug: 'gitea', name: 'Gitea' }],
    } as any)
    withQuery(<StorePage />)

    expect(screen.queryByPlaceholderText(/search/i)).toBeNull()
    expect(screen.queryByRole('searchbox')).toBeNull()
    // and the grid is unfiltered, both rows still render
    expect(screen.getByText('Redis')).toBeInTheDocument()
    expect(screen.getByText('Gitea')).toBeInTheDocument()
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

/**
 * Pagination (shadcn/ui pagination + select, vendored into components/ui).
 * The store used to render every matching card into a virtualized scroller;
 * it now renders one page at a time, with page and page size carried in the
 * route's search params next to category and q.
 */
describe('Store pagination', () => {
  const manyEntries = (n: number): CatalogRow[] =>
    Array.from({ length: n }, (_, i) => ({
      ...REDIS, slug: `app-${i}`, name: `App ${String(i).padStart(3, '0')}`,
    }))

  const mockEntries = async (rows: CatalogRow[]) => {
    const { useCatalog } = await import('../api/catalog')
    vi.mocked(useCatalog).mockReturnValue({ data: rows } as any)
  }

  // Every fixture row is installable, so one Install button is exactly one
  // rendered card. Counting them counts the page.
  const cardCount = () => screen.getAllByRole('button', { name: 'Install' }).length

  beforeEach(() => { mockSearch = {} })

  it('renders only the default 25 of a larger result set', async () => {
    await mockEntries(manyEntries(30))
    withQuery(<StorePage />)
    expect(cardCount()).toBe(25)
    expect(screen.getByText('Showing 1 to 25 of 30')).toBeInTheDocument()
    expect(screen.getByText('Page 1 of 2')).toBeInTheDocument()
    // page 1 is the URL's default state, so it stays out of the URL
    expect(mockSearch.page).toBeUndefined()
  })

  it('pages forward and back, and lands on the right slice', async () => {
    await mockEntries(manyEntries(30))
    withQuery(<StorePage />)
    expect(screen.getByText('App 000')).toBeInTheDocument()
    expect(screen.queryByText('App 025')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /go to next page/i }))

    expect(cardCount()).toBe(5)  // the 30 - 25 remainder
    expect(screen.getByText('App 025')).toBeInTheDocument()
    expect(screen.queryByText('App 000')).not.toBeInTheDocument()
    expect(screen.getByText('Showing 26 to 30 of 30')).toBeInTheDocument()
    expect(mockSearch.page).toBe(2)

    fireEvent.click(screen.getByRole('button', { name: /go to previous page/i }))

    expect(screen.getByText('App 000')).toBeInTheDocument()
    expect(mockSearch.page).toBeUndefined()
  })

  it('disables Previous on the first page and Next on the last', async () => {
    // Disabled, not a link that silently does nothing: the ends have to be
    // announced as unavailable, not just fail to respond.
    await mockEntries(manyEntries(30))
    withQuery(<StorePage />)
    expect(screen.getByRole('button', { name: /go to previous page/i })).toBeDisabled()
    expect(screen.getByRole('button', { name: /go to next page/i })).toBeEnabled()

    fireEvent.click(screen.getByRole('button', { name: /go to next page/i }))

    expect(screen.getByRole('button', { name: /go to previous page/i })).toBeEnabled()
    expect(screen.getByRole('button', { name: /go to next page/i })).toBeDisabled()
  })

  it('needs no pagination controls at all for a single page', async () => {
    await mockEntries(manyEntries(3))
    withQuery(<StorePage />)
    expect(cardCount()).toBe(3)
    expect(screen.getByText('Showing 1 to 3 of 3')).toBeInTheDocument()
    expect(screen.getByText('Page 1 of 1')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /go to previous page/i })).toBeDisabled()
    expect(screen.getByRole('button', { name: /go to next page/i })).toBeDisabled()
  })

  it('honours a page size from the URL', async () => {
    await mockEntries(manyEntries(30))
    mockSearch = { pageSize: 15 }
    withQuery(<StorePage />)
    expect(cardCount()).toBe(15)
    expect(screen.getByText('Showing 1 to 15 of 30')).toBeInTheDocument()
    expect(screen.getByText('Page 1 of 2')).toBeInTheDocument()
  })

  it('changes page size through the Select and resets to page 1', async () => {
    await mockEntries(manyEntries(120))
    mockSearch = { page: 3 }
    withQuery(<StorePage />)
    expect(screen.getByText('Showing 51 to 75 of 120')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('combobox', { name: /apps per page/i }))
    fireEvent.click(await screen.findByRole('option', { name: '100' }))

    await waitFor(() => expect(mockSearch.pageSize).toBe(100))
    // Page 1 at the new density, not page 3 of a list that no longer has one.
    expect(mockSearch.page).toBeUndefined()
    expect(screen.getByText('Showing 1 to 100 of 120')).toBeInTheDocument()
    expect(cardCount()).toBe(100)
  })

  it('offers exactly the four sizes the store supports', async () => {
    await mockEntries(manyEntries(30))
    withQuery(<StorePage />)
    fireEvent.click(screen.getByRole('combobox', { name: /apps per page/i }))
    const options = (await screen.findAllByRole('option')).map((o) => o.textContent)
    expect(options).toEqual(['15', '25', '50', '100'])
  })

  // The search-text half of this pair went with the search box. The rule it
  // proved (a filter change drops you back to page 1, rather than stranding
  // you on a page number the narrowed result set no longer has) is the same
  // rule, and the category chip is the filter that still exists to prove it.
  it('drops back to page 1 when the category chip changes', async () => {
    const rows = [...manyEntries(30), { ...REDIS, slug: 'gitea', name: 'Gitea', category: 'Dev Tools' }]
    await mockEntries(rows)
    mockSearch = { page: 2 }
    withQuery(<StorePage />)

    fireEvent.click(screen.getByRole('button', { name: 'Dev Tools' }))

    expect(mockSearch.page).toBeUndefined()
    expect(screen.getByText('Gitea')).toBeInTheDocument()
    expect(screen.getByText('Showing 1 to 1 of 1')).toBeInTheDocument()
  })

  it('clamps a stale page from the URL to the last real page', async () => {
    // A deep link to ?page=12 that a catalog refresh has since invalidated
    // shows the last page rather than an empty grid.
    await mockEntries(manyEntries(30))
    mockSearch = { page: 12 }
    withQuery(<StorePage />)
    expect(screen.getByText('Page 2 of 2')).toBeInTheDocument()
    expect(cardCount()).toBe(5)
  })
})

/**
 * Sorting and the popularity band. The four sort keys mirror GET /catalog's
 * own allowlist, but the ordering itself is done client-side over the single
 * catalog fetch this page already holds (see lib/store-order.ts for why, and
 * store-order.test.ts for the NULLS LAST rule these rely on).
 */
describe('Store sort and popularity band', () => {
  const app = (slug: string, over: Partial<CatalogRow> = {}): CatalogRow =>
    ({ ...REDIS, slug, name: slug, ...over })

  const mockEntries = async (rows: CatalogRow[]) => {
    const { useCatalog } = await import('../api/catalog')
    vi.mocked(useCatalog).mockReturnValue({ data: rows } as any)
  }

  // Card titles in DOM order, which is the order the grid rendered them.
  // `.mt-2.font-semibold` is the name line specifically: the initials tile is
  // also font-semibold, so matching on that alone reads back "AD" instead of
  // "adguard".
  const shownOrder = () =>
    screen.getAllByRole('button', { name: 'Install' })
      .map((b) => b.closest('.rounded-card')?.querySelector('.mt-2.font-semibold')?.textContent)

  beforeEach(() => { mockSearch = {} })

  it('offers exactly the four sort options, name first', async () => {
    await mockEntries([app('a')])
    withQuery(<StorePage />)
    fireEvent.click(screen.getByRole('combobox', { name: /sort by/i }))
    const options = (await screen.findAllByRole('option')).map((o) => o.textContent)
    expect(options).toEqual(['Name (A to Z)', 'Most installed', 'Newest', 'Recently updated'])
  })

  it('defaults to name order and keeps the default out of the URL', async () => {
    await mockEntries([app('zabbix'), app('adguard'), app('plex')])
    withQuery(<StorePage />)
    expect(shownOrder()).toEqual(['adguard', 'plex', 'zabbix'])
    expect(mockSearch.sort).toBeUndefined()
  })

  it('reorders the grid by install count, and resets to page 1', async () => {
    // Page 7 of an alphabetical list is not page 7 of a popularity one, so
    // holding the page number across a sort change would land the operator
    // somewhere arbitrary.
    await mockEntries([app('quiet', { popularity: 4 }), app('docker', { popularity: 126196 }),
                       app('middling', { popularity: 1001 })])
    mockSearch = { page: 2 }
    withQuery(<StorePage />)

    fireEvent.click(screen.getByRole('combobox', { name: /sort by/i }))
    fireEvent.click(await screen.findByRole('option', { name: 'Most installed' }))

    await waitFor(() => expect(mockSearch.sort).toBe('popularity'))
    expect(mockSearch.page).toBeUndefined()
    expect(shownOrder()).toEqual(['docker', 'middling', 'quiet'])
  })

  it('puts rows with no measurement last, not first, when sorting by newest', async () => {
    // The page-level counterpart to store-order.test.ts's NULLS LAST test:
    // proves the rule survives the trip through filtering and paging.
    await mockEntries([
      app('unlisted-row', { script_created: null, popularity: null }),
      app('older', { script_created: '2024-05-02T00:00:00' }),
      app('newest', { script_created: '2026-08-13T00:00:00' }),
    ])
    mockSearch = { sort: 'newest' }
    withQuery(<StorePage />)
    expect(shownOrder()).toEqual(['newest', 'older', 'unlisted-row'])
  })

  it('falls back to name order for a sort key the allowlist does not have', async () => {
    // A hand-typed ?sort=toString used to reach the comparator as a real key
    // and throw, taking the page down with it.
    await mockEntries([app('zabbix'), app('adguard')])
    mockSearch = { sort: 'toString' }
    withQuery(<StorePage />)
    expect(shownOrder()).toEqual(['adguard', 'zabbix'])
  })

  it('bands the top tenth of the whole corpus, not of the current page', async () => {
    // 100 rows, 1..100 installs, page size 15. Only the top 10 clear the 90th
    // percentile, so page 1 of a popularity sort shows 10 bands and 5 without,
    // and the threshold does not shift when the page does.
    const rows = Array.from({ length: 100 }, (_, i) =>
      app(`s${String(i).padStart(3, '0')}`, { popularity: i + 1 }))
    await mockEntries(rows)
    mockSearch = { sort: 'popularity', pageSize: 15 }
    withQuery(<StorePage />)

    expect(screen.getAllByText('Top 10%')).toHaveLength(10)
    expect(screen.getAllByText('star_shine')).toHaveLength(10)
  })

  it('shows no band anywhere when nothing has been measured', async () => {
    await mockEntries([app('a', { popularity: null }), app('b', { popularity: null })])
    withQuery(<StorePage />)
    expect(screen.queryByText('Top 10%')).toBeNull()
    expect(screen.queryByText('star_shine')).toBeNull()
  })
})

describe('Store grid sizing', () => {
  const mockEntries = async (rows: CatalogRow[]) => {
    const { useCatalog } = await import('../api/catalog')
    vi.mocked(useCatalog).mockReturnValue({ data: rows } as any)
  }

  beforeEach(() => { mockSearch = {} })

  it('sizes columns with one auto-fill rule rather than hand-written breakpoints', async () => {
    // The column count has to follow the lane, so a 4K monitor fills the row
    // instead of stopping at whatever the largest breakpoint said. Asserted on
    // the rule itself because jsdom has no layout engine and cannot report a
    // real column count.
    await mockEntries([{ ...REDIS, slug: 'a', name: 'A' }])
    const { container } = withQuery(<StorePage />)
    const grid = container.querySelector('.grid')
    expect(grid?.className).toContain('grid-cols-[repeat(auto-fill,minmax(min(360px,100%),1fr))]')
    // the fixed-breakpoint ladder this replaced must not come back
    expect(grid?.className).not.toMatch(/sm:grid-cols-|xl:grid-cols-|grid-cols-1\b/)
  })

  it('gives every card the same fixed height', async () => {
    // The whole point: a 10-line description next to a 2-line one used to
    // leave a hole in the grid.
    await mockEntries([
      { ...REDIS, slug: 'short', name: 'Short', description: 'Tiny.' },
      { ...REDIS, slug: 'long', name: 'Long', description: 'x '.repeat(400) },
      { ...REDIS, slug: 'none', name: 'None', description: null },
    ])
    const { container } = withQuery(<StorePage />)
    const cards = Array.from(container.querySelectorAll('.rounded-card'))
    expect(cards).toHaveLength(3)
    for (const card of cards) expect(card.className).toContain('h-[284px]')
  })

  it('clamps the description and fades it from the card background token', async () => {
    // A gradient hardcoded to one background smears in the other theme; the
    // token flips with [data-theme]. Over a short or missing description this
    // is panel-on-panel, i.e. invisible, which is why it needs no condition.
    await mockEntries([{ ...REDIS, slug: 'a', name: 'A', description: 'y '.repeat(400) }])
    const { container } = withQuery(<StorePage />)
    expect(container.querySelector('.line-clamp-3')).not.toBeNull()
    const fade = container.querySelector('[class*="linear-gradient(to_top,var(--panel)"]')
    expect(fade).not.toBeNull()
    expect(fade?.getAttribute('class')).toContain('pointer-events-none')
  })
})
