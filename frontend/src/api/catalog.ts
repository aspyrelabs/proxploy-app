import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'

// Every non-ct type stays in the catalog table, tagged by type, and never
// appears in the Store grid (catalog expansion plan, decision: LXC-only
// Store). "ct" is the only type the Store ever requests.
export type CatalogEntryType = 'ct' | 'vm' | 'pve' | 'addon' | 'turnkey'

/**
 * How this slug stands in upstream's own catalog, which is a separate question
 * from whether we can install it.
 *
 *  - "listed"   upstream carries it today. The ordinary case.
 *  - "delisted" upstream soft-deleted it, so its metadata still arrives and
 *               the card is fully populated.
 *  - "unlisted" upstream dropped it entirely, so there is no metadata to have
 *               and the card renders bare.
 *  - "superseded" upstream renamed the app and left the old script behind
 *               (netvisor became scanopy), so the old slug would render as a
 *               second, blank card under the new name. Hidden by the same
 *               server-side rule as "variant" and never reaches the grid.
 *  - "variant"  not an app of its own: the install script implements an
 *               existing app's Alpine variant (ct/alpine-syncthing.sh IS
 *               Syncthing's alpine install_method), so upstream shows one
 *               card where we discovered two. The store grid never receives
 *               these: list_catalog excludes them server-side for
 *               entry_type=ct, which is why nothing here filters on it. The
 *               value is typed because the API can still return it on other
 *               routes, not because the Store acts on it.
 *  - null       not yet classified, e.g. rows written before the metadata
 *               sync first ran.
 */
export type UpstreamState =
  'listed' | 'delisted' | 'unlisted' | 'variant' | 'superseded' | null

export type CatalogRow = {
  slug: string; name: string | null; category: string | null; type: CatalogEntryType
  description: string | null; icon_url: string | null; popularity: number | null
  // Both come from upstream metadata now (its `website` and `documentation`).
  // Null on either is normal and ambiguous by design: the row matched no
  // upstream record, or upstream simply has no such link for it. Nothing
  // renders docs_url yet; it is typed because the API serves it.
  website: string | null; docs_url: string | null
  default_cpu: number | null; default_ram_mb: number | null; default_disk_gb: number | null
  default_os: string | null; default_os_version: string | null
  // Tri-state: null means "discovered, not yet classified" (catalog expansion
  // plan decision 2 - classification is lazy, on card-open or install-attempt,
  // or the low-priority background pass, never during discovery/refresh).
  // What discovery found and pinned: the file inside
  // community-scripts/ProxmoxVE that would run, and the commit it was read
  // at. The pair is what makes "what will Proxploy run" answerable, so a
  // missing half means the question goes unanswered rather than guessed at.
  //
  // NEVER derive the path from the slug, and note WHY a test cannot catch a
  // derivation that only ever sees the Store. For ct rows the two cannot
  // diverge by construction: discovery takes the slug FROM the path
  // (services/catalog.py::_ct_slug returns path[len("ct/"):-len(".sh")]), so
  // ct/<slug>.sh holds for all 585 of them and would go on holding. The 84
  // non-ct rows the same serializer returns are where it breaks, and the
  // sharpest of them are the 5 addon rows where discovery deliberately
  // INVENTS a slug that is not the filename: tools/addon/coolify.sh is
  // `coolify-addon`, so that it cannot shadow the real ct/coolify.sh row.
  // Reconstructing a path from a slug would have to know about that renaming,
  // which is precisely the coupling this stored column exists to avoid.
  script_path: string | null
  upstream_sha: string | null
  installable: boolean | null; unsupported_reason: string | null
  upstream_state: UpstreamState
  // Install runs recorded by community-scripts' telemetry, terminal events
  // only (services/catalog_telemetry.py). Not downloads, and not successes
  // alone: it counts finished attempts, successful or not.
  popularity_synced_at: string | null
  script_created: string | null; script_updated: string | null
  // THREE-STATE, and the third state is the point: null means upstream has no
  // record for this slug (the 7 "unlisted" rows), NOT "no". `has_arm: null` is
  // not "x86 only" and `privileged: null` is not "unprivileged". Anything
  // rendering these must key off an explicit === true or === false and show
  // nothing at all for null.
  has_arm: boolean | null
  updateable: boolean | null
  privileged: boolean | null
  architectures: string[] | null
  port: number | null
  synced_at: string | null
}

export type CatalogEntryDetail = CatalogRow & { raw: { ct_script: string; install_script: string } | null }

export function useCatalog(category?: string, q?: string, entryType: CatalogEntryType = 'ct') {
  return useQuery({
    queryKey: ['catalog', category, q, entryType],
    staleTime: 5 * 60_000,
    queryFn: () => {
      const p = new URLSearchParams()
      if (category) p.set('category', category)
      if (q) p.set('q', q)
      if (entryType) p.set('entry_type', entryType)
      const qs = p.toString()
      return api<CatalogRow[]>(qs ? `/catalog?${qs}` : '/catalog')
    },
  })
}

export type CatalogStatus = {
  synced_at: string | null; age_s: number | null
  entries: number; stale_after_s: number; stale: boolean
}

export function useCatalogStatus() {
  return useQuery({
    queryKey: ['catalog', 'status'],
    queryFn: () => api<CatalogStatus>('/catalog/status'),
    // Same ['catalog'] prefix as the row list on purpose: useRefreshCatalog's
    // qc.invalidateQueries({ queryKey: ['catalog'] }) fuzzy-matches by prefix,
    // so a refresh drops this cache entry too without a second invalidation.
    refetchInterval: 60_000,
  })
}

export function useCatalogEntry(slug: string | null) {
  return useQuery({
    queryKey: ['catalog', slug],
    enabled: slug != null,
    queryFn: () => api<CatalogEntryDetail>(`/catalog/${slug}`),
  })
}

export function useRefreshCatalog() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api<{ job: { id: number; kind: string } }>('/catalog/refresh', { method: 'POST' }),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ['jobs'] })
      // A refresh is what actually rewrites catalog_entries, so this is the
      // mutation that has to drop the ['catalog'] cache. Invalidating on
      // settle (i.e. once the job is enqueued, not finished) is deliberate:
      // the refetch that follows the job's completion event picks up the new
      // rows, and this at least clears the 5-minute staleTime immediately.
      qc.invalidateQueries({ queryKey: ['catalog'] })
    },
  })
}

export type InstallVars = {
  // Optional: blank/null means the node assigns the next free id
  // (InstallIn.ctid, backend/proxploy/api/catalog.py).
  slug: string; host_id: number; name: string; ctid: number | null
  overrides: Record<string, string | number>; consent: boolean
}

export function useInstall() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (v: InstallVars) =>
      api<{ job: { id: number; kind: string; progress_pct: number | null } }>(`/catalog/${v.slug}/install`, {
        method: 'POST',
        body: JSON.stringify({ host_id: v.host_id, name: v.name, ctid: v.ctid,
                              overrides: v.overrides, consent: v.consent }),
      }),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ['jobs'] })
      // An install creates an App row; it does not touch catalog_entries.
      // ['apps'] is what goes stale here, including the Store page's own
      // installed-slug lookup.
      qc.invalidateQueries({ queryKey: ['apps'] })
    },
  })
}
