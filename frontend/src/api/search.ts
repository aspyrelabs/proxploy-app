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
 * GET /search backs the command palette. The server LIKE-scans, so this must
 * never fire on every keystroke (caller debounces `q`) and never fires under
 * 2 characters, the endpoint itself returns an empty array for that but there
 * is no reason to round-trip for a result we already know.
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
