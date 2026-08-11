import { useState } from 'react'
import { createRoute } from '@tanstack/react-router'
import { shellRoute } from './shell'
import { AUDIT_PER_PAGE, auditExportUrl, useAuditLog } from '../api/audit'
import type { AuditFilters } from '../api/audit'
import { useEntitlements } from '../api/hooks'
import { inputCls } from '../components/LoginForm'
import { LockVeil } from '../components/LockVeil'
import { QueryState } from '../components/QueryState'
import { Button } from '../components/ui/button'

const card = 'rounded-card border border-line-soft bg-panel p-5'
const th = 'text-[10.5px] uppercase tracking-wide text-text-3'
const label = 'mb-1 block text-[10.5px] uppercase tracking-wide text-text-3'

export function AuditPage() {
  const ent = useEntitlements()
  // Same wait-for-first-fetch idiom as every other entitlement gate in the
  // app: both GET /audit and GET /audit/export require audit.log, fetching
  // before the flag resolves true would 403 every plan on first load.
  const denied = ent.data != null && !ent.has('audit.log')
  const allowed = ent.data != null && ent.has('audit.log')

  const [filters, setFilters] = useState<AuditFilters>({})
  const [page, setPage] = useState(1)
  const audit = useAuditLog(filters, page, allowed)

  const setFilter = (k: keyof AuditFilters, v: string) => {
    setPage(1)
    setFilters((f) => ({ ...f, [k]: v || undefined }))
  }

  // A real navigation, not api(): the export is a file download
  // (Content-Disposition), and api()'s JSON wrapper would just throw the
  // response body away. Same-origin navigation sends the session cookie on
  // its own.
  const download = (format: 'csv' | 'jsonl') => {
    window.location.assign(auditExportUrl(filters, format))
  }

  return (
    <div className="space-y-5">
      <h1 className="font-display text-[22px] font-semibold">Audit log</h1>

      <LockVeil locked={denied}
                title="Audit log is a Pro feature"
                subtitle="See and export every action taken across your hosts, apps and users.">
        <section className={card}>
          <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
            <div className="flex flex-wrap items-end gap-3">
              <div>
                <label htmlFor="audit-action" className={label}>Action</label>
                <input id="audit-action" className={inputCls} placeholder="host.remove"
                  value={filters.action ?? ''} onChange={(e) => setFilter('action', e.target.value)} />
              </div>
              <div>
                <label htmlFor="audit-actor" className={label}>Actor id</label>
                <input id="audit-actor" className={inputCls} placeholder="1"
                  value={filters.actor ?? ''} onChange={(e) => setFilter('actor', e.target.value)} />
              </div>
              <div>
                <label htmlFor="audit-from" className={label}>From</label>
                <input id="audit-from" type="datetime-local" className={inputCls}
                  value={filters.from_ ?? ''} onChange={(e) => setFilter('from_', e.target.value)} />
              </div>
              <div>
                <label htmlFor="audit-to" className={label}>To</label>
                <input id="audit-to" type="datetime-local" className={inputCls}
                  value={filters.to ?? ''} onChange={(e) => setFilter('to', e.target.value)} />
              </div>
            </div>
            <div className="flex gap-2">
              <Button variant="ghost" onClick={() => download('csv')}>Export CSV</Button>
              <Button variant="ghost" onClick={() => download('jsonl')}>Export JSONL</Button>
            </div>
          </div>

          <QueryState query={audit}
                      emptyTitle="No audit events match."
                      emptyNote="Try widening the filters."
                      errorTitle="Audit log not readable"
                      errorNote="Proxploy could not reach the backend to list audit events.">
            {(fetched) => {
              // The hook asks for one row past the page so "is there more"
              // is a fact rather than an inference; that extra row is never
              // rendered.
              const rows = fetched.slice(0, AUDIT_PER_PAGE)
              const hasMore = fetched.length > AUDIT_PER_PAGE
              return (
              <>
                <table className="w-full text-left text-[13px]">
                  <thead><tr className={th}>
                    <th className="pb-2">When</th><th>Actor</th><th>Action</th>
                    <th>Target</th><th>Result</th><th>IP</th></tr></thead>
                  <tbody>
                    {rows.map((r) => (
                      <tr key={r.id} className="border-t border-line-soft hover:bg-panel-2">
                        <td className="py-2 font-mono text-[11.5px] text-text-3">
                          {new Date(r.ts).toLocaleString()}
                        </td>
                        <td className="font-mono text-text-2">
                          {r.actor_type}{r.actor_id != null ? ` #${r.actor_id}` : ''}
                        </td>
                        <td className="font-mono text-text">{r.action}</td>
                        <td className="font-mono text-[12px] text-text-3">
                          {r.target_type ?? ''}{r.target_id != null ? ` #${r.target_id}` : ''}
                        </td>
                        <td className={r.result === 'error' ? 'text-red' : 'text-green'}>{r.result}</td>
                        <td className="font-mono text-[11.5px] text-text-3">{r.ip ?? ''}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <div className="mt-4 flex justify-end gap-2">
                  <Button variant="ghost" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
                    Previous
                  </Button>
                  <Button variant="ghost" disabled={!hasMore}
                    onClick={() => setPage((p) => p + 1)}>
                    Next
                  </Button>
                </div>
              </>
              )
            }}
          </QueryState>
        </section>
      </LockVeil>
    </div>
  )
}

export const auditRoute = createRoute({
  getParentRoute: () => shellRoute,
  path: '/audit',
  component: AuditPage,
})
