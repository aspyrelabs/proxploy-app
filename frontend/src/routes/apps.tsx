import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createRoute, Link, Outlet, useNavigate, useParams, useSearch } from '@tanstack/react-router'
import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { notify } from '../lib/notify'
import { consoleWsUrl, useReconnectingTicket } from '../api/consoles'
import type { AppRow, DiscoveredRow, UpdateInfo } from '../api/hooks'
import { useEntitlements, useMetrics } from '../api/hooks'
import { AppCard, AppCardSkeleton } from '../components/AppCard'
import { BulkAdoptDialog } from '../components/BulkAdoptDialog'
import { Button } from '../components/ui/button'
import { EmptyState } from '../components/EmptyState'
import { IconTile } from '../components/IconTile'
import { JobLog } from '../components/JobLog'
import { KVGrid } from '../components/KVGrid'
import { LifecycleActions } from '../components/LifecycleActions'
import { MigrateDialog } from '../components/MigrateDialog'
import { QueryState } from '../components/QueryState'
import { Skeleton, SkeletonAvatar, SkeletonGroup, SkeletonLine } from '../components/ui/skeleton'
import { ReconfigureDialog } from '../components/ReconfigureDialog'
import { UninstallDialog } from '../components/UninstallDialog'
import { Loading } from '../components/ui/loading'
import { Terminal } from '../components/terminal/Terminal'
import { TerminalPanel } from '../components/TerminalPanel'
import { Sparkline } from '../components/charts/Sparkline'
import { StatusPill } from '../components/StatusPill'
import { RAM_GRADIENT, UsageBar } from '../components/UsageBar'
import { ScriptPanel } from '../components/ScriptPanel'
import { fmtBytes, fmtPct, fmtUptime } from '../lib/format'

const card = 'rounded-card border border-line-soft bg-panel p-5'
// Hoisted so the loading placeholder lays out in the SAME grid as the cards it
// stands in for. Two copies of the string is one copy too many.
const APP_GRID = 'grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4'
const inputCls ='rounded-ctl border border-line bg-panel px-3 py-1.5 text-[13px] text-text placeholder:text-text-3 focus:outline-none focus:ring-1 focus:ring-amber'

type HostRow = { id: number; name: string }

export function AppsPage() {
  const search = useSearch({ strict: false }) as { host?: number; q?: string }
  const navigate = useNavigate()
  const [dismissed, setDismissed] = useState(false)
  const [adopting, setAdopting] = useState(false)
  const hostsQuery = useQuery({
    queryKey: ['hosts'],
    queryFn: () => api<HostRow[]>('/hosts'),
  })
  const hosts = hostsQuery.data
  const appsQuery = useQuery({
    queryKey: ['apps', { host: search.host, q: search.q }],
    queryFn: () => {
      const p = new URLSearchParams()
      if (search.host != null) p.set('host', String(search.host))
      if (search.q) p.set('q', search.q)
      const qs = p.toString()
      return api<AppRow[]>(qs ? `/apps?${qs}` : '/apps')
    },
    refetchInterval: 30_000,
  })
  const apps = appsQuery.data
  const discoveredQuery = useQuery({
    queryKey: ['apps', 'discovered'],
    queryFn: () => api<DiscoveredRow[]>('/apps/discovered'),
    refetchInterval: 30_000,
  })
  const discovered = discoveredQuery.data

  const setSearch = (patch: Partial<{ host?: number; q?: string }>) =>
    navigate({ to: '/apps' as never, search: { ...search, ...patch } as never, replace: true })

  return (
    <div>
      <div className="mb-5 flex items-center justify-between">
        <div>
          <h1 className="font-display text-[22px] font-semibold">Apps</h1>
          <div className="text-[12px] text-text-3">
            {apps ? `${apps.length} installed across ${hosts?.length ?? 0} hosts` : '…'}
          </div>
        </div>
      </div>

      {discoveredQuery.isError && !dismissed && (
        <div className={`${card} mb-5`}>
          <p className="text-[12.5px] text-text-3">Could not check for existing containers to adopt.</p>
        </div>
      )}

      {discovered && discovered.length > 0 && !dismissed && (
        <div className={`${card} mb-5 border-amber-dim`}>
          <div className="flex items-center justify-between">
            <h2 className="text-[14px] font-semibold text-text">
              {discovered.length} existing container{discovered.length > 1 ? 's' : ''} discovered
            </h2>
            <button className="text-[12px] text-text-3 hover:text-text" onClick={() => setDismissed(true)}>
              Dismiss
            </button>
          </div>
          <div className="mt-2 space-y-1">
            {discovered.map((d) => (
              <div key={`${d.host_id}:${d.ctid}`} className="flex items-center gap-3 font-mono text-[12px] text-text-2">
                <span>CT {d.ctid}</span>
                <span className="text-text">{d.name ?? 'unknown'}</span>
                <span className="text-text-3">{d.host_name}</span>
                <StatusPill status={d.status} />
                {d.suggestion && (
                  <span className="rounded bg-amber-dim px-1.5 py-0.5 text-[10px] uppercase text-amber">
                    matches “{d.suggestion}”
                  </span>
                )}
              </div>
            ))}
          </div>
          <button className="mt-2 text-[12px] text-amber hover:underline" onClick={() => setAdopting(true)}>
            Adopt {discovered.length} container{discovered.length > 1 ? 's' : ''}
          </button>
        </div>
      )}

      <div className="mb-4 flex items-center gap-3">
        <div className="flex overflow-hidden rounded-ctl border border-line">
          <button
            className={`px-3 py-1.5 text-[12px] ${search.host == null ? 'bg-elev text-text' : 'text-text-2 hover:bg-panel-2'}`}
            onClick={() => setSearch({ host: undefined })}
          >
            All hosts
          </button>
          {(hosts ?? []).map((h) => (
            <button
              key={h.id}
              className={`border-l border-line px-3 py-1.5 text-[12px] ${search.host === h.id ? 'bg-elev text-text' : 'text-text-2 hover:bg-panel-2'}`}
              onClick={() => setSearch({ host: h.id })}
            >
              {h.name}
            </button>
          ))}
          {hostsQuery.isError && (
            <span className="border-l border-line px-3 py-1.5 text-[12px] text-red">
              Could not load hosts
            </span>
          )}
        </div>
        <input
          className={inputCls}
          placeholder="Filter apps…"
          defaultValue={search.q ?? ''}
          onChange={(e) => setSearch({ q: e.target.value || undefined })}
        />
        <span className="rounded-full bg-panel-2 px-2 py-0.5 font-mono text-[11px] text-text-2">
          {apps?.length ?? 0} shown
        </span>
      </div>

      <QueryState query={appsQuery}
                  loading={<SkeletonGroup label="Loading apps" className={APP_GRID}>
                    {Array.from({ length: 8 }, (_, i) => <AppCardSkeleton key={i} />)}
                  </SkeletonGroup>}
                  emptyTitle="No apps match your filter."
                  emptyNote="Install from the App Store (Phase 4) or adopt discovered containers."
                  errorTitle="Apps not readable"
                  errorNote="Proxploy could not reach the backend to list your apps.">
        {(rows) => (
          <div className={APP_GRID}>
            {rows.map((a) => <AppCard key={a.id} app={a} />)}
          </div>
        )}
      </QueryState>

      {adopting && discovered && <BulkAdoptDialog items={discovered} onClose={() => setAdopting(false)} />}
    </div>
  )
}

const TABS = [
  { path: '.', label: 'Overview' },
  { path: 'logs', label: 'Logs' },
  { path: 'console', label: 'Console' },
  { path: 'config', label: 'Config' },
] as const

export function AppDetail() {
  const { appId } = useParams({ strict: false }) as { appId: string }
  const ent = useEntitlements()
  const [migrating, setMigrating] = useState(false)
  const [uninstalling, setUninstalling] = useState(false)
  const [reconfiguring, setReconfiguring] = useState(false)
  const appQuery = useQuery({
    queryKey: ['apps', Number(appId)],
    queryFn: () => api<AppRow>(`/apps/${appId}`),
    refetchInterval: 15_000,
  })
  return (
    <QueryState query={appQuery} emptyTitle="" emptyNote="" empty={() => false}
                // The header and the tab strip, which is the whole page
                // frame; the tab body below draws its own placeholder off its
                // own query. Getting here means a cold navigation straight to
                // an app URL, since arriving from the grid finds this row
                // already cached and never shows a wait at all.
                loading={<SkeletonGroup label="Loading app">
                  <SkeletonLine className="w-14 text-[12px]" />
                  <SkeletonAvatar className="mt-2 mb-4 items-center gap-4"
                                  tile="h-14 w-14 rounded-tile"
                                  lines={['w-44 text-[22px]', 'w-64 text-[12px]']}>
                    {/* Lifecycle, Migrate, Reconfigure, Uninstall, then the
                        StatusPill: four md buttons at 35px and a 19px pill,
                        the same figures AppCardSkeleton derives. */}
                    <div className="flex shrink-0 items-center gap-3">
                      {['w-28', 'w-24', 'w-28', 'w-24'].map((w) => (
                        <Skeleton key={w} className={`h-[35px] rounded-ctl ${w}`} />
                      ))}
                      <Skeleton className="h-[19px] w-20 rounded-full" />
                    </div>
                  </SkeletonAvatar>
                  <div className="mb-5 flex gap-1 border-b border-line-soft">
                    {TABS.map((t) => (
                      <SkeletonLine key={t.path} className="mx-3 my-2 w-16 text-[13px]" />
                    ))}
                  </div>
                </SkeletonGroup>}
                errorTitle="This app could not be loaded"
                errorNote="Proxploy could not reach the backend, or the app no longer exists.">
      {(app) => {
        // Same wait-for-first-fetch gate as vms.tsx's cloneDenied, otherwise every
        // plan sees a dead Migrate button for the whole first entitlements fetch.
        const migrateDenied = ent.data != null && !ent.has('migrate.cross_host')
        const reconfigureDenied = ent.data != null && !ent.has('apps.reconfigure')
        const uninstallDenied = ent.data != null && !ent.has('apps.uninstall')
        return (
          <div>
            <Link to={'/apps' as never} className="text-[12px] text-text-3 hover:text-text">← Apps</Link>
            <div className="mt-2 mb-4 flex items-center gap-4">
              <IconTile name={app.name} iconUrl={app.icon_url} size={56}
                        initials={app.icon_initials} colors={app.icon_colors} />
              <div>
                <h1 className="font-display text-[22px] font-semibold">
                  {app.name}
                  {app.update_available && (
                    <span className="ml-2 rounded-tile bg-amber-dim px-2 py-0.5
                                     font-mono text-[10.5px] uppercase text-amber">
                      update available
                    </span>
                  )}
                </h1>
                <div className="font-mono text-[12px] text-text-3">
                  CT {app.ctid} · {app.host_name}{app.ip ? ` · ${app.ip}${app.web_port ? `:${app.web_port}` : ''}` : ''}
                </div>
              </div>
              <div className="ml-auto flex items-center gap-3">
                <LifecycleActions target="app" id={app.id} name={app.name} status={app.status} />
                <Button variant="ghost" disabled={migrateDenied}
                  title={migrateDenied ? 'Not included in your plan' : undefined}
                  onClick={() => setMigrating(true)}>
                  Migrate
                </Button>
                <Button variant="ghost" disabled={reconfigureDenied}
                  title={reconfigureDenied ? 'Not included in your plan' : undefined}
                  onClick={() => setReconfiguring(true)}>
                  Reconfigure
                </Button>
                <Button variant="danger" disabled={uninstallDenied}
                  title={uninstallDenied ? 'Not included in your plan' : undefined}
                  onClick={() => setUninstalling(true)}>
                  Uninstall
                </Button>
                <StatusPill status={app.status} />
              </div>
            </div>
            <div className="mb-5 flex gap-1 border-b border-line-soft">
              {TABS.map((t) => (
                <Link
                  key={t.path}
                  to={t.path as never}
                  from={'/apps/$appId' as never}
                  activeOptions={{ exact: t.path === '.' }}
                  className="px-3 py-2 text-[13px] text-text-2 hover:text-text [&.active]:border-b-2 [&.active]:border-amber [&.active]:text-text"
                >
                  {t.label}
                </Link>
              ))}
            </div>
            <Outlet />
            {migrating && <MigrateDialog app={app} onClose={() => setMigrating(false)} />}
            {reconfiguring && <ReconfigureDialog app={app} onClose={() => setReconfiguring(false)} />}
            {uninstalling && <UninstallDialog app={app} onClose={() => setUninstalling(false)} />}
          </div>
        )
      }}
    </QueryState>
  )
}

export function AppOverview() {
  const { appId } = useParams({ strict: false }) as { appId: string }
  const id = Number(appId)
  const { data: app } = useQuery({
    queryKey: ['apps', id],
    queryFn: () => api<AppRow>(`/apps/${id}`),
  })
  const cpu = useMetrics(`app:${id}`, 'cpu_pct', 24)
  if (!app) return null
  const memPct = app.mem_bytes != null && app.mem_total_bytes
    ? (app.mem_bytes / app.mem_total_bytes) * 100 : null
  return (
    <div>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className={card}>
          <h2 className="mb-2 text-[13px] uppercase text-text-3">CPU · 24h</h2>
          <Sparkline ts={cpu.data?.ts ?? []} values={cpu.data?.value ?? []} color="#F5B544" />
        </div>
        <div className={card}>
          <h2 className="mb-2 text-[13px] uppercase text-text-3">Memory</h2>
          <div className="mb-2 font-mono text-[13px] text-text">
            {fmtBytes(app.mem_bytes)} / {fmtBytes(app.mem_total_bytes)} ({fmtPct(memPct)})
          </div>
          <UsageBar pct={memPct} gradient={RAM_GRADIENT} />
        </div>
        <div className={card}>
          <h2 className="mb-2 text-[13px] uppercase text-text-3">Status</h2>
          <StatusPill status={app.status} />
          <div className="mt-2 font-mono text-[12px] text-text-2">up {fmtUptime(app.uptime_s)}</div>
        </div>
      </div>
      <div className={`${card} mt-4`}>
        <KVGrid items={[
          ['CTID', app.ctid],
          ['Node', app.node],
          ['IP', app.ip ?? 'unknown'],
          ['Category', app.category ?? 'unknown'],
          ['Web port', app.web_port ?? 'unknown'],
          ['Update', app.update_available ?? 'Up to date'],
        ]} />
      </div>
      <div className={`${card} mt-4`}>
        <h2 className="mb-3 text-[13px] uppercase text-text-3">Update</h2>
        <UpdatePanel appId={id} app={app} />
      </div>
    </div>
  )
}

/** Doc 06 App detail Overview: the Details KV grid's "Update" row plus an
 *  "Update to vX" button. X is a short commit sha, not a version; see
 *  services/appstore.py::mark_updates_available for why that is the only
 *  honest thing community-scripts lets us say. */
export function UpdatePanel({ appId, app }:
  { appId: number; app: { name: string; update_available: string | null } }) {
  const qc = useQueryClient()
  const ent = useEntitlements()
  const [consent, setConsent] = useState(false)
  const [jobId, setJobId] = useState<number | null>(null)
  // services/appstore.py::run_update reports the same ctx.progress(10)/(80)/
  // (100) shape run_install does: null on the freshly-enqueued job the
  // update POST returns, seeded from that row rather than assumed zero.
  const [progress, setProgress] = useState<number | null>(null)
  // Wait for the first entitlements fetch before deciding (settings.tsx
  // precedent), otherwise this fires GET /update for every viewer of every
  // app overview and offers a consent+button whose POST always 403s.
  const updatesAllowed = ent.data != null && ent.has('store.updates')
  const info = useQuery({
    queryKey: ['apps', appId, 'update'],
    queryFn: () => api<UpdateInfo>(`/apps/${appId}/update`),
    enabled: updatesAllowed,
  })
  const run = useMutation({
    mutationFn: () => api<{ job: { id: number; kind: string; progress_pct: number | null } }>(
      `/apps/${appId}/update`, { method: 'POST', body: JSON.stringify({ consent: true }) }),
    onSuccess: (r) => {
      setJobId(r.job.id)
      setProgress(r.job.progress_pct)
      notify.success('Update started.')
    },
    onError: () => notify.error('Could not start the update, try again.'),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ['apps'] })
      qc.invalidateQueries({ queryKey: ['jobs'] })
    },
  })

  const pending = info.data?.update_available ?? app.update_available
  if (!pending) {
    return <div className="text-[12.5px] text-text-3">Up to date.</div>
  }
  if (!updatesAllowed) {
    return <div className="text-[12.5px] text-text-3">
      {ent.data == null ? 'Loading…' : 'Not included in your plan.'}
    </div>
  }
  if (jobId != null) {
    return (
      <div>
        <div className="mb-3 flex items-center gap-2">
          {/* Never shown before the first step reports in: a zero here would
              read as stalled rather than as "not started yet". */}
          {progress != null && <Loading value={progress} label="Update progress" size={28} />}
          <span className="text-[12.5px] text-text-2">Updating {app.name}…</span>
        </div>
        <JobLog jobId={jobId} onProgress={setProgress} />
      </div>
    )
  }
  return (
    <div>
      <div className="mb-3 font-mono text-[12px] text-text-2">
        {info.data?.from_ref?.slice(0, 7) ?? '?'} → {info.data?.to_ref?.slice(0, 7) ?? pending}
      </div>
      {info.data?.diff_vs_upstream && (
        <pre className="mb-3 max-h-64 overflow-auto rounded-tile border border-line-soft
                        bg-panel-2 p-3 font-mono text-[11.5px] text-text-2">
          {info.data.diff_vs_upstream}
        </pre>
      )}
      <label className="mb-3 flex items-start gap-2 text-[12.5px] text-text-2">
        <input type="checkbox" checked={consent}
               onChange={(e) => setConsent(e.target.checked)} />
        <span>
          I understand this runs as root on the node hosting {app.name}.
        </span>
      </label>
      <Button disabled={!consent || run.isPending} onClick={() => run.mutate()}>
        Update to {pending}
      </Button>
    </div>
  )
}

// Route objects, imported by router.tsx (cluster.tsx precedent). shellRoute
// comes from ./shell, not ../router: importing router.tsx here would force
// its eager createRouter() to run mid-cycle when this file is the import
// entry point (e.g. in tests), before appsRoute/appDetailRoute exist.
import { shellRoute } from './shell'

export const appsRoute = createRoute({
  getParentRoute: () => shellRoute,
  path: '/apps',
  validateSearch: (s: Record<string, unknown>) => ({
    host: s.host != null ? Number(s.host) : undefined,
    q: typeof s.q === 'string' && s.q ? s.q : undefined,
  }),
  component: AppsPage,
})

export const appDetailRoute = createRoute({
  getParentRoute: () => shellRoute,
  path: '/apps/$appId',
  component: AppDetail,
})

export const appOverviewRoute = createRoute({
  getParentRoute: () => appDetailRoute,
  path: '/',
  component: AppOverview,
})
export function AppConsole({ appId }: { appId: number }) {
  const { ticket, failed, start, reconnect, giveUp } = useReconnectingTicket('app', appId)
  useEffect(() => { start() }, [appId])
  if (failed) {
    return <EmptyState title="Console connection failed"
      note="Gave up after repeated attempts. Reload the page to try again." />
  }
  if (!ticket.data) return <EmptyState title="Opening console…" note="" />
  return (
    <Terminal key={ticket.data.ticket}
      wsUrl={consoleWsUrl('app', appId, ticket.data.ticket)}
      onDrop={({ fatal }) => (fatal ? giveUp() : reconnect())} />
  )
}

function AppConsoleTab() {
  const { appId } = useParams({ strict: false }) as { appId: string }
  return <AppConsole appId={Number(appId)} />
}

export function AppLogs({ appId }: { appId: number }) {
  const { data, isError } = useQuery({
    queryKey: ['apps', appId, 'logs'],
    queryFn: () => api<{ stream: string; message: string }[]>(`/apps/${appId}/logs`),
    // Stop polling once the backend has answered with an error (currently
    // always, see GET /apps/{id}/logs's 501) instead of retrying a dead
    // endpoint every 5s forever.
    refetchInterval: (query) => (query.state.error ? false : 5_000),
    retry: false,
  })
  if (isError) {
    return <EmptyState title="Logs not available yet"
      note="Proxploy has no CT journal/exec channel wired up yet; this is a known gap, not a bug." />
  }
  return <TerminalPanel lines={data ?? []} />
}

function AppLogsTab() {
  const { appId } = useParams({ strict: false }) as { appId: string }
  return <AppLogs appId={Number(appId)} />
}

export const appLogsRoute = createRoute({
  getParentRoute: () => appDetailRoute, path: 'logs', component: AppLogsTab,
})

export const appConsoleRoute = createRoute({
  getParentRoute: () => appDetailRoute, path: 'console', component: AppConsoleTab,
})

const AppConfigTab = () => {
  const { appId } = useParams({ strict: false }) as { appId: string }
  return <ScriptPanel appId={Number(appId)} />
}

export const appConfigRoute = createRoute({
  getParentRoute: () => appDetailRoute,
  path: 'config',
  component: AppConfigTab,
})
