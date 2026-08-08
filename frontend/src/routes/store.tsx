import { useQuery } from '@tanstack/react-query'
import { createRoute, useNavigate, useSearch } from '@tanstack/react-router'
import { useState } from 'react'
import { useCatalog, useCatalogStatus, useRefreshCatalog } from '../api/catalog'
import { api } from '../api/client'
import { useEntitlements } from '../api/hooks'
import type { AppRow } from '../api/hooks'
import { InstallDialog } from '../components/InstallDialog'
import { StoreCard } from '../components/StoreCard'
import { QueryState } from '../components/QueryState'
import { Button } from '../components/ui/button'
import { fmtUptime } from '../lib/format'
import { shellRoute } from './shell'

const CATEGORIES = ['All', 'Media', 'Home & Auto', 'Files', 'Network', 'Monitoring',
                    'Databases', 'Security', 'Dev', 'Docker', 'Productivity']

export function StorePage() {
  const search = useSearch({ strict: false }) as { category?: string; q?: string }
  const navigate = useNavigate()
  const [installing, setInstalling] = useState<string | null>(null)
  const category = search.category && search.category !== 'All' ? search.category : undefined
  const catalogQuery = useCatalog(category, search.q)
  const entries = catalogQuery.data
  const refresh = useRefreshCatalog()
  const status = useCatalogStatus()
  const ent = useEntitlements()
  // has() reads false until the first entitlements fetch resolves; gating on
  // !has() alone would grey the button out for every plan during load (same
  // guard AttachmentMap uses in routes/network.tsx).
  const refreshDenied = ent.data != null && !ent.has('store.refresh')
  // Same query key as cluster.tsx's unfiltered /apps fetch, so this shares one
  // cache entry rather than adding a second request. Drives the real
  // `installed` prop below, it used to be hardcoded false, which made
  // StoreCard's tested "Installed" disabled state unreachable in the real page.
  const { data: apps } = useQuery({
    queryKey: ['apps', {}],
    queryFn: () => api<AppRow[]>('/apps'),
  })
  const installedSlugs = new Set((apps ?? []).map((a) => a.catalog_slug).filter(Boolean))

  const installableCount = (entries ?? []).filter((e) => e.installable).length
  const unsupportedCount = (entries ?? []).length - installableCount

  const setSearch = (patch: Partial<{ category?: string; q?: string }>) =>
    navigate({ to: '/store' as never, search: { ...search, ...patch } as never, replace: true })

  return (
    <div>
      <div className="mb-5 flex items-center justify-between">
        <div>
          <h1 className="font-display text-[22px] font-semibold">App Store</h1>
          <div className="text-[12px] text-text-3">
            Sourced from community-scripts/ProxmoxVE · {installableCount} of{' '}
            {entries?.length ?? 0} scripts installable ({unsupportedCount} unsupported)
          </div>
        </div>
        <Button variant="ghost" onClick={() => refresh.mutate()} disabled={refresh.isPending}>
          Refresh
        </Button>
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
                  disabled={refresh.isPending || refreshDenied}
                  title={refreshDenied ? 'Not included in your plan' : undefined}
                  onClick={() => refresh.mutate()}>
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

      <div className="mb-4 flex flex-wrap gap-2">
        {CATEGORIES.map((c) => (
          <button
            key={c}
            className={`rounded-full px-3 py-1 text-[12px] ${
              (search.category ?? 'All') === c ? 'bg-elev text-text' : 'text-text-2 hover:bg-panel-2'}`}
            onClick={() => setSearch({ category: c })}
          >
            {c}
          </button>
        ))}
      </div>

      <QueryState query={catalogQuery}
                  emptyTitle="No store entries match your filter."
                  emptyNote=""
                  errorTitle="Store catalog not readable"
                  errorNote="Proxploy could not reach the backend to list the app catalog.">
        {(rows) => (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {rows.map((e) => (
              <StoreCard key={e.slug} entry={e} installed={installedSlugs.has(e.slug)}
                onInstall={(slug) => setInstalling(slug)} />
            ))}
          </div>
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
