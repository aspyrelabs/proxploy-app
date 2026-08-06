import { useState } from 'react'
import { createRoute, Link } from '@tanstack/react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { shellRoute } from './shell'
import { api } from '../api/client'
import { useEntitlements } from '../api/hooks'
import { useSchedules } from '../api/schedules'
import type { ScheduleRow } from '../api/schedules'
import { ChannelForm } from '../components/ChannelForm'
import type { ChannelRow } from '../components/ChannelForm'
import { HostForm } from '../components/HostForm'
import { QueryState } from '../components/QueryState'
import { ScheduleForm } from '../components/ScheduleForm'
import { TeamsCard } from '../components/TeamsCard'
import { ApiKeysCard } from '../components/ApiKeysCard'
import { TotpCard } from '../components/TotpCard'
import { SessionsCard } from '../components/SessionsCard'
import { UpdateCard } from '../components/UpdateCard'
import { Button } from '../components/ui/button'
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
  // precedent) — POST/PATCH /schedules require sched.windows, so offering
  // "New schedule"/"Run now" to everyone flashes controls that always 403.
  const windowsAllowed = ent.data != null && ent.has('sched.windows')

  const toggle = useMutation({
    mutationFn: (s: ScheduleRow) => api(`/schedules/${s.id}`, {
      method: 'PATCH', body: JSON.stringify({ enabled: !s.enabled }),
    }),
    onError: () => toast.error('Could not update that schedule — try again.'),
    onSettled: () => qc.invalidateQueries({ queryKey: ['schedules'] }),
  })
  const runNow = useMutation({
    mutationFn: (id: number) => api(`/schedules/${id}/run`, { method: 'POST' }),
    onSuccess: () => toast.success('Started — follow it in the activity drawer.'),
    onError: () => toast.error('Could not start that job — try again.'),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ['schedules'] })
      qc.invalidateQueries({ queryKey: ['jobs'] })
    },
  })
  const remove = useMutation({
    mutationFn: (id: number) => api(`/schedules/${id}`, { method: 'DELETE' }),
    onError: () => toast.error('Could not remove that schedule — try again.'),
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
                  <td className="font-mono text-[12px] text-text-2">{s.job_kind}</td>
                  <td className="font-mono text-[12px] text-text-2">{s.cron}</td>
                  <td className="font-mono text-[11.5px] text-text-3">
                    {s.next_run_at ? new Date(s.next_run_at).toLocaleString() : '—'}
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

export function SettingsPage() {
  const ent = useEntitlements()
  const { tier, grace } = ent
  const qc = useQueryClient()
  const [adding, setAdding] = useState(false)
  const hosts = useQuery({ queryKey: ['hosts'], queryFn: () => api<HostRow[]>('/hosts') })
  // The only editable host field (doc 08 §9's deliberate second, admin-only
  // opt-in gate on top of RBAC) — NodeDetailPage's node-shell section reads
  // this same value, so invalidating the 'hosts' query key here (a prefix
  // match in TanStack Query v5) keeps both in sync without a second fetch.
  const toggleNodeShell = useMutation({
    mutationFn: (h: HostRow) => api(`/hosts/${h.id}`, {
      method: 'PATCH', body: JSON.stringify({ node_shell_enabled: !h.node_shell_enabled }),
    }),
    onError: () => toast.error('Could not update node shell setting — try again.'),
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
    mutationFn: ({ host, teamId }: { host: HostRow; teamId: number }) => api(`/hosts/${host.id}`, {
      method: 'PATCH',
      body: JSON.stringify({ node_shell_enabled: host.node_shell_enabled, team_id: teamId }),
    }),
    onError: () => toast.error('Could not assign that host to a team — try again.'),
    onSettled: () => qc.invalidateQueries({ queryKey: ['hosts'] }),
  })

  // Wait for the first entitlements fetch before deciding — `has()` defaults
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
    onSuccess: (r) => toast[r.sent ? 'success' : 'error'](
      r.sent ? 'Test notification sent' : 'Channel unreachable'),
    onSettled: () => qc.invalidateQueries({ queryKey: ['notifications', 'channels'] }),
  })
  const deleteChannel = useMutation({
    mutationFn: (id: number) =>
      api(`/notifications/channels/${id}`, { method: 'DELETE' }),
    onError: () => toast.error('Could not remove that channel — try again.'),
    onSettled: () => qc.invalidateQueries({ queryKey: ['notifications', 'channels'] }),
  })
  const toggleChannel = useMutation({
    mutationFn: (ch: ChannelRow) =>
      api(`/notifications/channels/${ch.id}`, {
        method: 'PATCH', body: JSON.stringify({ enabled: !ch.enabled }),
      }),
    onError: () => toast.error('Could not update that channel — try again.'),
    onSettled: () => qc.invalidateQueries({ queryKey: ['notifications', 'channels'] }),
  })
  const removeChannel = (ch: ChannelRow) => {
    // The URL is genuinely unrecoverable once deleted (never shown again
    // after creation) — one misclick next to Test would otherwise cost a
    // bot token with no undo.
    if (window.confirm(`Remove notification channel "${ch.name}"? This cannot be undone.`)) {
      deleteChannel.mutate(ch.id)
    }
  }

  return (
    <div className="max-w-3xl space-y-5">
      <h1 className="font-display text-[22px] font-semibold">Settings</h1>

      <Card title="Plan">
        <p className="text-[13.5px] text-text-2">
          <span className="font-mono text-amber">{tier === 'builtin' ? 'FREE' : tier.toUpperCase()}</span>
          {' — '}all features are enabled. Licensing is dormant; entering a license key
          activates against the Proxploy licensing service.
          {grace?.in_grace && <span className="text-amber"> License refresh failing — working offline until {grace.grace_until}.</span>}
        </p>
      </Card>

      <Card title="Hosts" action={<Button variant="ghost" onClick={() => setAdding(a => !a)}>{adding ? 'Close' : 'Add host'}</Button>}>
        <QueryState query={hosts}
                    emptyTitle="No hosts yet."
                    emptyNote=""
                    errorTitle="Hosts not readable"
                    errorNote="Proxploy could not reach the backend to list your hosts.">
          {(rows) => (
            <table className="w-full text-left text-[13px]">
              <thead><tr className="text-[10.5px] uppercase tracking-wide text-text-3">
                <th className="pb-2">Host</th><th>Address</th><th>PVE</th><th>Status</th><th>Node shell</th><th>Team</th></tr></thead>
              <tbody>
                {rows.map(h => (
                  <tr key={h.id} className="border-t border-line-soft hover:bg-panel-2">
                    <td className="py-2 font-mono">{h.name}</td>
                    <td className="font-mono text-text-2">{h.address}</td>
                    <td className="text-text-2">{h.pve_version ?? '—'}</td>
                    <td><span className={h.status === 'connected' ? 'text-green' : 'text-red'}>{h.status}</span></td>
                    <td>
                      <label className="inline-flex items-center gap-1.5">
                        <input type="checkbox" checked={h.node_shell_enabled}
                          disabled={toggleNodeShell.isPending}
                          onChange={() => toggleNodeShell.mutate(h)} />
                        <span className="text-[11px] text-text-3">
                          {h.node_shell_enabled ? 'enabled' : 'disabled'}
                        </span>
                      </label>
                    </td>
                    <td>
                      {teamsAllowed ? (
                        <select aria-label={`team for ${h.name}`} value={h.team_id ?? ''}
                          disabled={assignTeam.isPending}
                          onChange={(e) => {
                            const v = e.target.value
                            if (v) assignTeam.mutate({ host: h, teamId: Number(v) })
                          }}
                          className="rounded-ctl border border-line bg-panel px-2 py-1 text-[11.5px] text-text">
                          <option value="">Unassigned</option>
                          {(teams.data ?? []).map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
                        </select>
                      ) : <span className="text-text-3">—</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </QueryState>
        {adding && <div className="mt-4 border-t border-line-soft pt-4">
          <HostForm onCreated={() => { setAdding(false); qc.invalidateQueries({ queryKey: ['hosts'] }) }} />
        </div>}
      </Card>

      <Card title="Notifications"
            action={channelsAllowed && <Button variant="ghost" onClick={() => setAddingChannel(a => !a)}>
              {addingChannel ? 'Close' : 'Add channel'}
            </Button>}>
        {!channelsAllowed ? (
          <p className="text-[12.5px] text-text-3">
            {ent.data == null ? 'Loading…' : 'Not included in your plan.'}
          </p>
        ) : (
          <>
            <QueryState query={channels}
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

      <SchedulesCard />

      <TeamsCard />

      <ApiKeysCard />

      <TotpCard />

      <SessionsCard />

      <UpdateCard />

      <Card title="General">
        <p className="text-[12.5px] text-text-3">
          Auto-update windows, scheduled backups and catalog sync are all
          schedules — add them above. Alert rules live on the{' '}
          <Link to={'/alerts' as never} className="text-amber">Alerts</Link> page.
        </p>
      </Card>
    </div>
  )
}
