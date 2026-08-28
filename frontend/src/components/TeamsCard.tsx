import { Icon } from './ui/icon'
import { Fragment, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api, apiErrorDetail } from '../api/client'
import { useEntitlements } from '../api/hooks'
import { LockVeil } from './LockVeil'
import { notify } from '../lib/notify'
import { ROLE_OPTIONS, useTeamMembers, useTeams, useUsers } from '../api/teams'
import type { MemberRow, TeamRow, UserRow } from '../api/teams'
import { QueryState } from './QueryState'
import { Button } from './ui/button'
import { CardLoadingOverlay } from './ui/card-loading-overlay'
import { SkeletonGroup, SkeletonTable } from './ui/skeleton'

/** Proxploy stores one display name, so first and last are read off it:
 *  everything before the first space, and everything after. A user with no
 *  display name shows neither rather than repeating their email twice. */
function firstName(display: string | null): string {
  return (display ?? '').trim().split(/\s+/)[0] ?? ''
}

function lastName(display: string | null): string {
  const parts = (display ?? '').trim().split(/\s+/)
  return parts.length > 1 ? parts.slice(1).join(' ') : ''
}

const LAST_OWNER = 'The only owner. Make someone else an owner first, or nobody '
  + 'can manage this install.'

const selectCls = 'min-w-[7rem] rounded-ctl border border-line bg-panel px-2 py-1 text-[12px] text-text'

// teams.py's HTTPException details are plain strings ("cannot remove the
// last owner", "team name already exists") -- main.py::problem_handler puts
// those straight in body.detail. Surface them verbatim rather than a canned
// message: they're the whole point of the two backend behaviors this card
// has to be honest about.
// `usersLoading` travels down beside `usersError` because `users` alone cannot
// tell the two apart: an empty array is what this component gets both when
// every user is already a member and while GET /users is still in flight, and
// only the second of those must not read as "there is nobody to add".
function TeamMembers({ team, users, usersError, usersLoading, onRemove }: {
  team: TeamRow; users: UserRow[]; usersError: boolean; usersLoading: boolean
  onRemove: (team: TeamRow, m: MemberRow) => void
}) {
  const qc = useQueryClient()
  const members = useTeamMembers(team.id)
  const [pickUserId, setPickUserId] = useState('')
  const [pickRole, setPickRole] = useState<string>('viewer')

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['teams'] })
    qc.invalidateQueries({ queryKey: ['teams', team.id, 'members'] })
    qc.invalidateQueries({ queryKey: ['users'] })
  }
  const setRole = useMutation({
    mutationFn: ({ userId, role }: { userId: number; role: string }) =>
      api(`/teams/${team.id}/members/${userId}`, { method: 'PUT', body: JSON.stringify({ role }) }),
    onError: (e) => notify.error(apiErrorDetail(e, 'Request failed, try again.')),
    onSettled: invalidate,
  })
  const addMember = useMutation({
    mutationFn: ({ userId, role }: { userId: number; role: string }) =>
      api(`/teams/${team.id}/members/${userId}`, { method: 'PUT', body: JSON.stringify({ role }) }),
    onSuccess: () => setPickUserId(''),
    onError: (e) => notify.error(apiErrorDetail(e, 'Request failed, try again.')),
    onSettled: invalidate,
  })

  const memberIds = new Set((members.data ?? []).map((m) => m.user_id))
  const candidates = users.filter((u) => !memberIds.has(u.id))

  return (
    <div className="py-3">
      <QueryState query={members}
                  // The card's CardLoadingOverlay covers the teams list's
                  // first fetch, not this one: expanding a team row fires a
                  // fresh per-team query long after that veil has gone, and
                  // the "Add member" controls under this table stay usable
                  // throughout, so this wait belongs to the table alone.
                  loading={<SkeletonGroup label="Loading team members">
                    <SkeletonTable rows={2} cols={['w-44', 'w-24', 'w-16']} />
                  </SkeletonGroup>}
                  emptyTitle="No members yet."
                  emptyNote=""
                  errorTitle="Members not readable"
                  errorNote="Proxploy could not reach the backend to list this team's members.">
        {(rows) => {
        // The install must keep somebody who can promote people. The backend
        // refuses this too; the controls just stop offering a change they
        // know will come back 409.
        const lastOwner = (m: MemberRow) =>
          team.slug === 'default' && m.role === 'owner'
          && rows.filter((r) => r.role === 'owner').length <= 1
        return (
          <table className="w-full text-left text-[12.5px]">
            <thead><tr className="text-[10px] uppercase tracking-wide text-text-3
                                  [&>th:not(:last-child)]:pe-4">
              <th className="pb-2">First name</th>
              <th className="pb-2">Last name</th>
              <th className="pb-2">Email address</th>
              <th className="pb-2">Last login</th>
              <th className="pb-2">Role</th>
              <th className="pb-2" />
            </tr></thead>
            <tbody>
              {rows.map((m) => (
                <tr key={m.user_id}
                    className="border-t border-line-soft [&>td]:py-2.5
                               [&>td:not(:last-child)]:pe-4">
                  <td>{firstName(m.display_name)}</td>
                  <td>{lastName(m.display_name)}</td>
                  <td className="font-mono text-[11.5px]">{m.email}</td>
                  <td className="font-mono text-[11.5px] text-text-3">
                    {m.last_login_at ? new Date(m.last_login_at).toLocaleString() : 'never'}
                  </td>
                  <td>
                    <select aria-label={`role for ${m.email}`} value={m.role}
                      disabled={setRole.isPending || lastOwner(m)}
                      title={lastOwner(m) ? LAST_OWNER : undefined}
                      onChange={(e) => setRole.mutate({ userId: m.user_id, role: e.target.value })}
                      className={selectCls}>
                      {ROLE_OPTIONS.map((r) => <option key={r} value={r}>{r}</option>)}
                    </select>
                  </td>
                  <td className="text-right">
                    <Button variant="icon-danger" size="icon-xs"
                      disabled={lastOwner(m)}
                      title={lastOwner(m) ? LAST_OWNER : undefined}
                      aria-label={`Remove ${m.email}`}
                      onClick={() => onRemove(team, m)}>
                      <Icon name="delete" size={16} />
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}}
      </QueryState>
      <div className="mt-3 flex items-end gap-2">
        <div>
          <label htmlFor={`add-user-${team.id}`}
            className="mb-1 block text-[10.5px] uppercase tracking-wide text-text-3">
            Add member
          </label>
          <select id={`add-user-${team.id}`} value={pickUserId}
            disabled={usersError || usersLoading}
            onChange={(e) => setPickUserId(e.target.value)} className={selectCls}>
            {usersError
              ? <option value="">Could not load users</option>
              : usersLoading
                ? <option value="">Loading users…</option>
                : <option value="">Select user…</option>}
            {candidates.map((u) => <option key={u.id} value={u.id}>{u.email}</option>)}
          </select>
        </div>
        <select aria-label="new member role" value={pickRole}
          onChange={(e) => setPickRole(e.target.value)} className={selectCls}>
          {ROLE_OPTIONS.map((r) => <option key={r} value={r}>{r}</option>)}
        </select>
        <Button size="sm" variant="ghost"
          disabled={!pickUserId || addMember.isPending}
          onClick={() => addMember.mutate({ userId: Number(pickUserId), role: pickRole })}>
          Add
        </Button>
      </div>
    </div>
  )
}

export function TeamsCard() {
  const ent = useEntitlements()
  // Same wait-for-first-fetch pattern as settings.tsx's channelsAllowed:
  // every route on this router requires teams.rbac (teams.py::_ENT), so
  // fetching before the flag resolves true would 403 on every plan during
  // the initial load, not just plans that lack it.
  const teamsAllowed = ent.data != null && ent.has('teams.rbac')
  const qc = useQueryClient()
  const teams = useTeams(teamsAllowed)
  const users = useUsers(teamsAllowed)
  const [adding, setAdding] = useState(false)
  const [name, setName] = useState('')
  const [expanded, setExpanded] = useState<number | null>(null)

  const createTeam = useMutation({
    mutationFn: () => api<TeamRow>('/teams', { method: 'POST', body: JSON.stringify({ name }) }),
    onSuccess: () => { setName(''); setAdding(false); qc.invalidateQueries({ queryKey: ['teams'] }) },
    // The "New team" affordance renders for every role: owner-only
    // enforcement is the backend's job (teams.py's 403), not UI cosmetics.
    onError: (e) => notify.error(apiErrorDetail(e, 'Request failed, try again.')),
  })

  const removeMember = useMutation({
    mutationFn: ({ teamId, userId }: { teamId: number; userId: number }) =>
      api(`/teams/${teamId}/members/${userId}`, { method: 'DELETE' }),
    // Surfaces both backend behaviors honestly: teams.py returns 409 "cannot
    // remove the last owner" for the default team's last owner (shown here,
    // not swallowed); a non-default team's last membership for a user is
    // allowed and returns 200 -- that case is warned about *before* the
    // click, in confirmRemove below, per amendment A1.
    onError: (e) => notify.error(apiErrorDetail(e, 'Request failed, try again.')),
    onSettled: (_d, _e, v) => {
      qc.invalidateQueries({ queryKey: ['teams'] })
      qc.invalidateQueries({ queryKey: ['teams', v.teamId, 'members'] })
      qc.invalidateQueries({ queryKey: ['users'] })
    },
  })

  const confirmRemove = (team: TeamRow, m: MemberRow) => {
    const totalTeams = users.data?.find((u) => u.id === m.user_id)?.teams.length ?? 0
    const isLastMembership = totalTeams <= 1
    const msg = isLastMembership
      ? `Remove ${m.email} from ${team.name}? This is their only team -- they will be ` +
        'denied all access everywhere until added to a team again.'
      : `Remove ${m.email} from ${team.name}?`
    if (window.confirm(msg)) removeMember.mutate({ teamId: team.id, userId: m.user_id })
  }

  return (
    <CardLoadingOverlay state={{
      // Not-yet-known-if-entitled, then the teams list's own first fetch.
      // `isPending`, not `isFetching`: stays quiet on the invalidation
      // refetches every mutation below triggers.
      firstLoad: ent.isPending || (teamsAllowed && teams.isPending),
      // createTeam and removeMember are defined directly on this card.
      // setRole/addMember live in the nested TeamMembers subcomponent (one
      // per expanded team row) and keep their own existing inline pending
      // treatment instead -- lifting that state up here would be a bigger
      // refactor than this card needs. removeMember has no per-row pending
      // indicator at all today, so the card veil is its only feedback.
      mutating: createTeam.isPending || removeMember.isPending,
    }}>
    <section className="rounded-card border border-line-soft bg-panel p-5">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="font-display text-[15px] font-semibold">Teams</h2>
        {/* HIDDEN UNTIL THE TEAMS PLAN SHIPS. The button is commented out, not
            deleted, and nothing behind it was touched: POST /teams, the
            createTeam mutation, the add form below and the entitlement gate
            (`teamsAllowed`) all still work. Restore by uncommenting; there is
            nothing else to put back.

        {teamsAllowed && (
          <Button variant="ghost" onClick={() => setAdding((a) => !a)}>
            {adding ? 'Close' : 'New team'}
          </Button>
        )}
        */}
      </div>
      {ent.data != null && !teamsAllowed && (
        <LockVeil locked feature="teams.rbac"
          subtitle="Group hosts into teams and give each person a role, so not everyone is an owner."
          skeleton={<div aria-hidden className="pt-1">
            <SkeletonTable cols={['w-28', 'w-16', 'w-16', 'w-12']} rows={3} />
          </div>}>
          <></>
        </LockVeil>
      )}
      {teamsAllowed && (
        <>
          <QueryState query={teams}
                      // The outer CardLoadingOverlay already veils the card
                      // for teams.isPending; suppress the inner placeholder
                      // so the two don't stack.
                      loading={<></>}
                      emptyTitle="No teams yet."
                      emptyNote=""
                      errorTitle="Teams not readable"
                      errorNote="Proxploy could not reach the backend to list your teams.">
            {(rows) => (
              <table className="w-full text-left text-[13px]">
                <thead><tr className="text-[10.5px] uppercase tracking-wide text-text-3">
                  <th className="pb-2">Team</th><th>Members</th><th>Hosts</th><th /></tr></thead>
                <tbody>
                  {rows.map((t) => (
                    <Fragment key={t.id}>
                      <tr className="border-t border-line-soft hover:bg-panel-2">
                        <td className="py-2 font-mono">
                          <button type="button" className="cursor-pointer text-left"
                            onClick={() => setExpanded((x) => (x === t.id ? null : t.id))}>
                            {expanded === t.id ? '▾' : '▸'} {t.name}
                          </button>
                        </td>
                        <td>{t.member_count}</td>
                        <td>{t.host_count}</td>
                        <td />
                      </tr>
                      {expanded === t.id && (
                        <tr className="border-t border-line-soft bg-panel-2/40">
                          <td colSpan={4}>
                            {/* `isLoading`, not `isPending`: useUsers is
                                entitlement-gated, and a disabled query stays
                                pending for ever. */}
                            <TeamMembers team={t} users={users.data ?? []}
                              usersError={users.isError} usersLoading={users.isLoading}
                              onRemove={confirmRemove} />
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  ))}
                </tbody>
              </table>
            )}
          </QueryState>
          {adding && (
            <div className="mt-4 flex items-end gap-2 border-t border-line-soft pt-4">
              <div className="flex-1">
                <label htmlFor="team-name"
                  className="mb-1 block text-[11px] uppercase tracking-wide text-text-3">
                  Name
                </label>
                <input id="team-name"
                  className="w-full rounded-ctl border border-line bg-panel-2 px-3 py-1.5 text-[13px] text-text"
                  value={name} onChange={(e) => setName(e.target.value)} placeholder="Ops" />
              </div>
              <Button disabled={!name || createTeam.isPending} onClick={() => createTeam.mutate()}>
                Create team
              </Button>
            </div>
          )}
        </>
      )}
    </section>
    </CardLoadingOverlay>
  )
}
