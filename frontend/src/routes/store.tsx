import { createRoute, useNavigate, useSearch } from '@tanstack/react-router'
import { useState } from 'react'
import { useCatalog, useRefreshCatalog } from '../api/catalog'
import { InstallDialog } from '../components/InstallDialog'
import { StoreCard } from '../components/StoreCard'
import { EmptyState } from '../components/EmptyState'
import { Button } from '../components/ui/button'
import { shellRoute } from './shell'

const CATEGORIES = ['All', 'Media', 'Home & Auto', 'Files', 'Network', 'Monitoring',
                    'Databases', 'Security', 'Dev', 'Docker', 'Productivity']

export function StorePage() {
  const search = useSearch({ strict: false }) as { category?: string; q?: string }
  const navigate = useNavigate()
  const [installing, setInstalling] = useState<string | null>(null)
  const category = search.category && search.category !== 'All' ? search.category : undefined
  const { data: entries } = useCatalog(category, search.q)
  const refresh = useRefreshCatalog()

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
            Sourced from community-scripts/ProxmoxVE · showing {entries?.length ?? 0} of{' '}
            {installableCount} installable scripts ({unsupportedCount} unsupported)
          </div>
        </div>
        <Button variant="ghost" onClick={() => refresh.mutate()} disabled={refresh.isPending}>
          Refresh
        </Button>
      </div>

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

      {entries && entries.length > 0 ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {entries.map((e) => (
            <StoreCard key={e.slug} entry={e} installed={false}
              onInstall={(slug) => setInstalling(slug)} />
          ))}
        </div>
      ) : (
        <EmptyState title="No store entries match your filter." note="" />
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
    q: typeof s.q === 'string' && s.q ? s.q : undefined,
  }),
  component: StorePage,
})
