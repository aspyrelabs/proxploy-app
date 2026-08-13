import { useQuery } from '@tanstack/react-query'
import { createRoute, useNavigate, useSearch } from '@tanstack/react-router'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useCatalog, useCatalogStatus, useRefreshCatalog } from '../api/catalog'
import type { CatalogRow } from '../api/catalog'
import { api } from '../api/client'
import { useEntitlements } from '../api/hooks'
import type { AppRow } from '../api/hooks'
import { TERMINAL, useJob } from '../api/jobs'
import { InstallDialog } from '../components/InstallDialog'
import { StoreCard } from '../components/StoreCard'
import { QueryState } from '../components/QueryState'
import { Button } from '../components/ui/button'
import { Field, FieldLabel } from '@/components/ui/field'
import {
  Pagination, PaginationContent, PaginationItem, PaginationNext, PaginationPrevious,
} from '@/components/ui/pagination'
import {
  Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { Progress, ProgressLabel, ProgressValue } from '../components/ui/progress'
import { fmtUptime } from '../lib/format'
import { shellRoute } from './shell'

const inputCls = 'rounded-ctl border border-line bg-panel px-3 py-1.5 text-[13px] text-text placeholder:text-text-3 focus:outline-none focus:ring-1 focus:ring-amber'

// The page sizes offered, and the one a fresh visit gets. DEFAULT_PAGE_SIZE
// is deliberately absent from the URL when it is in force (see the route's
// validateSearch), so the common case keeps a clean /store link.
const PAGE_SIZES = [15, 25, 50, 100] as const
const DEFAULT_PAGE_SIZE = 25

/** The router's own parse yields a number, a hand-typed URL yields a string,
 *  and anything else is not a number at all. */
function toNumber(v: unknown): number {
  return typeof v === 'number' ? v : typeof v === 'string' ? Number(v) : NaN
}

/** Page 1 is the default, so it is represented by absence, not by "?page=1". */
function toPage(v: unknown): number | undefined {
  const n = toNumber(v)
  return Number.isInteger(n) && n > 1 ? n : undefined
}

/** Only a size actually on the menu survives, and the default is absence
 *  again, so an invented "?pageSize=7" falls back rather than being honoured. */
function toPageSize(v: unknown): number | undefined {
  const n = toNumber(v)
  return n !== DEFAULT_PAGE_SIZE && (PAGE_SIZES as readonly number[]).includes(n)
    ? n : undefined
}

// One page of cards, in the plain responsive grid the virtualizer used to
// emulate by hand. The virtualizer earned its keep when this rendered all
// ~557 LXC entries at once; a page is at most 100 cards, so the DOM cost is
// bounded by the page size and the measurement plumbing is just overhead.
function StoreGrid({ entries, installedSlugs, onInstall }: {
  entries: CatalogRow[]; installedSlugs: Set<string>; onInstall: (slug: string) => void
}) {
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
      {entries.map((e) => (
        <StoreCard key={e.slug} entry={e} installed={installedSlugs.has(e.slug)}
          onInstall={onInstall} />
      ))}
    </div>
  )
}

export function StorePage() {
  const search = useSearch({ strict: false }) as
    { category?: string; q?: string; page?: number; pageSize?: number }
  const navigate = useNavigate()
  const [installing, setInstalling] = useState<string | null>(null)
  const gridTop = useRef<HTMLDivElement>(null)
  // The Store is LXC-only (catalog expansion plan: non-LXC entries stay in
  // the catalog table, tagged by type, and never render here), so this
  // fetches the whole ct/ catalog once; category/search are then instant,
  // client-side filters over that one list, driving the search+chip
  // navigation the virtualized grid needs (decision 5).
  const catalogQuery = useCatalog(undefined, undefined, 'ct')
  const entries = catalogQuery.data
  const refresh = useRefreshCatalog()
  const status = useCatalogStatus()
  const ent = useEntitlements()
  // has() reads false until the first entitlements fetch resolves; gating on
  // !has() alone would grey the button out for every plan during load (same
  // guard AttachmentMap uses in routes/network.tsx).
  const refreshDenied = ent.data != null && !ent.has('store.refresh')
  // POST /catalog/refresh only ENQUEUES the job, so the mutation's isPending
  // covers the enqueue and nothing else. The work itself is the job, followed
  // here through useJob: its ['jobs', id] cache entry is patched live by the
  // one SSE stream the app already has (api/live.ts::applyJob), which carries
  // a delta for every ctx.progress() the handler emits.
  const [refreshJobId, setRefreshJobId] = useState<number | null>(null)
  const refreshJob = useJob(refreshJobId)
  const refreshJobStatus = refreshJob.data?.status
  useEffect(() => {
    // Terminal is terminal, succeeded or failed alike: let go of the job so
    // the bar disappears instead of parking forever at whatever percentage
    // the run died on. A job row we cannot read at all is treated the same.
    if ((refreshJobStatus && TERMINAL.includes(refreshJobStatus)) || refreshJob.isError) {
      setRefreshJobId(null)
    }
  }, [refreshJobStatus, refreshJob.isError])
  // Both Refresh buttons drive this one job, so neither can start a second
  // one while the first is still running, and there is only ever one bar.
  const refreshBusy = refresh.isPending || refreshJobId != null
  // No bar for a refresh the plan does not include: that POST is going to
  // 403 and there will be no job behind it to report on.
  const showRefreshBar = refreshBusy && !refreshDenied
  const startRefresh = () => {
    if (refreshBusy) return
    refresh.mutate(undefined, { onSuccess: (r) => setRefreshJobId(r.job.id) })
  }
  // Same query key as cluster.tsx's unfiltered /apps fetch, so this shares one
  // cache entry rather than adding a second request. Drives the real
  // `installed` prop below, it used to be hardcoded false, which made
  // StoreCard's tested "Installed" disabled state unreachable in the real page.
  const { data: apps } = useQuery({
    queryKey: ['apps', {}],
    queryFn: () => api<AppRow[]>('/apps'),
  })
  const installedSlugs = new Set(
    (apps ?? []).map((a) => a.catalog_slug).filter((s): s is string => s != null))

  const installableCount = (entries ?? []).filter((e) => e.installable === true).length
  const unsupportedCount = (entries ?? []).filter((e) => e.installable === false).length
  const pendingCount = (entries ?? []).filter((e) => e.installable === null).length

  const categories = useMemo(() => {
    const set = new Set((entries ?? []).map((e) => e.category ?? 'Uncategorized'))
    return ['All', ...Array.from(set).sort()]
  }, [entries])

  const filtered = useMemo(() => {
    let rows = entries ?? []
    if (search.category && search.category !== 'All') {
      rows = rows.filter((e) => (e.category ?? 'Uncategorized') === search.category)
    }
    if (search.q) {
      const needle = search.q.toLowerCase()
      // Description is part of the haystack now that upstream metadata
      // actually fills it: searching "media server" should find Plex rather
      // than nothing. Slug stays in it because the ct rows with no upstream
      // match have nothing but a name and a slug to be found by.
      rows = rows.filter((e) =>
        (e.name ?? e.slug).toLowerCase().includes(needle)
        || e.slug.toLowerCase().includes(needle)
        || (e.description ?? '').toLowerCase().includes(needle))
    }
    return rows
  }, [entries, search.category, search.q])

  const setSearch = (patch: Partial<typeof search>) =>
    navigate({ to: '/store' as never, search: { ...search, ...patch } as never, replace: true })

  // Page and page size live in the route's search params, next to category and
  // q, so a reload, a bookmark and the back button all land on the page the
  // operator was actually looking at. They are already navigating this page by
  // URL for category and search; paging is the same kind of state and it would
  // be odd for it to be the one thing that evaporates on refresh.
  const pageSize = search.pageSize ?? DEFAULT_PAGE_SIZE
  const pageCount = Math.max(1, Math.ceil(filtered.length / pageSize))
  // Clamped rather than corrected in place. A hand-edited or stale ?page= (a
  // refresh can shrink the catalog under a deep link) shows the last real page
  // instead of an empty grid, and the next Prev/Next click writes an honest
  // number back. An effect that renavigated here would be one more thing that
  // can loop with the user's own navigation.
  const page = Math.min(Math.max(1, search.page ?? 1), pageCount)
  const firstIndex = (page - 1) * pageSize
  const pageEntries = filtered.slice(firstIndex, firstIndex + pageSize)

  const goToPage = (next: number) => {
    setSearch({ page: next <= 1 ? undefined : next })
    // Page 2 should start at the top of the grid, not wherever the click
    // happened to leave the viewport. Optional call: jsdom has no
    // scrollIntoView, and this is presentation, not behaviour.
    gridTop.current?.scrollIntoView?.({ block: 'start' })
  }

  // Changing the page size resets to page 1 rather than trying to keep the
  // first visible card in view. Picked for predictability: "show me 100" is a
  // request to see the top of the list at a new density, and preserving a
  // scroll offset across a re-paginate is guesswork the user cannot check.
  const setPageSize = (next: number) =>
    setSearch({ pageSize: next === DEFAULT_PAGE_SIZE ? undefined : next, page: undefined })

  // Every filter change drops back to page 1. Without this, narrowing a
  // 23-page result set to a 2-page one while sitting on page 12 renders an
  // empty grid that looks like "no results" and is really "no page 12".
  const setFilter = (patch: Partial<typeof search>) => setSearch({ ...patch, page: undefined })

  const rangeStart = filtered.length === 0 ? 0 : firstIndex + 1
  const rangeEnd = firstIndex + pageEntries.length

  return (
    <div>
      <div className="relative mb-5 flex items-center justify-between">
        <div>
          <h1 className="font-display text-[22px] font-semibold">App Store</h1>
          <div className="text-[12px] text-text-3">
            Sourced from community-scripts/ProxmoxVE · {installableCount} of{' '}
            {entries?.length ?? 0} scripts installable ({unsupportedCount} unsupported
            {pendingCount > 0 ? `, ${pendingCount} checking` : ''})
          </div>
        </div>
        <Button variant="ghost" onClick={startRefresh} disabled={refreshBusy}>
          Refresh
        </Button>
        {/* Absolutely positioned, so it is out of flow and appearing or
            vanishing cannot move the header, the banner or the grid by a
            pixel. Anchored under the button that started it, with its own
            opaque panel background because it floats over whatever status
            line happens to be underneath.

            services/catalog.py::refresh_catalog reports four values and no
            others: 45 once discovery has returned, 85 once the upstream
            metadata sync has (on its failure path too, so a source that is
            down cannot strand the bar), 95 after mark_updates_available, and
            100 at the end. So this jumps in four steps rather than sweeping,
            and sits indeterminate for the couple of seconds before the first
            one lands. That is honest: the job publishes nothing in between,
            and inventing motion to fill the gap would be a lie about
            progress. Nothing here hardcodes those numbers; they are simply
            what the bar will be handed. */}
        {showRefreshBar && (
          <Progress
            value={refreshJob.data?.progress_pct}
            className="absolute right-0 top-full z-10 w-60 rounded-ctl border border-line-soft bg-panel px-2.5 pb-2 pt-1.5"
          >
            <ProgressLabel>Refreshing the catalog</ProgressLabel>
            <ProgressValue />
          </Progress>
        )}
      </div>

      {status.data?.stale && (
        <p role="alert"
           className="mb-4 rounded-ctl border border-amber/30 bg-amber-dim p-2 text-[12.5px] text-text-2">
          <span className="text-amber">
            {status.data.synced_at == null
              ? 'The app catalog has never synced.'
              : `The app catalog has not synced in ${fmtUptime(status.data.age_s)}.`}
          </span>{' '}
          Installable apps and their default sizing may be out of date.{' '}
          <Button variant="ghost" className="ml-1 px-2 py-1 text-[11px]"
                  disabled={refreshBusy || refreshDenied}
                  title={refreshDenied ? 'Not included in your plan' : undefined}
                  onClick={startRefresh}>
            Refresh
          </Button>
        </p>
      )}
      {status.data && !status.data.stale && (
        <div className="mb-3 text-[11px] text-text-3">
          {status.data.age_s != null && status.data.age_s < 60
            ? 'Catalog synced just now.'
            : `Catalog synced ${fmtUptime(status.data.age_s)} ago.`}
        </div>
      )}

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <input
          className={inputCls}
          placeholder="Search the store…"
          defaultValue={search.q ?? ''}
          onChange={(e) => setFilter({ q: e.target.value || undefined })}
        />
        <div className="flex flex-wrap gap-2">
          {categories.map((c) => (
            <button
              key={c}
              className={`rounded-full px-3 py-1 text-[12px] ${
                (search.category ?? 'All') === c ? 'bg-elev text-text' : 'text-text-2 hover:bg-panel-2'}`}
              onClick={() => setFilter({ category: c === 'All' ? undefined : c })}
            >
              {c}
            </button>
          ))}
        </div>
      </div>

      <div ref={gridTop} />

      <QueryState query={catalogQuery}
                  empty={() => filtered.length === 0}
                  emptyTitle="No store entries match your filter."
                  emptyNote=""
                  errorTitle="Store catalog not readable"
                  errorNote="Proxploy could not reach the backend to list the app catalog.">
        {() => (
          <>
            <StoreGrid entries={pageEntries} installedSlugs={installedSlugs}
                      onInstall={(slug) => setInstalling(slug)} />

            <div className="mt-5 flex flex-wrap items-center justify-between gap-4">
              <Field orientation="horizontal" className="w-fit">
                <FieldLabel htmlFor="select-rows-per-page" className="text-[12px] text-text-2">
                  Apps per page
                </FieldLabel>
                <Select value={String(pageSize)} onValueChange={(v) => setPageSize(Number(v))}>
                  <SelectTrigger className="w-20" id="select-rows-per-page" size="sm">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent align="start">
                    <SelectGroup>
                      {PAGE_SIZES.map((n) => (
                        <SelectItem key={n} value={String(n)}>{n}</SelectItem>
                      ))}
                    </SelectGroup>
                  </SelectContent>
                </Select>
              </Field>

              <div className="flex flex-wrap items-center gap-3">
                {/* Prev/Next alone say nothing about where you are in 557
                    apps, so the position is spelled out rather than implied. */}
                <span className="font-mono text-[11px] text-text-3">
                  Showing {rangeStart} to {rangeEnd} of {filtered.length}
                </span>
                <Pagination className="mx-0 w-auto">
                  <PaginationContent>
                    <PaginationItem>
                      {/* Genuinely disabled at the ends, not a link that
                          quietly does nothing. */}
                      <PaginationPrevious disabled={page <= 1}
                                          onClick={() => goToPage(page - 1)} />
                    </PaginationItem>
                    <PaginationItem>
                      <span className="px-2 text-[12px] text-text-2">
                        Page {page} of {pageCount}
                      </span>
                    </PaginationItem>
                    <PaginationItem>
                      <PaginationNext disabled={page >= pageCount}
                                      onClick={() => goToPage(page + 1)} />
                    </PaginationItem>
                  </PaginationContent>
                </Pagination>
              </div>
            </div>
          </>
        )}
      </QueryState>

      {installing && (
        <InstallDialog slug={installing} onClose={() => setInstalling(null)} />
      )}
    </div>
  )
}

export const storeRoute = createRoute({
  getParentRoute: () => shellRoute,
  path: '/store',
  validateSearch: (s: Record<string, unknown>) => ({
    category: typeof s.category === 'string' ? s.category : undefined,
    q: typeof s.q === 'string' && s.q ? s.q : undefined,
    // Both default states are represented by their ABSENCE from the URL, so
    // /store stays clean until the operator actually pages or changes the
    // density. A page number arrives as a number from the router's own parse
    // but as a string from a hand-typed URL, so both are accepted; anything
    // else, including page 1 and the default size, normalises to undefined.
    page: toPage(s.page),
    pageSize: toPageSize(s.pageSize),
  }),
  component: StorePage,
})
