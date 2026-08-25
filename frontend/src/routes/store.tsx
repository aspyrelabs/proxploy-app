import { useQuery } from '@tanstack/react-query'
import { createRoute, useNavigate, useSearch } from '@tanstack/react-router'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useCatalog, useCatalogEntry, useCatalogStatus, useRefreshCatalog } from '../api/catalog'
import type { CatalogRow } from '../api/catalog'
import { api } from '../api/client'
import { useEntitlements } from '../api/hooks'
import type { AppRow } from '../api/hooks'
import { TERMINAL, useJob } from '../api/jobs'
import { InstallDialog } from '../components/InstallDialog'
import { InstallAction, StoreDetailContent } from '../components/StoreDetailContent'
import { StoreCard, StoreCardSkeleton } from '../components/StoreCard'
import { QueryState } from '../components/QueryState'
import { Skeleton, SkeletonGroup, SkeletonLine } from '../components/ui/skeleton'
import { Button, segment } from '../components/ui/button'
import { Dialog } from '../components/ui/dialog'
import { Field, FieldLabel } from '@/components/ui/field'
import {
  Pagination, PaginationContent, PaginationItem, PaginationNext, PaginationPrevious,
} from '@/components/ui/pagination'
import {
  Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { Progress, ProgressLabel, ProgressValue } from '../components/ui/progress'
import { fmtUptime } from '../lib/format'
import {
  DEFAULT_SORT, STORE_SORTS, isStoreSort, sortEntries,
} from '../lib/store-order'
import type { StoreSort } from '../lib/store-order'
import { shellRoute } from './shell'

// The page sizes offered, and the one a fresh visit gets. DEFAULT_PAGE_SIZE
// is deliberately absent from the URL when it is in force (see the route's
// validateSearch), so the common case keeps a clean /store link.
const PAGE_SIZES = [15, 25, 50, 100] as const
const DEFAULT_PAGE_SIZE = 25

/** The popup's title. Read off the list the grid already has rather than
 *  waiting on the detail fetch, so the dialog has a name from the moment it
 *  opens instead of flashing the slug and then correcting itself. */
function entryName(entries: CatalogRow[] | undefined, slug: string): string {
  return entries?.find((e) => e.slug === slug)?.name ?? slug
}

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
// ~556 LXC entries at once; a page is at most 100 cards, so the DOM cost is
// bounded by the page size and the measurement plumbing is just overhead.
// The auto-fill rule is derived at length inside StoreGrid below. It lives out
// here because the loading placeholder must lay out in the same grid, and a
// second copy of that string would be free to drift from the reasoning.
const STORE_GRID = 'grid grid-cols-[repeat(auto-fill,minmax(min(360px,100%),1fr))] gap-4'

function StoreGrid({ entries, installCounts, onInstall, onOpenDetail }: {
  entries: CatalogRow[]; installCounts: Map<string, number>; onInstall: (slug: string) => void
  onOpenDetail: (slug: string) => void
}) {
  /**
   * ONE auto-fill rule, no hand-written breakpoints, anchored so a 1080p
   * monitor shows exactly 4 columns.
   *
   * The arithmetic, so the next person can re-derive it rather than guess.
   * The grid does NOT get the viewport: AppShell.tsx renders
   * `<main className="min-w-0 flex-1 p-6">` beside a `w-[236px]` sidebar
   * (SidebarNav.tsx), so at a 1920px viewport the real lane is
   * 1920 - 236 - 48 = 1636px. With `gap-4` (16px), auto-fill gives
   * floor((lane + gap) / (min + gap)) columns, so 4 columns needs
   *     (1636+16)/5 < min+16 <= (1636+16)/4
   *     314px < min <= 397px
   * 360px sits mid-range rather than on either edge, which is what keeps
   * the answer at 4 when the lane moves: with the sidebar collapsed to
   * w-16 the lane is 1808px and it is still 4 (1824/376 = 4.85), and a
   * 15px classic scrollbar does not change it either.
   *
   * `min(360px, 100%)` rather than a bare 360px is the phone case: below
   * 360px of lane a bare minimum would make the track wider than its own
   * container and overflow the page. This caps the track at the container
   * and yields the one sensible column.
   *
   * auto-fill, not auto-fit: with auto-fit the empty tracks collapse, so a
   * filtered result of two apps would stretch into two enormous cards,
   * which is the opposite of the fixed-size cards this is here to give.
   */
  return (
    <div className={STORE_GRID}>
      {entries.map((e) => (
        <StoreCard key={e.slug} entry={e} installCount={installCounts.get(e.slug) ?? 0}
          onOpenDetail={onOpenDetail} onInstall={onInstall} />
      ))}
    </div>
  )
}

export function StorePage() {
  const search = useSearch({ strict: false }) as
    { category?: string; page?: number; pageSize?: number; sort?: StoreSort }
  const navigate = useNavigate()
  const [installing, setInstalling] = useState<string | null>(null)
  // The detail popup. Same shape as `installing` above, and deliberately
  // never open at the same time: see the handoff in the Dialog below.
  const [detailSlug, setDetailSlug] = useState<string | null>(null)
  // The SAME query StoreDetailContent runs, by the same key, so this shares
  // one cache entry and fires no second request. Reading it here rather than
  // reusing the grid row matters: opening a card is one of the two moments the
  // backend classifies a ct entry, so the grid's `installable` can still be
  // null while the detail's is true. The pinned action has to agree with the
  // Availability section it sits above.
  const detailEntry = useCatalogEntry(detailSlug)
  const gridTop = useRef<HTMLDivElement>(null)
  // The Store is LXC-only (catalog expansion plan: non-LXC entries stay in
  // the catalog table, tagged by type, and never render here), so this
  // fetches the whole ct/ catalog once; the category chips are then an
  // instant, client-side filter over that one list, and paging slices it.
  // Text search is not here at all any more: it is the global palette's job.
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
  // A COUNT per catalog entry, not a set of "has one". Installing a second
  // copy is ordinary (a test one beside a prod one, or an operator's own
  // naming scheme), so the card reports how many exist rather than hiding the
  // Install button once one does. Keyed on catalog_slug: App.slug is the
  // synthetic {catalog_slug}-{host_id}-{ctid} install identity, so counting on
  // that would count every row exactly once and tell nobody anything.
  const installCounts = new Map<string, number>()
  for (const a of apps ?? []) {
    if (a.catalog_slug) installCounts.set(a.catalog_slug, (installCounts.get(a.catalog_slug) ?? 0) + 1)
  }

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
    return rows
  }, [entries, search.category])

  const sort = search.sort ?? DEFAULT_SORT
  // Sorted after filtering (cheaper, same answer) and before paging, so a page
  // is a slice of the order the operator asked for rather than of the fetch
  // order. NULLS LAST lives in sortEntries; see lib/store-order.ts for why
  // this is client-side at all.
  const ordered = useMemo(() => sortEntries(filtered, sort), [filtered, sort])

  const setSearch = (patch: Partial<typeof search>) =>
    navigate({ to: '/store' as never, search: { ...search, ...patch } as never, replace: true })

  // Page and page size live in the route's search params, next to category,
  // so a reload, a bookmark and the back button all land on the page the
  // operator was actually looking at. They are already navigating this page by
  // URL for the category chip; paging is the same kind of state and it would
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
  const pageEntries = ordered.slice(firstIndex, firstIndex + pageSize)

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
          {/* The counts are all derived from `entries ?? []`, so before the
              catalog lands this line read "0 of 0 scripts installable (0
              unsupported)" directly above a grid of eight card placeholders:
              the page saying "there is nothing here" and "something is coming"
              at the same time. The source attribution is not waiting on
              anything and stays. */}
          <div className="text-[12px] text-text-3">
            {catalogQuery.isPending ? (
              <SkeletonGroup label="Loading the catalog summary">
                <SkeletonLine className="w-96 max-w-full text-[12px]" />
              </SkeletonGroup>
            ) : catalogQuery.isError ? (
              // isPending is false in the error state, so these counts used to
              // render from `entries ?? []` and state "0 of 0 scripts
              // installable" as fact, directly above a grid correctly saying
              // the catalog could not be read. The attribution is not waiting
              // on anything and stays.
              <>Sourced from community-scripts/ProxmoxVE</>
            ) : (
              <>
                Sourced from community-scripts/ProxmoxVE · {installableCount} of{' '}
                {entries?.length ?? 0} scripts installable ({unsupportedCount} unsupported
                {pendingCount > 0 ? `, ${pendingCount} checking` : ''})
              </>
            )}
          </div>
        </div>
        {/* Same refreshDenied guard as the banner's Refresh below. Without
            it this button 403'd in silence: useRefreshCatalog has no onError,
            and showRefreshBar is deliberately false for a denied refresh, so
            nothing on screen changed however many times it was clicked. */}
        <Button variant="ghost" onClick={startRefresh}
                disabled={refreshBusy || refreshDenied}
                title={refreshDenied ? 'Not included in your plan' : undefined}>
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
          <Button size="sm" variant="ghost" className="ml-1"
                  disabled={refreshBusy || refreshDenied}
                  title={refreshDenied ? 'Not included in your plan' : undefined}
                  onClick={startRefresh}>
            Refresh
          </Button>
        </p>
      )}
      {/* Held open while /catalog/status answers. This line is only one 11px
          row, but it sits directly above the chip block and the grid, so its
          arrival pushed the whole page down a moment after it had settled.
          The stale banner above is not held open the same way: it is an
          exception that usually does not appear, and reserving room for
          something that probably is not coming is its own kind of jump. */}
      {status.isPending && (
        <SkeletonGroup label="Checking when the catalog last synced" className="mb-3">
          <SkeletonLine className="w-44 text-[11px]" />
        </SkeletonGroup>
      )}
      {status.data && !status.data.stale && (
        <div className="mb-3 text-[11px] text-text-3">
          {status.data.age_s != null && status.data.age_s < 60
            ? 'Catalog synced just now.'
            : `Catalog synced ${fmtUptime(status.data.age_s)} ago.`}
        </div>
      )}

      {/* No search box here any more. Text search over the store lives in the
          one global palette (Ctrl+K), which searches name, slug AND
          description server-side (backend/proxploy/api/search.py) rather than
          filtering the page's own already-fetched rows, and which reaches a
          store-only plan too. The category chips stay: they are a browse
          affordance over a fixed vocabulary, not a search. */}
      {/* Two stacked rows, not one flex row: the categories are the real
          upstream vocabulary of 26, several of them long, so the chip block
          wraps to three or four lines at most widths. Sort therefore has to
          be a BLOCK BELOW that block rather than a flex sibling of it, which
          is the only way it lands under the last wrapped line instead of
          floating beside the first. */}
      <div className="mb-4">
        {/* `categories` is ['All'] until the catalog lands and 27 chips after
            it, which is three or four wrapped lines appearing at once and
            shoving the grid down. Eight is a deliberate under-estimate: the
            chips wrap, so a short placeholder settles UP into the real row
            rather than leaving a gap, and reserving all 27 would over-claim a
            vocabulary this page does not know yet. */}
        {catalogQuery.isPending ? (
          <SkeletonGroup label="Loading categories" className="flex flex-wrap gap-2">
            {/* Keyed by index, not by `w`: the list repeats widths (w-20 and
                w-16 appear twice), so the class string is not unique. It is a
                fixed-length placeholder that never reorders, which is exactly
                the case an index key is correct for. */}
            {['w-10', 'w-20', 'w-16', 'w-24', 'w-14', 'w-20', 'w-16', 'w-28'].map((w, i) => (
              <Skeleton key={i} className={`h-[26.5px] rounded-full ${w}`} />
            ))}
          </SkeletonGroup>
        ) : catalogQuery.isError ? null : (
        <div className="flex flex-wrap gap-2">
          {categories.map((c) => (
            <button
              key={c}
              className={`rounded-full px-3 py-1 text-[12px] ${segment((search.category ?? 'All') === c)}`}
              onClick={() => setFilter({ category: c === 'All' ? undefined : c })}
            >
              {c}
            </button>
          ))}
        </div>
        )}
        {/* Right-aligned to the content lane, which is the same right edge the
            grid below uses, so the two line up. flex-wrap so a narrow viewport
            drops it to its own line rather than squeezing or overflowing.
            Changing the order resets to page 1 for the same reason a filter
            change does: page 7 of an alphabetical list is not page 7 of a
            popularity one, and holding the number would land the operator
            somewhere arbitrary. */}
        <div className="mt-3 flex flex-wrap justify-end">
          <Field orientation="horizontal" className="w-fit">
            <FieldLabel htmlFor="select-store-sort" className="text-[12px] text-text-2">
              Sort by
            </FieldLabel>
            <Select value={sort}
                    onValueChange={(v) => setFilter({ sort: isStoreSort(v) ? v : undefined })}>
              <SelectTrigger className="w-44" id="select-store-sort" size="sm">
                <SelectValue />
              </SelectTrigger>
              <SelectContent align="end">
                <SelectGroup>
                  {(Object.keys(STORE_SORTS) as StoreSort[]).map((k) => (
                    <SelectItem key={k} value={k}>{STORE_SORTS[k]}</SelectItem>
                  ))}
                </SelectGroup>
              </SelectContent>
            </Select>
          </Field>
        </div>
      </div>

      <div ref={gridTop} />

      <QueryState query={catalogQuery}
                  loading={<SkeletonGroup label="Loading the app catalog" className={STORE_GRID}>
                    {Array.from({ length: 8 }, (_, i) => <StoreCardSkeleton key={i} />)}
                  </SkeletonGroup>}
                  empty={() => filtered.length === 0}
                  emptyTitle="No store entries match your filter."
                  emptyNote=""
                  errorTitle="Store catalog not readable"
                  errorNote="Proxploy could not reach the backend to list the app catalog.">
        {() => (
          <>
            <StoreGrid entries={pageEntries} installCounts={installCounts}
                      onOpenDetail={(slug) => setDetailSlug(slug)}
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
                {/* Prev/Next alone say nothing about where you are in 556
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

      {/* "Read more" opens the detail content HERE, in a dialog, rather than
          navigating. The same component backs routes/store-detail.tsx, so a
          palette result or a pasted /store/<slug> link still renders the page
          and the two can never drift apart.

          Install inside the popup CLOSES the popup and then opens
          InstallDialog. Sequential, never nested: InstallDialog is itself a
          Dialog, so stacking them would mount two overlays with two focus
          traps, and would put two buttons named "Install" on screen at once,
          which e2e/journey.spec.ts explicitly scopes around. Exactly one
          dialog is mounted at any moment.

          936 is 720 + 30%. The shared 92vw cap still applies and starts biting
          below a ~1017px viewport (936 / 0.92), so this is a desktop width
          that narrows on its own rather than a fixed one that would overhang a
          phone. scrollBody caps the height at 70vh and scrolls the body only:
          this content is the whole detail page, which is taller than the
          screen, and an uncapped panel could not be centred at all because
          there was no free space left to centre it in. */}
      {detailSlug && (
        <Dialog title={entryName(entries, detailSlug)} width={936} scrollBody
                onClose={() => setDetailSlug(null)}
                headerRight={detailEntry.data && (
                  <InstallAction entry={detailEntry.data}
                    installCount={installCounts.get(detailEntry.data.slug) ?? 0}
                    onInstall={(slug) => { setDetailSlug(null); setInstalling(slug) }} />
                )}>
          {/* showHeaderAction={false}: the action is pinned in the dialog's
              title row above, which is outside the scroll body, so it stays
              visible however far down the body is scrolled. The content's own
              header would scroll away with everything else. */}
          <StoreDetailContent slug={detailSlug} showHeaderAction={false}
            onInstall={(slug) => {
              setDetailSlug(null)
              setInstalling(slug)
            }} />
        </Dialog>
      )}

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
    // Both default states are represented by their ABSENCE from the URL, so
    // /store stays clean until the operator actually pages or changes the
    // density. A page number arrives as a number from the router's own parse
    // but as a string from a hand-typed URL, so both are accepted; anything
    // else, including page 1 and the default size, normalises to undefined.
    page: toPage(s.page),
    pageSize: toPageSize(s.pageSize),
    // Same four keys the server's own `sort` allowlist accepts, and the
    // default is absence again. Anything else falls back to name rather than
    // being carried around as a value nothing can honour, which is also what
    // GET /catalog does with a bad sort.
    sort: isStoreSort(s.sort) && s.sort !== DEFAULT_SORT ? s.sort : undefined,
  }),
  component: StorePage,
})
