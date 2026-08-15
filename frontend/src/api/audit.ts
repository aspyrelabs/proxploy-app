import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { api } from './client'

// Mirrors backend/proxploy/api/audit.py::row_dict.
export type AuditRow = {
  id: number; ts: string; actor_type: string; actor_id: number | null
  action: string; target_type: string | null; target_id: number | null
  params: Record<string, unknown> | null; result: string; ip: string | null
  job_id: number | null
}

export type AuditFilters = { action?: string; actor?: string; from_?: string; to?: string }

export const AUDIT_PER_PAGE = 50

// The one filter-to-query-params mapping, shared by the list fetch and the
// export URL, so the export can never silently drop a filter the table is
// showing. Note the literal `from_` key (audit.py's query param, no alias).
function filterEntries(f: AuditFilters): [string, string][] {
  const out: [string, string][] = []
  if (f.action) out.push(['action', f.action])
  if (f.actor) out.push(['actor', f.actor])
  if (f.from_) out.push(['from_', f.from_])
  if (f.to) out.push(['to', f.to])
  return out
}

export function useAuditLog(filters: AuditFilters, page: number, enabled = true) {
  return useQuery({
    queryKey: ['audit', filters, page],
    queryFn: () => {
      const p = new URLSearchParams(filterEntries(filters))
      p.set('page', String(page))
      // One more row than the page renders. Its presence is an exact answer
      // to "is there another page", which the old "did this page come back
      // full" heuristic got wrong on every exact multiple of the page size:
      // the last full page kept Next enabled and walked the user into a blank
      // table. The true total does come back in X-Total-Count, but api()
      // surfaces only the JSON body by design, and widening that shared
      // signature for one screen costs more than fetching one extra row.
      // The route slices back to AUDIT_PER_PAGE for display.
      p.set('per_page', String(AUDIT_PER_PAGE + 1))
      return api<AuditRow[]>(`/audit?${p.toString()}`)
    },
    // Four filter inputs feed this key, so it changes per keystroke and per
    // page step. Holding the previous rows keeps the table from blanking
    // between them.
    placeholderData: keepPreviousData,
    enabled,
  })
}

/**
 * A real download URL, deliberately not run through api(): the export is a
 * StreamingResponse with a Content-Disposition header, and api()'s wrapper
 * reads the body as JSON and throws it away. `window.location.assign` (or an
 * `<a>`) navigating to a same-origin URL sends the session cookie on its own,
 * no manual credentials handling needed.
 */
export function auditExportUrl(filters: AuditFilters, format: 'csv' | 'jsonl'): string {
  const p = new URLSearchParams(filterEntries(filters))
  p.set('format', format)
  return `/api/v1/audit/export?${p.toString()}`
}
