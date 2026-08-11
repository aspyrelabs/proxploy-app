import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { api, ApiError } from '../api/client'
import { useUsers } from '../api/teams'
import type { UserRow } from '../api/teams'
import { ConfirmSelfDialog } from './ConfirmSelfDialog'
import { QueryState } from './QueryState'
import { Button } from './ui/button'
import { Dialog } from './ui/dialog'

// self_deactivate/self_delete/last_owner are the three 409s an admin will
// actually hit while managing their own team, name them plainly instead of
// a generic "Request failed".
const ERROR_COPY: Record<string, string> = {
  self_deactivate: 'You cannot deactivate your own account.',
  self_delete: 'You cannot delete your own account.',
  last_owner: 'This is the last owner. Promote another owner before this.',
}

function errorOf(e: unknown): string {
  if (e instanceof ApiError) {
    const kind = (e.body as any)?.error
    if (typeof kind === 'string' && ERROR_COPY[kind]) return ERROR_COPY[kind]
    const detail = (e.body as any)?.detail
    if (typeof detail === 'string') return detail
  }
  return 'Request failed, try again.'
}

function ResetPasswordDialog({ user, pending, onCancel, onSubmit }: {
  user: UserRow; pending: boolean; onCancel: () => void; onSubmit: (password: string) => void
}) {
  const [password, setPassword] = useState('')
  return (
    <Dialog title={<>Reset password, {user.email}</>} width={380} onClose={onCancel}>
    <p className="mt-2 text-[12.5px] text-text-3">
      Revokes every live session for this account. TOTP is not cleared, do not treat
      this as a full account reset.
    </p>
    <label htmlFor="reset-password"
      className="mb-1 mt-3 block text-[11px] uppercase tracking-wide text-text-3">
      New password (min 12 characters)
    </label>
    <input id="reset-password" type="password" value={password}
      onChange={(e) => setPassword(e.target.value)}
      className="w-full rounded-ctl border border-line bg-panel px-3 py-1.5 text-[13px] text-text" />
    <div className="mt-4 flex justify-end gap-2">
      <Button variant="ghost" onClick={onCancel}>Cancel</Button>
      <Button disabled={password.length < 12 || pending} onClick={() => onSubmit(password)}>
        {pending ? 'Setting…' : 'Set password'}
      </Button>
    </div>
    </Dialog>
  )
}

export function UsersCard() {
  const qc = useQueryClient()
  const users = useUsers()
  const [rowErrors, setRowErrors] = useState<Record<number, string>>({})
  const [resetting, setResetting] = useState<UserRow | null>(null)
  const [deleting, setDeleting] = useState<UserRow | null>(null)

  const clearError = (id: number) =>
    setRowErrors((r) => { const next = { ...r }; delete next[id]; return next })

  // Retained deliberately while its button is commented out below, so the
  // deactivate/reactivate flow comes back by uncommenting one block rather
  // than being rewritten. `void` is what keeps noUnusedLocals quiet without
  // deleting the mutation.
  const toggleActive = useMutation({
    mutationFn: (u: UserRow) => api<{ sessions_revoked: number }>(`/users/${u.id}`, {
      method: 'PATCH', body: JSON.stringify({ is_active: !u.is_active }),
    }),
    onSuccess: (r, u) => {
      clearError(u.id)
      if (u.is_active) toast.success(`${u.email} deactivated, ${r.sessions_revoked} session(s) revoked.`)
    },
    onError: (e, u) => setRowErrors((r) => ({ ...r, [u.id]: errorOf(e) })),
    onSettled: () => qc.invalidateQueries({ queryKey: ['users'] }),
  })

  void toggleActive

  const resetPassword = useMutation({
    mutationFn: (vars: { id: number; password: string }) =>
      api<{ ok: boolean; sessions_revoked: number }>(`/users/${vars.id}/password`, {
        method: 'POST', body: JSON.stringify({ password: vars.password }),
      }),
    onSuccess: (r) => {
      toast.success(`Password set, ${r.sessions_revoked} session(s) revoked. TOTP was not cleared.`)
      setResetting(null)
    },
    onError: (e) => toast.error(errorOf(e)),
  })

  const deleteUser = useMutation({
    mutationFn: (id: number) => api(`/users/${id}`, { method: 'DELETE' }),
    onSuccess: (_d, id) => { clearError(id); setDeleting(null) },
    onError: (e, id) => { setRowErrors((r) => ({ ...r, [id]: errorOf(e) })); setDeleting(null) },
    onSettled: () => qc.invalidateQueries({ queryKey: ['users'] }),
  })

  return (
    <section className="rounded-card border border-line-soft bg-panel p-5">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="font-display text-[15px] font-semibold">Users</h2>
      </div>
      <QueryState query={users}
                  emptyTitle="No users yet."
                  emptyNote=""
                  errorTitle="Users not readable"
                  errorNote="Proxploy could not reach the backend to list users.">
        {(rows) => (
          <table className="w-full text-left text-[13px]">
            <thead><tr className="text-[10.5px] uppercase tracking-wide text-text-3">
              <th className="pb-2 font-normal">Email</th>
              <th className="pb-2 font-normal">Name</th>
              <th className="pb-2 font-normal">State</th>
              <th className="pb-2" /></tr></thead>
            <tbody>
              {/* align-middle, not align-top: the actions cell is taller than a
                  line of text (a button, and sometimes an error above it), so
                  pinning to the top left the email and state sitting high while
                  the button hung below them. Every cell carries the same py-2
                  for the same reason: uneven padding reads as misalignment even
                  when the text baselines agree. */}
              {rows.map((u) => (
                <tr key={u.id} className="border-t border-line-soft align-middle hover:bg-panel-2">
                  <td className="py-2 font-mono">{u.email}</td>
                  <td className="py-2 text-text-2">{u.display_name ?? ''}</td>
                  <td className={`py-2 ${u.is_active ? 'text-green' : 'text-text-3'}`}>
                    {u.is_active ? 'active' : 'deactivated'}
                  </td>
                  <td className="py-2 text-right">
                    {rowErrors[u.id] && (
                      <div className="mb-1 text-[11.5px] text-red">{rowErrors[u.id]}</div>
                    )}
                    {/* HIDDEN UNTIL THERE IS MORE THAN ONE USER TO MANAGE.
                        With a single account, both of these can only fail:
                        auth.py refuses self_delete and last_owner on DELETE
                        /users/{id}, and self_deactivate and last_owner on
                        PATCH. So the buttons were affordances whose only
                        possible outcome was an error dialog.

                        Nothing behind them was touched: both endpoints, the
                        toggleActive mutation, ConfirmSelfDialog and the
                        rowErrors plumbing are all still here. Restore by
                        uncommenting.

                    <Button variant="ghost" className="px-2 py-1 text-[11px]"
                      disabled={toggleActive.isPending}
                      onClick={() => {
                        if (u.is_active && !window.confirm(
                          `Deactivate ${u.email}? This revokes every live session for that account immediately.`)) return
                        toggleActive.mutate(u)
                      }}>
                      {u.is_active ? 'Deactivate' : 'Reactivate'}
                    </Button>
                    */}
                    <Button variant="ghost" className="px-2 py-1 text-[11px]"
                      onClick={() => setResetting(u)}>
                      Reset password
                    </Button>
                    {/*
                    <Button variant="danger" className="ml-2 px-2 py-1 text-[11px]"
                      onClick={() => setDeleting(u)}>
                      Delete
                    </Button>
                    */}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </QueryState>

      {resetting && (
        <ResetPasswordDialog user={resetting} pending={resetPassword.isPending}
          onCancel={() => setResetting(null)}
          onSubmit={(password) => resetPassword.mutate({ id: resetting.id, password })} />
      )}
      {deleting && (
        <ConfirmSelfDialog title={`Delete ${deleting.email}?`} phrase={deleting.email}
          detail="This deletes the account outright, and its audit rows become unattributable.
                  Prefer Deactivate unless this account should never have existed."
          onCancel={() => setDeleting(null)}
          onConfirm={() => deleteUser.mutate(deleting.id)} />
      )}
    </section>
  )
}
