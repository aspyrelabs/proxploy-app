import { useQuery } from '@tanstack/react-query'
import { api } from './client'

export type SearchResult = {
  kind: 'app' | 'vm' | 'host' | 'store'
  id: number | string
  label: string
  sublabel: string
  href: string
  status: string | null
}

export type SearchResponse = { query: string; results: SearchResult[] }

/**
 * GET /search backs the command palette. The server LIKE-scans, so the caller
 * must debounce `q` and never fire under 2 chars (endpoint returns empty anyway).
 */
export function useGlobalSearch(q: string, enabled = true) {
  const trimmed = q.trim()
  return useQuery({
    queryKey: ['search', trimmed],
    queryFn: () => api<SearchResponse>(`/search?q=${encodeURIComponent(trimmed)}`),
    enabled: enabled && trimmed.length >= 2,
    staleTime: 10_000,
  })
}
