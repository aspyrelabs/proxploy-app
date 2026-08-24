import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api, apiErrorDetail } from '../api/client'
import { notify } from '../lib/notify'
import { useTotpStatus, useTrustedDevices } from '../api/account'
import type { TrustedDeviceRow } from '../api/account'
import { QueryState } from './QueryState'
import { Button } from './ui/button'
import { SkeletonGroup, SkeletonTable } from './ui/skeleton'

/** Only rendered when two-factor is on: with no second factor there is nothing
 *  to skip, so the card would be a list that can never have a row in it.
 *
 *  Self-service like SessionsCard, and for the same reason (api/auth.py's
 *  comment on that section): managing your own login state is not an RBAC or
 *  plan question. Separate from Sessions because these are a different thing
 *  with a different risk: revoking a session signs a browser out, revoking one
 *  of these makes a browser prove the second factor again. */
export function TrustedDevicesCard() {
  const qc = useQueryClient()
  // Same ['auth', 'me'] query TotpCard reads, so this shares its cache rather
  // than costing a second request.
  const totpEnabled = useTotpStatus(true).data?.totp_enabled === true
  const devices = useTrustedDevices(totpEnabled)
  const rows: TrustedDeviceRow[] = Array.isArray(devices.data) ? devices.data : []

  const revoke = useMutation({
    mutationFn: (id: number) => api(`/auth/trusted-devices/${id}`, { method: 'DELETE' }),
    onError: (e) => notify.error(apiErrorDetail(e, 'Request failed, try again.')),
    onSettled: () => qc.invalidateQueries({ queryKey: ['auth', 'trusted-devices'] }),
  })

  if (!totpEnabled) return null

  return (
    <section className="rounded-card border border-line-soft bg-panel p-5">
      <div className="mb-1 flex items-center justify-between">
        <h2 className="font-display text-[15px] font-semibold">Trusted devices</h2>
        {rows.length > 0 && (
          <Button variant="ghost" disabled={revoke.isPending}
            onClick={() => { void (async () => {
              for (const row of rows) await revoke.mutateAsync(row.id)
            })() }}>
            Forget all
          </Button>
        )}
      </div>
      <p className="mb-4 text-[12.5px] text-text-3">
        These browsers skip the authentication code at sign-in. They still need
        your password. Changing your password, or turning two-factor off, forgets
        all of them.
      </p>
      <QueryState query={devices}
                  loading={<SkeletonGroup label="Loading trusted devices">
                    <SkeletonTable rows={1} cols={['w-28', 'w-40', 'w-32', 'w-32', 'w-16']} />
                  </SkeletonGroup>}
                  emptyTitle="No trusted devices."
                  emptyNote="Tick the box at sign-in to skip the code on a browser you use often."
                  errorTitle="Trusted devices not readable"
                  errorNote="Proxploy could not reach the backend to list them.">
        {(list) => (
          /* Every cell but the last gets its gutter here rather than a pr-4
             repeated on eight of them. Without it a long user-agent ran
             straight into the date beside it -- always true, just invisible
             until the section rail narrowed the pane. */
          <table className="w-full text-left text-[13px] [&_td]:pr-4 [&_th]:pr-4 [&_td:last-child]:pr-0 [&_th:last-child]:pr-0">
            <thead><tr className="text-[10.5px] uppercase tracking-wide text-text-3">
              <th className="pb-2">IP</th><th>Device</th><th>Trusted</th><th>Expires</th><th /></tr></thead>
            <tbody>
              {list.map((r) => (
                <tr key={r.id} className="border-t border-line-soft hover:bg-panel-2">
                  <td className="py-2 font-mono">{r.ip ?? 'unknown'}</td>
                  <td className="text-text-2">{r.user_agent ?? 'unknown'}</td>
                  <td className="text-text-3">{new Date(r.created_at).toLocaleDateString()}</td>
                  <td className="text-text-3">{new Date(r.expires_at).toLocaleDateString()}</td>
                  <td className="py-2 text-right">
                    {/* size="sm" for the reason SessionsCard's row button
                        carries: the className size was silently losing to the
                        default one. */}
                    <Button variant="danger" size="sm"
                      disabled={revoke.isPending} onClick={() => revoke.mutate(r.id)}>
                      {r.current ? 'Forget this one' : 'Forget'}
                    </Button>
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
