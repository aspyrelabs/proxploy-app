import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'

export type CatalogRow = {
  slug: string; name: string | null; category: string | null
  description: string | null; icon_url: string | null; popularity: number | null
  website: string | null
  default_cpu: number | null; default_ram_mb: number | null; default_disk_gb: number | null
  default_os: string | null; default_os_version: string | null
  installable: boolean; unsupported_reason: string | null
  synced_at: string | null
}

export type CatalogEntryDetail = CatalogRow & { raw: { ct_script: string; install_script: string } | null }

export function useCatalog(category?: string, q?: string) {
  return useQuery({
    queryKey: ['catalog', category, q],
    staleTime: 5 * 60_000,
    queryFn: () => {
      const p = new URLSearchParams()
      if (category) p.set('category', category)
      if (q) p.set('q', q)
      const qs = p.toString()
      return api<CatalogRow[]>(qs ? `/catalog?${qs}` : '/catalog')
    },
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
  slug: string; host_id: number; name: string; ctid: number
  overrides: Record<string, string | number>; consent: boolean
}

export function useInstall() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (v: InstallVars) =>
      api<{ job: { id: number; kind: string } }>(`/catalog/${v.slug}/install`, {
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
