import { useVirtualizer } from '@tanstack/react-virtual'
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
import { Progress, ProgressLabel, ProgressValue } from '../components/ui/progress'
import { fmtUptime } from '../lib/format'
import { shellRoute } from './shell'

const inputCls = 'rounded-ctl border border-line bg-panel px-3 py-1.5 text-[13px] text-text placeholder:text-text-3 focus:outline-none focus:ring-1 focus:ring-amber'

// Same breakpoints as the grid classes this replaces (Tailwind's default
// sm=640px/xl=1280px), kept in one place so the virtualizer's row width and
// the rendered column count can never disagree with each other.
function columnsFor(width: number): number {
  if (width >= 1280) return 3
  if (width >= 640) return 2
  return 1
}

function useColumnCount(): number {
  const [cols, setCols] = useState(() =>
    columnsFor(typeof window === 'undefined' ? 0 : window.innerWidth))
  useEffect(() => {
    const onResize = () => setCols(columnsFor(window.innerWidth))
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])
  return cols
}

const ROW_ESTIMATE_PX = 268

// Virtualized so ~533 LXC cards cost a handful of mounted rows rather than
// the whole grid at once (catalog expansion plan, decision 5). Logos load
// lazily as a side effect of this: a card outside the rendered window never
// mounts, so its <img> never fires a network request in the first place.
function StoreGrid({ entries, installedSlugs, onInstall }: {
  entries: CatalogRow[]; installedSlugs: Set<string>; onInstall: (slug: string) => void
}) {
  const parentRef = useRef<HTMLDivElement>(null)
  const columns = useColumnCount()
  const rowCount = Math.ceil(entries.length / columns)
  const virtualizer = useVirtualizer({
    count: rowCount,
    getScrollElement: () => parentRef.current,
    estimateSize: () => ROW_ESTIMATE_PX,
    overscan: 6,
  })

  return (
    <div ref={parentRef} className="max-h-[calc(100vh-260px)] overflow-y-auto">
      <div style={{ height: virtualizer.getTotalSize(), position: 'relative' }}>
        {virtualizer.getVirtualItems().map((vRow) => {
          const rowEntries = entries.slice(vRow.index * columns, vRow.index * columns + columns)
          return (
            <div
              key={vRow.key} data-index={vRow.index} ref={virtualizer.measureElement}
              style={{
                position: 'absolute', top: 0, left: 0, width: '100%',
                transform: `translateY(${vRow.start}px)`,
                display: 'grid', gridTemplateColumns: `repeat(${columns}, 1fr)`, gap: '1rem',
              }}
              className="pb-4"
            >
              {rowEntries.map((e) => (
                <StoreCard key={e.slug} entry={e} installed={installedSlugs.has(e.slug)}
                  onInstall={onInstall} />
              ))}
            </div>
          )
        })}
      </div>
    </div>
  )
}

export function StorePage() {
  const search = useSearch({ strict: false }) as { category?: string; q?: string }
  const navigate = useNavigate()
  const [installing, setInstalling] = useState<string | null>(null)
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

  const setSearch = (patch: Partial<{ category?: string; q?: string }>) =>
    navigate({ to: '/store' as never, search: { ...search, ...patch } as never, replace: true })

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
          onChange={(e) => setSearch({ q: e.target.value || undefined })}
        />
        <div className="flex flex-wrap gap-2">
          {categories.map((c) => (
            <button
              key={c}
              className={`rounded-full px-3 py-1 text-[12px] ${
                (search.category ?? 'All') === c ? 'bg-elev text-text' : 'text-text-2 hover:bg-panel-2'}`}
              onClick={() => setSearch({ category: c === 'All' ? undefined : c })}
            >
              {c}
            </button>
          ))}
        </div>
      </div>

      <QueryState query={catalogQuery}
                  empty={() => filtered.length === 0}
                  emptyTitle="No store entries match your filter."
                  emptyNote=""
                  errorTitle="Store catalog not readable"
                  errorNote="Proxploy could not reach the backend to list the app catalog.">
        {() => (
          <StoreGrid entries={filtered} installedSlugs={installedSlugs}
                    onInstall={(slug) => setInstalling(slug)} />
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
  }),
  component: StorePage,
})
