import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api, apiErrorDetail } from '../api/client'
import { notify } from '../lib/notify'
import { useSessions } from '../api/account'
import { describeDevice } from '../lib/user-agent'
import type { SessionRow } from '../api/account'
import { QueryState } from './QueryState'
import { Button } from './ui/button'
import { SkeletonGroup, SkeletonTable } from './ui/skeleton'

// No entitlement gate: GET/DELETE /auth/sessions are self-service on the
// caller's own login state (api/auth.py's comment on that section), not an
// RBAC or plan question -- same status as "list/revoke my own API keys".
export function SessionsCard() {
  const qc = useQueryClient()
  const sessions = useSessions()
  const rows: SessionRow[] = Array.isArray(sessions.data) ? sessions.data : []
  const others = rows.filter((r) => !r.current)

  const revoke = useMutation({
    mutationFn: (id: number) => api(`/auth/sessions/${id}`, { method: 'DELETE' }),
    onError: (e) => notify.error(apiErrorDetail(e, 'Request failed, try again.')),
    onSettled: () => qc.invalidateQueries({ queryKey: ['auth', 'sessions'] }),
  })

  const signOutEverywhereElse = async () => {
    for (const row of others) await revoke.mutateAsync(row.id)
  }

  return (
    <section className="rounded-card border border-line-soft bg-panel p-5">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="font-display text-[15px] font-semibold">Sessions</h2>
        {others.length > 0 && (
          <Button variant="ghost" disabled={revoke.isPending}
            onClick={() => { void signOutEverywhereElse() }}>
            Sign out everywhere else
          </Button>
        )}
      </div>
      <QueryState query={sessions}
                  // Never empty: the reader is always one of the rows.
                  loading={<SkeletonGroup label="Loading sessions">
                    {/* IP, Device, Started, Last seen, and the Sign out button. */}
                    <SkeletonTable rows={2} cols={['w-28', 'w-40', 'w-32', 'w-32', 'w-16']} />
                  </SkeletonGroup>}
                  emptyTitle="No sessions."
                  emptyNote=""
                  errorTitle="Sessions not readable"
                  errorNote="Proxploy could not reach the backend to list your sessions.">
        {(list) => (
          /* Gutter on every cell but the last, via the table selector instead
             of per-cell pr-4 (a long user-agent collided with the date). */
          <table className="w-full text-left text-[13px] [&_td]:pr-4 [&_th]:pr-4 [&_td:last-child]:pr-0 [&_th:last-child]:pr-0">
            <thead><tr className="text-[10.5px] uppercase tracking-wide text-text-3">
              <th className="pb-2">IP</th><th>Device</th><th>Started</th><th>Last seen</th><th /></tr></thead>
            <tbody>
              {list.map((r) => (
                <tr key={r.id} className="border-t border-line-soft hover:bg-panel-2">
                  <td className="py-2 font-mono">{r.ip ?? 'unknown'}</td>
                  <td className="text-text-2" title={r.user_agent ?? undefined}>
                    {describeDevice(r.user_agent)}
                  </td>
                  <td className="text-text-3">{new Date(r.created_at).toLocaleString()}</td>
                  <td className="text-text-3">
                    {r.last_seen_at ? new Date(r.last_seen_at).toLocaleString() : 'unknown'}
                  </td>
                  <td className="py-2 text-right">
                    {r.current ? (
                      <span className="text-[11px] text-green">current</span>
                    ) : (
                      // size="sm", not a className: px-2/py-1/text-[11px]
                      // collides with size md's own, and the emit order decides
                      // which wins. It lost, so this rendered full size.
                      <Button variant="danger" size="sm"
                        disabled={revoke.isPending} onClick={() => revoke.mutate(r.id)}>
                        Sign out
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </QueryState>
    </section>
  )
}
