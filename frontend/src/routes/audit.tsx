import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { createRoute } from '@tanstack/react-router'
import { shellRoute } from './shell'
import { AUDIT_PER_PAGE, CLEAR_PHRASE, auditExportUrl, clearAuditLog, useAuditLog } from '../api/audit'
import type { AuditFilters, AuditRow } from '../api/audit'
import { ApiError, apiErrorDetail } from '../api/client'
import { useEntitlements } from '../api/hooks'
import { useUsers } from '../api/teams'
import { ConfirmSelfDialog } from '../components/ConfirmSelfDialog'
import { inputCls } from '../components/LoginForm'
import { LockVeil } from '../components/LockVeil'
import { actionLabel, statusLabel } from '../lib/activityDisplay'
import { QueryState } from '../components/QueryState'
import { Button } from '../components/ui/button'
import {
  Pagination, PaginationContent, PaginationItem, PaginationNext, PaginationPrevious,
} from '../components/ui/pagination'
import { SkeletonGroup, SkeletonTable } from '../components/ui/skeleton'

const card = 'rounded-card border border-line-soft bg-panel p-5'
const th = 'text-[10.5px] uppercase tracking-wide text-text-3'
const label = 'mb-1 block text-[10.5px] uppercase tracking-wide text-text-3'

/** The raw shape the User and Item columns fall back to: "host #2". Ugly on
 *  purpose, and never blank: it is what is left when the thing a row is about
 *  has been deleted, and the removal is usually the row someone came to read. */
const rawRef = (kind: string | null, id: number | null) =>
  kind == null ? '' : id == null ? kind : `${kind} #${id}`

/** Who did it. A person's name where a person did it, and the truth otherwise:
 *  a schedule tick writes actor_type "system" with no id at all, and an API
 *  call writes the key's id, so calling either one a person would be a false
 *  attribution on the one screen that gets read after an incident. */
function actorName(r: AuditRow): string {
  if (r.actor_type === 'system') return 'System'
  if (!r.actor_label) return rawRef(r.actor_type, r.actor_id)
  return r.actor_type === 'user' ? r.actor_label : `${r.actor_label} (API key)`
}

/** Performed-by option values. A user id is a bare number so it goes straight
 *  into the `actor` param; the two non-person choices are prefixed because they
 *  set `actor_type` instead, and one select cannot send two shapes of value
 *  without saying which is which. */
const PERFORMED_BY = [
  { value: '', text: 'Anyone' },
  { value: 'type:system', text: 'System (Proxploy itself)' },
  { value: 'type:api_key', text: 'Any API key' },
]

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
  // GET /users needs ("user", "read"), which is the same admin floor as
  // ("audit", "read"), so anyone who can see this page can fill the select.
  const users = useUsers(allowed)

  const setFilter = (k: keyof AuditFilters, v: string) => {
    setPage(1)
    setFilters((f) => ({ ...f, [k]: v || undefined }))
  }

  // One control, two params: a user id narrows `actor`, the non-person choices
  // narrow `actor_type`. Both are cleared on every change so the two can never
  // be sent together and silently intersect to nothing.
  const setPerformedBy = (v: string) => {
    setPage(1)
    setFilters((f) => ({
      ...f,
      actor: v && !v.startsWith('type:') ? v : undefined,
      actor_type: v.startsWith('type:') ? v.slice('type:'.length) : undefined,
    }))
  }

  // Clearing the log. Owner-only and typed-confirmed at the backend
  // (api/audit.py::clear_audit); this side offers the gate, never a way past
  // it, and reports back what the server said it did.
  const qc = useQueryClient()
  const [clearOpen, setClearOpen] = useState(false)
  const [clearBefore, setClearBefore] = useState('')
  const [clearNote, setClearNote] = useState('')
  const clear = useMutation({
    mutationFn: clearAuditLog,
    onSuccess: (r) => {
      setClearOpen(false)
      setPage(1)
      qc.invalidateQueries({ queryKey: ['audit'] })
      setClearNote(`Cleared ${r.deleted} ${r.deleted === 1 ? 'entry' : 'entries'}`
        + `${r.before ? ' older than ' + new Date(r.before).toLocaleString() : ''}.`
        + ' The clear itself is recorded in the log.')
    },
    // A 403 here is the owner-only gate holding, which is a RULE, not a fault,
    // and the server's raw sentence reads like a bug to the admin who just
    // pressed the button. So it gets a legible line on top with the real text
    // underneath, the same shape the host errors use: act on the first
    // sentence, verify with the second. Every other failure keeps the backend's
    // own sentence, because saying "try again" to a refusal would be a lie.
    onError: (e) => {
      setClearOpen(false)
      const raw = apiErrorDetail(e, 'Could not clear the audit log, try again.')
      setClearNote(e instanceof ApiError && e.status === 403
        ? `Only the owner can clear the audit log. ${raw}`
        : raw)
    },
  })

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
                <label htmlFor="audit-search" className={label}>Item or action</label>
                {/* One box for both halves: the backend matches it against the
                    stored action or against the item's name (audit.py::
                    _search_clause), so "pve-lab-01" and "remove" both find
                    something. */}
                <input id="audit-search" className={inputCls} placeholder="pve-lab-01 or host.remove"
                  value={filters.search ?? ''} onChange={(e) => setFilter('search', e.target.value)} />
              </div>
              <div>
                <label htmlFor="audit-actor" className={label}>Performed by</label>
                <select id="audit-actor" className={inputCls}
                  value={filters.actor_type ? `type:${filters.actor_type}` : (filters.actor ?? '')}
                  onChange={(e) => setPerformedBy(e.target.value)}>
                  {PERFORMED_BY.map((o) => (
                    <option key={o.value} value={o.value}>{o.text}</option>
                  ))}
                  {(users.data ?? []).map((u) => (
                    <option key={u.id} value={String(u.id)}>
                      {u.display_name || u.email}
                    </option>
                  ))}
                </select>
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
              <Button variant="danger" disabled={clear.isPending}
                      onClick={() => { setClearNote(''); setClearOpen(true) }}>
                Clear log…
              </Button>
            </div>
          </div>

          {clearNote && <p className="mb-4 text-[12.5px] text-text-2">{clearNote}</p>}

          <QueryState query={audit}
                      // The filters above stay live and the table below is
                      // the only thing that changes, so the wait reads as
                      // "these rows are being fetched" rather than as the
                      // page going away. Every re-filter and every page turn
                      // comes back through here.
                      loading={<SkeletonGroup label="Loading audit events">
                        <SkeletonTable cols={['w-32', 'w-20', 'w-28', 'w-20', 'w-12', 'w-24']} />
                      </SkeletonGroup>}
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
                    <th className="pb-2">Date</th><th>User</th><th>Action</th>
                    <th>Item</th><th>Result</th><th>IP</th></tr></thead>
                  <tbody>
                    {rows.map((r) => (
                      <tr key={r.id} className="border-t border-line-soft hover:bg-panel-2">
                        <td className="py-2 font-mono text-[11.5px] text-text-3">
                          {new Date(r.ts).toLocaleString()}
                        </td>
                        <td className="text-text-2">{actorName(r)}</td>
                        {/* Friendly name on top, raw identifier under it: the
                            filter, the export and the API all still speak the
                            stored value, so hiding it would make this page
                            unusable for filtering and for debugging. The
                            result is passed in so a denied row reads "Blocked
                            Host Disconnect" rather than leaving the verdict to
                            the Result column, which is the second glance. */}
                        <td className="py-2 text-text">
                          {/* job_id matters here and nowhere else: it marks a
                              row that recorded a REQUEST, written when the job
                              was queued, so the row is about the asking and
                              not about the finishing. The audit log is the
                              only surface that keeps these rows, so it is the
                              only one that has to say which it is. */}
                          {actionLabel(r.action, r.result)}
                          <span className="block font-mono text-[11px] text-text-3">{r.action}</span>
                        </td>
                        {/* The item by name where there is one, the raw
                            `host #2` where there is not. Not blank: the label
                            is missing exactly when the target was deleted, and
                            that deletion is usually the row being looked for. */}
                        <td className="text-[12px] text-text-3">
                          {r.target_label ?? rawRef(r.target_type, r.target_id)}
                        </td>
                        {/* Green is for `ok` and nothing else. Keyed on
                            failure before ("error" only) it painted `denied`
                            green, i.e. the one result that most needs to
                            stand out was styled as the happy path. */}
                        <td className={r.result === 'ok' ? 'text-green' : 'text-red'}>
                          {statusLabel(r.result)}
                        </td>
                        <td className="font-mono text-[11.5px] text-text-3">{r.ip ?? ''}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <div className="mt-4 flex justify-end">
                  <Pagination className="mx-0 w-auto">
                    <PaginationContent>
                      <PaginationItem>
                        {/* Real buttons, genuinely disabled at the ends. The
                            shadcn example ships anchors, and an anchor is the
                            wrong control here twice over: href="#" jumps the
                            scroll position, and aria-disabled on a link still
                            follows on click. */}
                        <PaginationPrevious disabled={page <= 1}
                                            onClick={() => setPage((p) => p - 1)} />
                      </PaginationItem>
                      <PaginationItem>
                        {/* Page N, and no "of M": the endpoint answers with rows
                            only, so the total is not something this table knows.
                            Numbered links and the ellipsis are left out for the
                            same reason. Offering a jump to page 9 that cannot
                            land is worse than not offering it. */}
                        <span className="px-2 text-[12px] text-text-2">Page {page}</span>
                      </PaginationItem>
                      <PaginationItem>
                        <PaginationNext disabled={!hasMore}
                                        onClick={() => setPage((p) => p + 1)} />
                      </PaginationItem>
                    </PaginationContent>
                  </Pagination>
                </div>
              </>
              )
            }}
          </QueryState>
        </section>
      </LockVeil>

      {clearOpen && (
        <ConfirmSelfDialog
          title="Clear the audit log"
          phrase={CLEAR_PHRASE}
          detail={'This deletes audit entries for good. Proxploy records who '
            + 'cleared the log, and how many entries went, as the first entry '
            + 'afterwards. Leave the date empty to clear everything. Nothing '
            + 'here follows the filters above.'}
          onConfirm={(typed) => clear.mutate({
            confirm: typed,
            // Midnight local, so "older than the 31st" keeps the 31st.
            before: clearBefore ? `${clearBefore}T00:00:00` : undefined,
          })}
          onCancel={() => setClearOpen(false)}
        >
          {/* Retention, not erasure, is the everyday reason to be here, so the
              cutoff is offered first. A native date input: no picker library,
              and the browser already validates it. */}
          <label className="mt-4 block text-[12px] text-text-3" htmlFor="audit-clear-before">
            Clear entries older than
          </label>
          <input id="audit-clear-before" type="date" className={`mt-1 ${inputCls}`}
            value={clearBefore} onChange={(e) => setClearBefore(e.target.value)} />
        </ConfirmSelfDialog>
      )}
    </div>
  )
}

export const auditRoute = createRoute({
  getParentRoute: () => shellRoute,
  path: '/audit',
  component: AuditPage,
})
