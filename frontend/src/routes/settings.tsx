import { Fragment, useState } from 'react'
import type { ReactNode } from 'react'
import * as DropdownMenu from '@radix-ui/react-dropdown-menu'
import { Link, createRoute, useSearch } from '@tanstack/react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { shellRoute } from './shell'
import { api, apiErrorDetail } from '../api/client'
import { notify } from '../lib/notify'
import { useEntitlements } from '../api/hooks'
import { LicenseCard } from '../components/LicenseCard'
import { BACKUP_KINDS, useSchedules } from '../api/schedules'
import { actionLabel, statusLabel } from '../lib/activityDisplay'
import type { ScheduleRow } from '../api/schedules'
import { SCHED_COL, TABLE_MIN, TABLE_SCROLL, TablePager, usePaged } from '../components/TablePager'
import { ButtonGroup, ButtonGroupSeparator } from '../components/ui/button-group'
import { RowActionsMenu } from '../components/ui/row-actions'
import { ScheduleRunsDialog } from '../components/ScheduleRunsDialog'
import { ChannelForm } from '../components/ChannelForm'
import { ChannelEditForm } from '../components/ChannelEditForm'
import { EventsMatrix } from '../components/EventsMatrix'
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
import { AccountCard } from '../components/AccountCard'
import { PasswordCard } from '../components/PasswordCard'
import { TotpCard } from '../components/TotpCard'
import { ConsoleCard } from '../components/ConsoleCard'
import { SessionsCard } from '../components/SessionsCard'
import { TrustedDevicesCard } from '../components/TrustedDevicesCard'
import { UpdateCard } from '../components/UpdateCard'
import { Button } from '../components/ui/button'
import { Icon } from '../components/ui/icon'
import { CardLoadingOverlay } from '../components/ui/card-loading-overlay'
import { Skeleton, SkeletonGroup, SkeletonTable } from '../components/ui/skeleton'
import { useTeams } from '../api/teams'
// The rail, the ?section= contract and the command palette all read the same
// table; it lives in lib/ so CommandPalette can import it without a cycle.
import {
  DEFAULT_SETTINGS_SECTION, SETTINGS_SECTIONS, SETTINGS_SECTION_IDS,
  resolveSettingsSection,
} from '../lib/settings-sections'

export const settingsRoute = createRoute({
  getParentRoute: () => shellRoute,
  path: '/settings',
  // Same shape apps.tsx and vms.tsx use. An unrecognised ?section= falls back
  // to Hosts rather than rendering an empty pane.
  validateSearch: (s: Record<string, unknown>) => ({
    section: resolveSettingsSection(s.section),
  }),
  component: SettingsPage,
})

/** The section list. Same vocabulary as SidebarNav.tsx but borderless
 *  and inside the page, so it reads as part of Settings rather than as a
 *  second app rail. Horizontal and scrollable below `md`.
 */
function SectionRail({ active }: { active: string }) {
  return (
    <nav aria-label="Settings sections"
         className="-mx-1 flex shrink-0 gap-1 overflow-x-auto px-1 pb-1
                    md:mx-0 md:w-[188px] md:flex-col md:gap-0 md:overflow-visible
                    md:px-0 md:pb-0 md:sticky md:top-20 md:self-start">
      {SETTINGS_SECTIONS.map(g => (
        <Fragment key={g.group}>
          <div className="hidden px-3 pb-1 pt-4 text-[10.5px] font-semibold uppercase
                          tracking-[.08em] text-text-3 first:pt-0 md:block">
            {g.group}
          </div>
          {g.items.map(i => (
            <Link key={i.id} to="/settings" search={{ section: i.id }}
                  aria-current={i.id === active ? 'page' : undefined}
                  className={`relative whitespace-nowrap rounded-tile px-3 py-2 text-[13.5px]
                              hover:bg-panel-2 hover:text-text ${i.id === active
                    ? 'bg-panel-2 text-text before:absolute before:left-0 before:top-1.5 '
                      + 'before:bottom-1.5 before:w-[3px] before:rounded before:bg-amber'
                    : 'text-text-2'}`}>
              {i.label}
            </Link>
          ))}
        </Fragment>
      ))}
    </nav>
  )
}

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

/**
 * Every schedule, or just the kinds one page owns: the Backups page shows
 * `backup.run` rows with `only`, so scheduled jobs are managed where they
 * are read. One card, one set of row actions.
 */
/** The schedules table, its own component so it can hold a hook called
 *  from an Async render prop. Ten to a page, same six column widths as
 *  the Recent backups table. */
function ScheduleTable({ rows, editing, setEditing, setAdding, windowsAllowed,
                        remove, runNow, toggle, renderEdit }: {
  rows: ScheduleRow[]
  renderEdit: (s: ScheduleRow) => ReactNode
  editing: ScheduleRow | null
  setEditing: (f: (e: ScheduleRow | null) => ScheduleRow | null) => void
  setAdding: (v: boolean) => void
  windowsAllowed: boolean
  remove: { mutate: (id: number) => void }
  runNow: { mutate: (id: number) => void; isPending: boolean }
  toggle: { mutate: (s: ScheduleRow) => void; isPending: boolean }
}) {
  const paged = usePaged(rows)
  const [viewingRuns, setViewingRuns] = useState<ScheduleRow | null>(null)
  return (
    <>
                <div className={TABLE_SCROLL}>
            <table className={`w-full ${TABLE_MIN} table-fixed text-left text-[13px] [&_td]:pr-4 [&_th]:pr-4`}>
            {SCHED_COL}
            <thead><tr className="text-[10.5px] uppercase tracking-wide text-text-3">
              <th className="pb-2">Name</th><th>Runs</th><th>Cron</th><th>Next</th>
              <th>State</th><th>Status</th><th /></tr></thead>
            <tbody>
              {paged.rows.map((s: ScheduleRow) => (
                <Fragment key={s.id}>
                <tr className="border-t border-line-soft hover:bg-panel-2">
                  <td className="truncate py-2" title={s.name}>
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
                  <td className="truncate font-mono text-[12px] text-text-2"
                      title={s.cron}>{s.cron}</td>
                  <td className="font-mono text-[11.5px] text-text-3">
                    {s.next_run_at ? (
                      <>
                        {new Date(s.next_run_at).toLocaleString()}
                        <span className="ml-1">{s.timezone}</span>
                      </>
                    ) : 'not scheduled'}
                  </td>
                  <td className={`truncate ${s.enabled ? 'text-green' : 'text-text-3'}`}>
                    {s.enabled ? 'enabled' : 'disabled'}
                  </td>
                  <td className={`truncate ${s.last_run == null ? 'text-text-3'
                      : s.last_run.status === 'succeeded' ? 'text-green'
                      : s.last_run.status === 'failed' ? 'text-red' : 'text-text-3'}`}
                      title={s.last_run?.status === 'failed' ? (s.last_run.error ?? undefined) : undefined}>
                    {s.last_run == null ? 'Never run' : statusLabel(s.last_run.status)}
                  </td>
                  <td className="py-2 text-right">
                    <ButtonGroup>
                      {windowsAllowed && (
                        <>
                          <Button size="sm" variant="ghost"
                                  disabled={runNow.isPending}
                                  onClick={() => runNow.mutate(s.id)}>Run now</Button>
                          <ButtonGroupSeparator />
                        </>
                      )}
                      <Button size="sm" variant="ghost"
                              onClick={() => setViewingRuns(s)}>Logs</Button>
                      <ButtonGroupSeparator />
                      <RowActionsMenu label={`More actions for ${s.name}`}
                        actions={[
                          { label: s.enabled ? 'Disable' : 'Enable',
                            icon: s.enabled ? 'pause' : 'play_arrow',
                            disabled: toggle.isPending,
                            onSelect: () => toggle.mutate(s) },
                          ...(windowsAllowed ? [{
                            label: editing?.id === s.id ? 'Close editor' : 'Edit',
                            icon: 'edit',
                            onSelect: () => {
                              setAdding(false)
                              setEditing((e) => (e?.id === s.id ? null : s))
                            },
                          }] : []),
                          { label: 'Remove', icon: 'delete', destructive: true,
                            onSelect: () => {
                              if (window.confirm(`Remove schedule "${s.name}"?`)) {
                                remove.mutate(s.id)
                              }
                            } },
                        ]} />
                    </ButtonGroup>
                  </td>
                </tr>
                <tr>
                  <td colSpan={7} className="p-0">
                    <div className={`grid transition-[grid-template-rows] duration-200 ease-out
                                     motion-reduce:transition-none ${editing?.id === s.id
                                       ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'}`}>
                      <div className="overflow-hidden">
                        {editing?.id === s.id && (
                          <div className="border-t border-line-soft px-1 py-4">
                            {renderEdit(s)}
                          </div>
                        )}
                      </div>
                    </div>
                  </td>
                </tr>
                </Fragment>
              ))}
            </tbody>
          </table>
          </div>
      <TablePager page={paged.page} pages={paged.pages} onPage={paged.setPage}
                  label="Scheduled jobs pages" />
      {viewingRuns && (
        <ScheduleRunsDialog schedule={viewingRuns} onClose={() => setViewingRuns(null)} />
      )}
    </>
  )
}

export function SchedulesCard({ only, exclude, title = 'Schedules', canAdd = true }:
  { only?: string[]; exclude?: string[]; title?: string; canAdd?: boolean } = {}) {
  const qc = useQueryClient()
  const ent = useEntitlements()
  const schedules = useSchedules()
  const [adding, setAdding] = useState(false)
  const [editing, setEditing] = useState<ScheduleRow | null>(null)
  // Wait for the first entitlements fetch before deciding. `has()` defaults
  // to false until then, which would 403 the query and open a form that always
  // errors.
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
    onSuccess: () => notify.success('Started. Track its progress in notifications.'),
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

  // `canAdd` is off on the Backups page, which already has "New job" in its
  // own header: two buttons opening the same form is a choice nobody has.
  return (
    <Card title={title}
          action={canAdd && windowsAllowed && (
            <Button variant="ghost"
                    onClick={() => { setEditing(null); setAdding(a => !a) }}>
              {adding ? 'Close' : 'New job'}
            </Button>
          )}>
      <QueryState query={schedules}
                  loading={<SkeletonGroup label="Loading schedules">
                    {/* Name, Runs, Cron, Next, State, and the row actions. */}
                    <SkeletonTable rows={3} cols={['w-28', 'w-24', 'w-20', 'w-36', 'w-16', 'w-28']} />
                  </SkeletonGroup>}
                  emptyTitle="No schedules yet"
                  emptyNote="Add one to refresh the app catalog or roll up metrics on a schedule."
                  errorTitle="Schedules not readable"
                  errorNote="Proxploy could not reach the backend to list your schedules.">
        {(all) => {
          const rows = only
            ? all.filter((s) => only.includes(s.job_kind))
            : exclude
              ? all.filter((s) => !exclude.includes(s.job_kind))
              : all
          return rows.length === 0 ? (
            <p className="text-[12.5px] text-text-3">
              No scheduled jobs yet, &quot;New job&quot;
              {' '}creates one.
            </p>
          ) : (
<ScheduleTable rows={rows} editing={editing} setEditing={setEditing}
                         setAdding={setAdding} windowsAllowed={windowsAllowed}
                         remove={remove} runNow={runNow} toggle={toggle}
                         renderEdit={(s) => (
                           <ScheduleForm key={s.id} existing={s} exclude={exclude}
                                         onSaved={() => { setAdding(false); setEditing(null) }}
                                         onCancel={() => setEditing(null)} />
                         )} />
          )
        }}
      </QueryState>
      {adding && (
        <div className="mt-4 border-t border-line-soft pt-4">
          <ScheduleForm key="new"
                        jobKind={only?.length === 1 ? only[0] : undefined}
                        exclude={exclude}
                        onSaved={() => { setAdding(false); setEditing(null) }}
                        onCancel={() => setAdding(false)} />
        </div>
      )}
    </Card>
  )
}

/** Which enrolled host, if any, Proxploy itself runs on. Onboarding
 *  asks this once for a new install; an existing install has no other
 *  prompt. "None of these" is a real, storable answer.
 */
// The same two class strings HostActionsMenu, VmActionsMenu and AppIconMenu
// share, destructive vocabulary included.
const itemCls = 'flex cursor-pointer items-center gap-2 px-3 py-2 text-[13px] text-text-2 '
             + 'outline-none data-[highlighted]:bg-panel-2 data-[highlighted]:text-text'
const destructiveItemCls = 'flex cursor-pointer items-center gap-2 border-t border-line-soft '
                         + 'px-3 py-2 text-[13px] text-red outline-none data-[highlighted]:bg-red-dim'

/**
 * Edit, Tasks and Remove for one enrolled host, behind one trigger.
 * Sync stays out here because it is the one with a pending state worth
 * watching and the action an operator repeats. Not HostActionsMenu:
 * that one carries Reboot and Power off. Same Radix primitive and class
 * strings, so they read as one family.
 */
function HostRowMenu({ name, onEdit, onTasks, onRemove, tasksOpen }: {
  name: string
  onEdit: () => void
  onTasks: () => void
  onRemove: () => void
  tasksOpen: boolean
}) {
  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <Button variant="ghost" size="icon-xs" aria-label={`Actions for ${name}`}>
          <Icon name="more_vert" />
        </Button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content align="end" sideOffset={8}
          className="z-50 w-48 overflow-hidden rounded-card border border-line bg-panel
                     shadow-[0_12px_32px_rgba(0,0,0,.35)]">
          <DropdownMenu.Item onSelect={onEdit} className={itemCls}>
            <Icon name="edit" size={16} /> Edit
          </DropdownMenu.Item>
          <DropdownMenu.Item onSelect={onTasks} className={itemCls}>
            <Icon name="fact_check" size={16} /> {tasksOpen ? 'Hide tasks' : 'Tasks'}
          </DropdownMenu.Item>
          <DropdownMenu.Item onSelect={onRemove} className={destructiveItemCls}>
            <Icon name="delete" size={16} /> Remove
          </DropdownMenu.Item>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  )
}

const selfRow = 'mb-4 flex flex-wrap items-center gap-2 rounded-ctl border '
  + 'border-line-soft bg-panel-2 px-3 py-2 text-[12.5px]'

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

  // The QUESTION is static; only the answer is in flight. Returning null
  // for the whole strip pushed every host row down when the answer arrived.
  // Same rule routes/network.tsx's Throughput card follows.
  if (settings.isPending) {
    return (
      <div className={selfRow}>
        <span className="text-text-2">
          Which of these hosts is Proxploy itself running on?
        </span>
        <SkeletonGroup label="Loading which host Proxploy runs on">
          {/* The select below: px-2 py-1 text-[11.5px] inside a 1px border, so
              8 + 2 + 11.5 * 1.45 = 27px, and rounded-ctl like the control. */}
          <Skeleton className="h-[27px] w-36 rounded-ctl" />
        </SkeletonGroup>
      </div>
    )
  }

  return (
    <div className={selfRow}>
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
  // `strict: false` matches apps.tsx: the component may be rendered without
  // a matched route above it.
  const search = useSearch({ strict: false }) as { section?: string }
  const active = search.section && SETTINGS_SECTION_IDS.has(search.section)
    ? search.section : DEFAULT_SETTINGS_SECTION
  const ent = useEntitlements()
  const { tier, grace, clockSkew } = ent
  const qc = useQueryClient()
  const [adding, setAdding] = useState(false)
  const hosts = useQuery({ queryKey: ['hosts'], queryFn: () => api<HostRow[]>('/hosts') })
  // The only editable host field, admin-only opt-in gate on top of RBAC.
  // NodeDetailPage's node-shell section reads this same value, so invalidating
  // the 'hosts' query key keeps both in sync.
  const toggleNodeShell = useMutation({
    mutationFn: (h: HostRow) => api(`/hosts/${h.id}`, {
      method: 'PATCH', body: JSON.stringify({ node_shell_enabled: !h.node_shell_enabled }),
    }),
    onError: () => notify.error('Could not update node shell setting, try again.'),
    onSettled: () => qc.invalidateQueries({ queryKey: ['hosts'] }),
  })

  // Host lifecycle ops: sync is synchronous despite the route name. Tracked
  // per host by comparing the pending mutation's own variables.
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
  // team. Same teams.rbac gate as TeamsCard; TanStack Query dedupes against
  // TeamsCard's identical ['teams'] query.
  const teamsAllowed = ent.data != null && ent.has('teams.rbac')
  const teams = useTeams(teamsAllowed)
  const assignTeam = useMutation({
    mutationFn: ({ host, teamId }: { host: HostRow; teamId: number | null }) =>
      api(`/hosts/${host.id}`, {
        method: 'PATCH',
        // teamId null is sent, not dropped: the route reads model_fields_set,
        // so an explicit null unassigns and an omitted key means "leave alone".
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
  const [editingChannel, setEditingChannel] = useState<number | null>(null)
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
    // The URL is genuinely unrecoverable once deleted, one misclick next to
    // Test would cost a bot token with no undo.
    if (window.confirm(`Remove notification channel "${ch.name}"? This cannot be undone.`)) {
      deleteChannel.mutate(ch.id)
    }
  }

  return (
    <div>
      {/* The one h1 stays on the page, not on the section: every card below
          already carries its own h2, so moving the title onto the section
          would leave the page with two headings for the same thing. */}
      <h1 className="mb-5 font-display text-[22px] font-semibold">Settings</h1>

      <div className="flex flex-col gap-4 md:flex-row md:gap-7">
        <SectionRail active={active} />

        <div className="min-w-0 flex-1 space-y-5">

      {active === 'plan' && <Card title="Plan">
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
          <div className="flex flex-col gap-3">
            <LicenseCard tier={tier === 'builtin' ? 'free' : tier}
                         licensed={tier !== 'builtin'} />
            {grace?.in_grace && (
              <p className="text-[13.5px] text-amber">
                License refresh failing, working offline until {grace.grace_until}.
              </p>
            )}
          </div>
        )}
        {clockSkew && (
          <p className="mt-2 text-[13.5px] text-amber">
            This machine&apos;s clock looks wrong. Fix the system time; entitlement checks depend on it.
          </p>
        )}
      </Card>}

      {active === 'hosts' && <Card title="Hosts" action={<Button variant="ghost" onClick={() => setAdding(a => !a)}>{adding ? 'Close' : 'Add host'}</Button>}>
        {hosts.data && hosts.data.length > 0 && <SelfHostRow hosts={hosts.data} />}
        <QueryState query={hosts}
                    // Wrapped in the same overflow-x-auto the loaded branch
                    // uses, and the same min-w: seven columns don't fit a
                    // narrow card either way.
                    loading={<SkeletonGroup label="Loading hosts" className="overflow-x-auto">
                      <div className="min-w-[860px]">
                        {/* Host, Address, PVE, Status, Node shell, Team, actions. */}
                        {/* Host, Address, PVE, Status, Node shell, Team, then
                            Sync and the row menu. */}
                        <SkeletonTable rows={2}
                          cols={['w-24', 'w-32', 'w-16', 'w-20', 'w-24', 'w-24', 'w-24']} />
                      </div>
                    </SkeletonGroup>}
                    emptyTitle="No hosts yet."
                    emptyNote=""
                    errorTitle="Hosts not readable"
                    errorNote="Proxploy could not reach the backend to list your hosts.">
          {(rows) => (
            <div className="overflow-x-auto">
            <table className="w-full min-w-[860px] text-left text-[13px]">
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
                          // host's team_id, so the browser falls back to the first
                          // one. `isLoading` rather than `isPending` because
                          // useTeams is entitlement-gated and a disabled query
                          // stays pending for ever.
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
                        {/* nowrap, not wrap: wrapping let the cell collapse
                            below the width four buttons actually need, so with
                            the section rail taking 216px the row stacked into
                            three lines instead of scrolling. The card's own
                            overflow-x-auto below is what handles a narrow
                            pane, and it can only do that if the cell reports
                            its real width. */}
                        <div className="flex flex-nowrap justify-end gap-1.5">
                          <Button size="sm" variant="ghost"
                            disabled={syncHost.isPending && syncHost.variables?.id === h.id}
                            onClick={() => syncHost.mutate(h)}>
                            {syncHost.isPending && syncHost.variables?.id === h.id ? 'Syncing…' : 'Sync'}
                          </Button>
                          <HostRowMenu name={h.name} tasksOpen={tasksHostId === h.id}
                            onEdit={() => setEditingHost(h)}
                            onTasks={() => setTasksHostId(id => id === h.id ? null : h.id)}
                            onRemove={() => setRemovingHost(h)} />
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
      </Card>}

      {active === 'channels' && <>
      {/* This is the card's own entitlement-gated first load: not yet known
          whether the plan includes notify.channels, then the channels list's
          own first fetch. `isPending`, not `isFetching`, so this stays quiet
          on the invalidation refetches the mutations below trigger. */}
      <CardLoadingOverlay state={{ firstLoad: ent.isPending || (channelsAllowed && channels.isPending) }}>
      <Card title="Channels"
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
                        {/* A count, not the keys. Joining them printed
                            "app.install.failed, app.install.succeeded, ..."
                            across four lines of backend spelling, which is
                            both unreadable and the one thing a row like this
                            must never show. Which events is the Events
                            section's question. */}
                        <td className="whitespace-nowrap text-text-3">
                          {ch.events.length === 0
                            ? 'Everything'
                            : `${ch.events.length} ${ch.events.length === 1 ? 'event' : 'events'}`}
                        </td>
                        <td className={ch.enabled ? 'text-green' : 'text-text-3'}>
                          {ch.enabled ? 'enabled' : 'disabled'}
                        </td>
                        <td className="py-2 text-right">
                          <Button size="sm" variant="ghost"
                                  aria-label={`Edit ${ch.name}`}
                                  onClick={() => setEditingChannel(
                                    editingChannel === ch.id ? null : ch.id)}>
                            Edit
                          </Button>
                          <Button size="sm" variant="ghost" className="ml-2"
                                  disabled={toggleChannel.isPending}
                                  onClick={() => toggleChannel.mutate(ch)}>
                            {ch.enabled ? 'Disable' : 'Enable'}
                          </Button>
                          <Button size="sm" variant="ghost" className="ml-2"
                                  onClick={() => testChannel.mutate(ch.id)}>Test</Button>
                          <Button size="sm" variant="danger" className="ml-2"
                                  onClick={() => removeChannel(ch)}>Remove</Button>
                        </td>
                      </tr>
                    ))}
                    {rows.filter(ch => ch.id === editingChannel).map(ch => (
                      <tr key={`edit-${ch.id}`} className="border-t border-line-soft">
                        <td colSpan={5} className="py-3">
                          <ChannelEditForm channel={ch}
                            onSaved={() => {
                              setEditingChannel(null)
                              qc.invalidateQueries({ queryKey: ['notifications', 'channels'] })
                            }}
                            onCancel={() => setEditingChannel(null)} />
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
      </>}

      {active === 'events' && <Card title="Events">
        <EventsMatrix />
      </Card>}

      {active === 'maintenance' && <SchedulesCard exclude={BACKUP_KINDS} title="Maintenance" />}

      {active === 'teams' && <TeamsCard />}

      {active === 'users' && <UsersCard />}

      {active === 'api-keys' && <ApiKeysCard />}

      {/* Who you are and how you prove it. These three were routes/profile.tsx,
          a second page named "Profile and security" that rendered the same
          cards Settings did; it is gone and the avatar menu points here. */}
      {active === 'profile' && <>
        <AccountCard />
        <PasswordCard />
        <TotpCard />
      </>}

      {/* What is currently allowed in on that basis. TrustedDevicesCard
          renders nothing until two-factor is on, which is correct: there is no
          such thing as a device trusted to skip a factor you do not have. */}
      {active === 'sessions' && <>
        <SessionsCard />
        <TrustedDevicesCard />
      </>}

      {active === 'console' && <ConsoleCard />}

      {active === 'updates' && <UpdateCard />}

        </div>
      </div>
    </div>
  )
}
