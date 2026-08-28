import { DEFAULT_PAGE_SIZE } from '../components/TablePager'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { api } from './client'

// Mirrors backend/proxploy/api/audit.py::row_dict.
//
// `actor_label` and `target_label` are the human names GET /audit joins in for
// the User and Item columns (api/audit.py::_labels). Either is null when
// nothing answers to that id any more, which is the whole point: a host that
// was removed still has to list, reading "host #2".
export type AuditRow = {
  id: number; ts: string; actor_type: string; actor_id: number | null
  actor_label: string | null
  action: string; target_type: string | null; target_id: number | null
  target_label: string | null
  params: Record<string, unknown> | null; result: string; ip: string | null
  job_id: number | null
}

export type AuditFilters = {
  /** One box, matched against the action OR the item (substring, either half). */
  search?: string
  /** A user id, from the Performed by select. */
  actor?: string
  /** "system" or "api_key": the rows no person wrote, which an id cannot reach. */
  actor_type?: string
  from_?: string
  to?: string
}

// Kept as the fallback for callers that do not choose, and re-exported from
// the shared table constants so the Audit log and the App Store offer the same
// page sizes rather than each inventing one.
export const AUDIT_PER_PAGE = DEFAULT_PAGE_SIZE

// The one filter-to-query-params mapping, shared by the list fetch and the
// export URL, so the export can never silently drop a filter the table is
// showing. Note the literal `from_` key (audit.py's query param, no alias).
function filterEntries(f: AuditFilters): [string, string][] {
  const out: [string, string][] = []
  if (f.search) out.push(['search', f.search])
  if (f.actor) out.push(['actor', f.actor])
  if (f.actor_type) out.push(['actor_type', f.actor_type])
  if (f.from_) out.push(['from_', f.from_])
  if (f.to) out.push(['to', f.to])
  return out
}

export function useAuditLog(filters: AuditFilters, page: number, enabled = true,
                            perPage: number = AUDIT_PER_PAGE) {
  return useQuery({
    queryKey: ['audit', filters, page, perPage],
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
      p.set('per_page', String(perPage + 1))
      return api<AuditRow[]>(`/audit?${p.toString()}`)
    },
    // The filter inputs feed this key, so it changes per keystroke and per
    // page step. Holding the previous rows keeps the table from blanking
    // between them.
    placeholderData: keepPreviousData,
    enabled,
  })
}

/** The phrase the backend demands before it deletes anything
 *  (api/audit.py::CLEAR_PHRASE). Hard-coded here as well because the button
 *  has to render the gate before there is a response to read it from; the 409
 *  reply carries the authoritative copy if the two ever diverge. */
export const CLEAR_PHRASE = 'clear audit log'

/**
 * DELETE /audit. `before` clears only entries older than that instant, omitted
 * clears everything, and the backend refuses either without `confirm`.
 *
 * Deliberately NOT given the active filters: the route only understands a
 * cutoff, and "clear what I am looking at" is ambiguous the moment a filter is
 * a substring match.
 */
export function clearAuditLog(body: { before?: string; confirm: string }) {
  return api<{ deleted: number; before: string | null }>('/audit', {
    method: 'DELETE', body: JSON.stringify(body),
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
