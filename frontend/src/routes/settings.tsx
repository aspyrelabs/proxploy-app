import { Fragment, useState } from 'react'
import { createRoute } from '@tanstack/react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { shellRoute } from './shell'
import { api, apiErrorDetail } from '../api/client'
import { notify } from '../lib/notify'
import { useEntitlements } from '../api/hooks'
import { useSchedules } from '../api/schedules'
import { actionLabel } from '../lib/activityDisplay'
import type { ScheduleRow } from '../api/schedules'
import { ChannelForm } from '../components/ChannelForm'
import type { ChannelRow } from '../components/ChannelForm'
import { HostEditDialog } from '../components/HostEditDialog'
import { HostForm } from '../components/HostForm'
import { HostRemoveDialog } from '../components/HostRemoveDialog'
import { HostTasksPanel } from '../components/HostTasksPanel'
import { QueryState } from '../components/QueryState'
import { ScheduleForm } from '../components/ScheduleForm'
import { TeamsCard } from '../components/TeamsCard'
import { ApiKeysCard } from '../components/ApiKeysCard'
import { UsersCard } from '../components/UsersCard'
import { TotpCard } from '../components/TotpCard'
import { SessionsCard } from '../components/SessionsCard'
import { TrustedDevicesCard } from '../components/TrustedDevicesCard'
import { UpdateCard } from '../components/UpdateCard'
import { Button } from '../components/ui/button'
import { CardLoadingOverlay } from '../components/ui/card-loading-overlay'
import { Skeleton, SkeletonGroup, SkeletonTable } from '../components/ui/skeleton'
import { useTeams } from '../api/teams'

export const settingsRoute = createRoute({
  getParentRoute: () => shellRoute,
  path: '/settings',
  component: SettingsPage,
})

type HostRow = { id: number; name: string; address: string; status: string; pve_version: string | null;
                node_shell_enabled: boolean; team_id: number | null }

function Card({ title, children, action }: { title: string; children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <section className="rounded-card border border-line-soft bg-panel p-5">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="font-display text-[15px] font-semibold">{title}</h2>{action}
      </div>
      {children}
    </section>
  )
}

export function SchedulesCard() {
  const qc = useQueryClient()
  const ent = useEntitlements()
  const schedules = useSchedules()
  const [adding, setAdding] = useState(false)
  // Wait for the first entitlements fetch before deciding (alerts.tsx
  // precedent), POST/PATCH /schedules require sched.windows, so offering
  // "New schedule"/"Run now" to everyone flashes controls that always 403.
  const windowsAllowed = ent.data != null && ent.has('sched.windows')

  const toggle = useMutation({
    mutationFn: (s: ScheduleRow) => api(`/schedules/${s.id}`, {
      method: 'PATCH', body: JSON.stringify({ enabled: !s.enabled }),
    }),
    onError: () => notify.error('Could not update that schedule, try again.'),
    onSettled: () => qc.invalidateQueries({ queryKey: ['schedules'] }),
  })
  const runNow = useMutation({
    mutationFn: (id: number) => api(`/schedules/${id}/run`, { method: 'POST' }),
    onSuccess: () => notify.success('Started, follow it on the Hosts page.'),
    onError: () => notify.error('Could not start that job, try again.'),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ['schedules'] })
      qc.invalidateQueries({ queryKey: ['jobs'] })
    },
  })
  const remove = useMutation({
    mutationFn: (id: number) => api(`/schedules/${id}`, { method: 'DELETE' }),
    onError: () => notify.error('Could not remove that schedule, try again.'),
    onSettled: () => qc.invalidateQueries({ queryKey: ['schedules'] }),
  })

  return (
    <Card title="Schedules"
          action={windowsAllowed && (
            <Button variant="ghost" onClick={() => setAdding(a => !a)}>
              {adding ? 'Close' : 'New schedule'}
            </Button>
          )}>
      <QueryState query={schedules}
                  loading={<SkeletonGroup label="Loading schedules">
                    {/* Name, Runs, Cron, Next, State, and the row actions. */}
                    <SkeletonTable rows={3} cols={['w-28', 'w-24', 'w-20', 'w-36', 'w-16', 'w-28']} />
                  </SkeletonGroup>}
                  emptyTitle="No schedules yet"
                  emptyNote="Add one for nightly backups or an auto-update window."
                  errorTitle="Schedules not readable"
                  errorNote="Proxploy could not reach the backend to list your schedules.">
        {(rows) => (
          <table className="w-full text-left text-[13px]">
            <thead><tr className="text-[10.5px] uppercase tracking-wide text-text-3">
              <th className="pb-2">Name</th><th>Runs</th><th>Cron</th><th>Next</th>
              <th>State</th><th /></tr></thead>
            <tbody>
              {rows.map(s => (
                <tr key={s.id} className="border-t border-line-soft hover:bg-panel-2">
                  <td className="py-2">
                    {s.name}
                    {s.created_by == null && (
                      <span className="ml-2 rounded-tile bg-panel-2 px-1.5 py-0.5
                                       font-mono text-[10px] uppercase text-text-3">
                        system
                      </span>
                    )}
                  </td>
                  {/* The job kind read as a name, not as the raw identifier.
                      Monospace went with it: that face was signalling "this is
                      a machine value", which stopped being true. The raw kind
                      is still what the API returns and what the backend keys
                      on, it is just not what this column is for.

                      actionLabel with no status, which is the whole label:
                      the labels are neutral now, so "Backup Run" is both what
                      this schedule runs and what a finished row is called.
                      jobKindLabel existed only to dodge the past-tense map. */}
                  <td className="text-[12px] text-text-2">{actionLabel(s.job_kind)}</td>
                  <td className="font-mono text-[12px] text-text-2">{s.cron}</td>
                  <td className="font-mono text-[11.5px] text-text-3">
                    {s.next_run_at ? new Date(s.next_run_at).toLocaleString() : 'unknown'}
                    <span className="ml-1">{s.timezone}</span>
                  </td>
                  <td className={s.enabled ? 'text-green' : 'text-text-3'}>
                    {s.enabled ? 'enabled' : 'disabled'}
                  </td>
                  <td className="py-2 text-right whitespace-nowrap">
                    {windowsAllowed && (
                      <Button variant="ghost" className="px-2 py-1 text-[11px]"
                              disabled={runNow.isPending}
                              onClick={() => runNow.mutate(s.id)}>Run now</Button>
                    )}
                    <Button variant="ghost" className="ml-2 px-2 py-1 text-[11px]"
                            disabled={toggle.isPending}
                            onClick={() => toggle.mutate(s)}>
                      {s.enabled ? 'Disable' : 'Enable'}
                    </Button>
                    <Button variant="danger" className="ml-2 px-2 py-1 text-[11px]"
                            onClick={() => {
                              if (window.confirm(`Remove schedule "${s.name}"?`)) {
                                remove.mutate(s.id)
                              }
                            }}>Remove</Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </QueryState>
      {adding && <div className="mt-4 border-t border-line-soft pt-4">
        <ScheduleForm onSaved={() => setAdding(false)} />
      </div>}
    </Card>
  )
}

/** Which enrolled host, if any, Proxploy itself runs on (PXP-33). Onboarding
 *  asks this once for a new install; an install that already finished
 *  onboarding before this existed has no other prompt, so it lives here too.
 *  "None of these" is a real, storable answer: not every install manages the
 *  host it runs on, and self-detection already fails open (never blocks) when
 *  nothing is recorded. */
function SelfHostRow({ hosts }: { hosts: HostRow[] }) {
  const qc = useQueryClient()
  const settings = useQuery({
    queryKey: ['settings'],
    queryFn: () => api<Record<string, unknown>>('/settings'),
  })
  const answered = settings.data != null
    && Object.prototype.hasOwnProperty.call(settings.data, 'self.host_id')
  const current = settings.data?.['self.host_id']
  const setSelfHost = useMutation({
    mutationFn: (hostId: number | null) =>
      api('/hosts/self', { method: 'PUT', body: JSON.stringify({ host_id: hostId }) }),
    onError: () => notify.error('Could not save that, try again.'),
    onSettled: () => qc.invalidateQueries({ queryKey: ['settings'] }),
  })

  if (settings.isPending) return null

  return (
    <div className="mb-4 flex flex-wrap items-center gap-2 rounded-ctl border
                    border-line-soft bg-panel-2 px-3 py-2 text-[12.5px]">
      <span className="text-text-2">
        Which of these hosts is Proxploy itself running on?
      </span>
      <select aria-label="Proxploy's own host"
        value={typeof current === 'number' ? String(current) : ''}
        disabled={setSelfHost.isPending}
        onChange={(e) => {
          const v = e.target.value
          setSelfHost.mutate(v ? Number(v) : null)
        }}
        className="rounded-ctl border border-line bg-panel px-2 py-1 text-[11.5px] text-text">
        <option value="">None of these</option>
        {hosts.map(h => <option key={h.id} value={h.id}>{h.name}</option>)}
      </select>
      {!answered && <span className="text-text-3">Not answered yet</span>}
    </div>
  )
}

export function SettingsPage() {
  const ent = useEntitlements()
  const { tier, grace, clockSkew } = ent
  const qc = useQueryClient()
  const [adding, setAdding] = useState(false)
  const hosts = useQuery({ queryKey: ['hosts'], queryFn: () => api<HostRow[]>('/hosts') })
  // The only editable host field (doc 08 §9's deliberate second, admin-only
  // opt-in gate on top of RBAC), NodeDetailPage's node-shell section reads
  // this same value, so invalidating the 'hosts' query key here (a prefix
  // match in TanStack Query v5) keeps both in sync without a second fetch.
  const toggleNodeShell = useMutation({
    mutationFn: (h: HostRow) => api(`/hosts/${h.id}`, {
      method: 'PATCH', body: JSON.stringify({ node_shell_enabled: !h.node_shell_enabled }),
    }),
    onError: () => notify.error('Could not update node shell setting, try again.'),
    onSettled: () => qc.invalidateQueries({ queryKey: ['hosts'] }),
  })

  // Host lifecycle ops (PXP-17): sync is synchronous despite the route name
  // (it runs a poller cycle inline and can take a while), tracked per host by
  // comparing the pending mutation's own variables rather than a separate
  // "which host" state.
  const [editingHost, setEditingHost] = useState<HostRow | null>(null)
  const [removingHost, setRemovingHost] = useState<HostRow | null>(null)
  const [tasksHostId, setTasksHostId] = useState<number | null>(null)
  const syncHost = useMutation({
    mutationFn: (h: HostRow) => api<{ id: number; status: string; last_seen_at: string | null; events: number }>(
      `/hosts/${h.id}/sync`, { method: 'POST' }),
    onSuccess: (r) => notify.success('Synced.', { description: `${r.events} event(s) applied.` }),
    onError: (e) => notify.error(apiErrorDetail(e, 'Sync failed, try again.')),
    onSettled: () => qc.invalidateQueries({ queryKey: ['hosts'] }),
  })

  // Both host reads return team_id, so this select shows the host's CURRENT
  // team rather than being a write-only reassignment control. Same teams.rbac gate as
  // TeamsCard: every /teams route requires it, so fetching before the first
  // entitlements resolve would 403 for every plan, and TanStack Query
  // dedupes this against TeamsCard's identical ['teams'] query.
  const teamsAllowed = ent.data != null && ent.has('teams.rbac')
  const teams = useTeams(teamsAllowed)
  const assignTeam = useMutation({
    mutationFn: ({ host, teamId }: { host: HostRow; teamId: number | null }) =>
      api(`/hosts/${host.id}`, {
        method: 'PATCH',
        // teamId null is sent, not dropped: the route reads model_fields_set,
        // so an explicit null is what unassigns and an omitted key means
        // "leave the team alone".
        body: JSON.stringify({ node_shell_enabled: host.node_shell_enabled,
                               team_id: teamId }),
      }),
    onError: () => notify.error('Could not assign that host to a team, try again.'),
    onSettled: () => qc.invalidateQueries({ queryKey: ['hosts'] }),
  })

  // Wait for the first entitlements fetch before deciding, `has()` defaults
  // to false until then, which would 403 the query and open an "Add channel"
  // form that always errors for the sliver of a second before the flag
  // resolves true.
  const channelsAllowed = ent.data != null && ent.has('notify.channels')
  const [addingChannel, setAddingChannel] = useState(false)
  const channels = useQuery({
    queryKey: ['notifications', 'channels'],
    queryFn: () => api<ChannelRow[]>('/notifications/channels'),
    enabled: channelsAllowed,
  })
  const testChannel = useMutation({
    mutationFn: (id: number) =>
      api<{ sent: boolean }>(`/notifications/channels/${id}/test`, { method: 'POST' }),
    onSuccess: (r) => notify[r.sent ? 'success' : 'error'](
      r.sent ? 'Test notification sent' : 'Channel unreachable'),
    onSettled: () => qc.invalidateQueries({ queryKey: ['notifications', 'channels'] }),
  })
  const deleteChannel = useMutation({
    mutationFn: (id: number) =>
      api(`/notifications/channels/${id}`, { method: 'DELETE' }),
    onError: () => notify.error('Could not remove that channel, try again.'),
    onSettled: () => qc.invalidateQueries({ queryKey: ['notifications', 'channels'] }),
  })
  const toggleChannel = useMutation({
    mutationFn: (ch: ChannelRow) =>
      api(`/notifications/channels/${ch.id}`, {
        method: 'PATCH', body: JSON.stringify({ enabled: !ch.enabled }),
      }),
    onError: () => notify.error('Could not update that channel, try again.'),
    onSettled: () => qc.invalidateQueries({ queryKey: ['notifications', 'channels'] }),
  })
  const removeChannel = (ch: ChannelRow) => {
    // The URL is genuinely unrecoverable once deleted (never shown again
    // after creation), one misclick next to Test would otherwise cost a
    // bot token with no undo.
    if (window.confirm(`Remove notification channel "${ch.name}"? This cannot be undone.`)) {
      deleteChannel.mutate(ch.id)
    }
  }

  return (
    <div className="space-y-5">
      <h1 className="font-display text-[22px] font-semibold">Settings</h1>

      <Card title="Plan">
        {/* api/hooks.ts defaults tier to 'builtin' because failing closed is
            the right security answer, but printing that default as a sentence
            told a paid installation it was on the free plan for the length of
            the fetch, and kept saying so if the fetch failed. TierPill, which
            this page's own topbar link points at, has said the same thing in
            a comment since it was written. `unknown` is what separates "not
            entitled" from "could not check". */}
        {ent.isPending ? (
          <SkeletonGroup label="Checking your plan">
            <Skeleton className="h-[19px] w-72" />
          </SkeletonGroup>
        ) : ent.unknown ? (
          <p className="text-[13.5px] text-text-2">
            Could not check your plan, try reloading.
          </p>
        ) : (
          <p className="text-[13.5px] text-text-2">
            <span className="font-mono text-amber">{tier === 'builtin' ? 'FREE' : tier.toUpperCase()}</span>
            {', '}all features are enabled. Licensing is dormant; entering a license key
            activates against the Proxploy licensing service.
            {grace?.in_grace && <span className="text-amber"> License refresh failing, working offline until {grace.grace_until}.</span>}
          </p>
        )}
        {clockSkew && (
          <p className="mt-2 text-[13.5px] text-amber">
            This machine&apos;s clock looks wrong. Fix the system time; entitlement checks depend on it.
          </p>
        )}
      </Card>

      <Card title="Hosts" action={<Button variant="ghost" onClick={() => setAdding(a => !a)}>{adding ? 'Close' : 'Add host'}</Button>}>
        {hosts.data && hosts.data.length > 0 && <SelfHostRow hosts={hosts.data} />}
        <QueryState query={hosts}
                    // Wrapped in the same overflow-x-auto the loaded branch
                    // uses, and the same min-w: seven columns do not fit a
                    // narrow card either way, and a placeholder that fits
                    // where the table will not is a placeholder of the wrong
                    // width.
                    loading={<SkeletonGroup label="Loading hosts" className="overflow-x-auto">
                      <div className="min-w-[620px]">
                        {/* Host, Address, PVE, Status, Node shell, Team, actions. */}
                        <SkeletonTable rows={2}
                          cols={['w-24', 'w-32', 'w-16', 'w-20', 'w-24', 'w-24', 'w-40']} />
                      </div>
                    </SkeletonGroup>}
                    emptyTitle="No hosts yet."
                    emptyNote=""
                    errorTitle="Hosts not readable"
                    errorNote="Proxploy could not reach the backend to list your hosts.">
          {(rows) => (
            // Seven columns plus four action buttons overflow a narrow card, and a
            // table that shrinks to fit collides its own headers. Scroll instead.
            <div className="overflow-x-auto">
            <table className="w-full min-w-[620px] text-left text-[13px]">
              <thead><tr className="whitespace-nowrap text-[10.5px] uppercase tracking-wide text-text-3">
                <th className="pb-2 pr-4">Host</th><th className="pr-4">Address</th><th className="pr-4">PVE</th><th className="pr-4">Status</th><th className="pr-4">Node shell</th><th className="pr-4">Team</th><th /></tr></thead>
              <tbody>
                {rows.map(h => (
                  <Fragment key={h.id}>
                    <tr className="border-t border-line-soft hover:bg-panel-2">
                      <td className="py-2 pr-4 font-mono">{h.name}</td>
                      <td className="pr-4 font-mono text-text-2">{h.address}</td>
                      <td className="pr-4 text-text-2">{h.pve_version ?? 'unknown'}</td>
                      <td className="pr-4"><span className={h.status === 'connected' ? 'text-green' : 'text-red'}>{h.status}</span></td>
                      <td className="pr-4">
                        <label className="inline-flex items-center gap-1.5">
                          <input type="checkbox" checked={h.node_shell_enabled}
                            disabled={toggleNodeShell.isPending}
                            onChange={() => toggleNodeShell.mutate(h)} />
                          <span className="text-[11px] text-text-3">
                            {h.node_shell_enabled ? 'enabled' : 'disabled'}
                          </span>
                        </label>
                      </td>
                      <td className="pr-4">
                        {teamsAllowed ? (
                          // Until GET /teams lands there is no option matching a
                          // host's team_id, so the browser falls back to the
                          // first one and this column read "Unassigned" for
                          // every host, including the assigned ones. `isLoading`
                          // rather than `isPending` because useTeams is
                          // entitlement-gated and a disabled query stays pending
                          // for ever.
                          <select aria-label={`team for ${h.name}`} value={h.team_id ?? ''}
                            disabled={assignTeam.isPending || teams.isLoading}
                            onChange={(e) => {
                              const v = e.target.value
                              assignTeam.mutate({ host: h, teamId: v ? Number(v) : null })
                            }}
                            className="rounded-ctl border border-line bg-panel px-2 py-1 text-[11.5px] text-text">
                            {teams.isLoading
                              ? <option value="">Loading teams…</option>
                              : <option value="">Unassigned</option>}
                            {(teams.data ?? []).map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
                          </select>
                        ) : <span className="text-text-3">n/a</span>}
                      </td>
                      <td className="py-2">
                        <div className="flex flex-wrap justify-end gap-1.5">
                          <Button variant="ghost" className="px-2 py-1 text-[11px]"
                            disabled={syncHost.isPending && syncHost.variables?.id === h.id}
                            onClick={() => syncHost.mutate(h)}>
                            {syncHost.isPending && syncHost.variables?.id === h.id ? 'Syncing…' : 'Sync'}
                          </Button>
                          <Button variant="ghost" className="px-2 py-1 text-[11px]"
                            onClick={() => setEditingHost(h)}>Edit</Button>
                          <Button variant="ghost" className="px-2 py-1 text-[11px]"
                            onClick={() => setTasksHostId(id => id === h.id ? null : h.id)}>
                            {tasksHostId === h.id ? 'Hide tasks' : 'Tasks'}
                          </Button>
                          <Button variant="danger" className="px-2 py-1 text-[11px]"
                            onClick={() => setRemovingHost(h)}>Remove</Button>
                        </div>
                      </td>
                    </tr>
                    {tasksHostId === h.id && (
                      <tr className="border-t border-line-soft bg-panel-2/40">
                        <td colSpan={7}><HostTasksPanel hostId={h.id} /></td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
            </div>
          )}
        </QueryState>
        {adding && <div className="mt-4 border-t border-line-soft pt-4">
          <HostForm onCreated={() => { setAdding(false); qc.invalidateQueries({ queryKey: ['hosts'] }) }} />
        </div>}
        {editingHost && (
          <HostEditDialog hostId={editingHost.id} host={editingHost}
            onClose={() => setEditingHost(null)} />
        )}
        {removingHost && (
          <HostRemoveDialog hostId={removingHost.id} hostName={removingHost.name}
            onClose={() => setRemovingHost(null)}
            onRemoved={() => setRemovingHost(null)} />
        )}
      </Card>

      {/* This is the card's own entitlement-gated first load: not yet known
          whether the plan includes notify.channels, then the channels list's
          own first fetch. `isPending`, not `isFetching`, so this stays quiet
          on the invalidation refetches the mutations below trigger. */}
      <CardLoadingOverlay state={{ firstLoad: ent.isPending || (channelsAllowed && channels.isPending) }}>
      <Card title="Notifications"
            action={channelsAllowed && <Button variant="ghost" onClick={() => setAddingChannel(a => !a)}>
              {addingChannel ? 'Close' : 'Add channel'}
            </Button>}>
        {ent.data != null && !channelsAllowed && (
          <p className="text-[12.5px] text-text-3">Not included in your plan.</p>
        )}
        {channelsAllowed && (
          <>
            <QueryState query={channels}
                        // The overlay above already veils the card for
                        // channels.isPending; suppress the inner placeholder
                        // so the two don't stack.
                        loading={<></>}
                        emptyTitle="No channels yet"
                        emptyNote="Add one to get told when a job fails."
                        errorTitle="Channels not readable"
                        errorNote="Proxploy could not reach the backend to list your notification channels.">
              {(rows) => (
                <table className="w-full text-left text-[13px]">
                  <thead><tr className="text-[10.5px] uppercase tracking-wide text-text-3">
                    <th className="pb-2">Name</th><th>Kind</th><th>Events</th><th>State</th><th /></tr></thead>
                  <tbody>
                    {rows.map(ch => (
                      <tr key={ch.id} className="border-t border-line-soft hover:bg-panel-2">
                        <td className="py-2">{ch.name}</td>
                        <td className="font-mono text-text-2">{ch.kind}</td>
                        <td className="font-mono text-[11.5px] text-text-3">
                          {ch.events.length ? ch.events.join(', ') : 'all events'}
                        </td>
                        <td className={ch.enabled ? 'text-green' : 'text-text-3'}>
                          {ch.enabled ? 'enabled' : 'disabled'}
                        </td>
                        <td className="py-2 text-right">
                          <Button variant="ghost" className="px-2 py-1 text-[11px]"
                                  disabled={toggleChannel.isPending}
                                  onClick={() => toggleChannel.mutate(ch)}>
                            {ch.enabled ? 'Disable' : 'Enable'}
                          </Button>
                          <Button variant="ghost" className="ml-2 px-2 py-1 text-[11px]"
                                  onClick={() => testChannel.mutate(ch.id)}>Test</Button>
                          <Button variant="danger" className="ml-2 px-2 py-1 text-[11px]"
                                  onClick={() => removeChannel(ch)}>Remove</Button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </QueryState>
            {addingChannel && <div className="mt-4 border-t border-line-soft pt-4">
              <ChannelForm onSaved={() => {
                setAddingChannel(false)
                qc.invalidateQueries({ queryKey: ['notifications', 'channels'] })
              }} />
            </div>}
          </>
        )}
      </Card>
      </CardLoadingOverlay>

      <SchedulesCard />

      <TeamsCard />

      <UsersCard />

      <ApiKeysCard />

      <TotpCard />

      <SessionsCard />

      <TrustedDevicesCard />

      <UpdateCard />
    </div>
  )
}
