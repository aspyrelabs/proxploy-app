import { useQuery } from '@tanstack/react-query'
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
      p.set('per_page', String(AUDIT_PER_PAGE))
      return api<AuditRow[]>(`/audit?${p.toString()}`)
    },
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
