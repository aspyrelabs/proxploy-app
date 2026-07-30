import { useQuery } from '@tanstack/react-query'
import { createRoute, Link, Outlet, useNavigate, useParams, useSearch } from '@tanstack/react-router'
import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { useConsoleTicket, consoleWsUrl } from '../api/consoles'
import type { AppRow, DiscoveredRow } from '../api/hooks'
import { useMetrics } from '../api/hooks'
import { AppCard } from '../components/AppCard'
import { BulkAdoptDialog } from '../components/BulkAdoptDialog'
import { EmptyState } from '../components/EmptyState'
import { KVGrid } from '../components/KVGrid'
import { LifecycleActions } from '../components/LifecycleActions'
import { Terminal } from '../components/terminal/Terminal'
import { TerminalPanel } from '../components/TerminalPanel'
import { Sparkline } from '../components/charts/Sparkline'
import { StatusPill } from '../components/StatusPill'
import { RAM_GRADIENT, UsageBar } from '../components/UsageBar'
import { ScriptPanel } from '../components/ScriptPanel'
import { fmtBytes, fmtPct, fmtUptime } from '../lib/format'

const card = 'rounded-card border border-line-soft bg-panel p-5'
const inputCls = 'rounded-ctl border border-line bg-panel px-3 py-1.5 text-[13px] text-text placeholder:text-text-3 focus:outline-none focus:ring-1 focus:ring-amber'

type HostRow = { id: number; name: string }

export function AppsPage() {
  const search = useSearch({ strict: false }) as { host?: number; q?: string }
  const navigate = useNavigate()
  const [dismissed, setDismissed] = useState(false)
  const [adopting, setAdopting] = useState(false)
  const { data: hosts } = useQuery({
    queryKey: ['hosts'],
    queryFn: () => api<HostRow[]>('/hosts'),
  })
  const { data: apps } = useQuery({
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
  const { data: discovered } = useQuery({
    queryKey: ['apps', 'discovered'],
    queryFn: () => api<DiscoveredRow[]>('/apps/discovered'),
    refetchInterval: 30_000,
  })

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
                <span className="text-text">{d.name ?? '—'}</span>
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

      {apps && apps.length > 0 ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {apps.map((a) => <AppCard key={a.id} app={a} />)}
        </div>
      ) : (
        <EmptyState title="No apps match your filter."
          note="Install from the App Store (Phase 4) or adopt discovered containers." />
      )}

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
  const { data: app } = useQuery({
    queryKey: ['apps', Number(appId)],
    queryFn: () => api<AppRow>(`/apps/${appId}`),
    refetchInterval: 15_000,
  })
  if (!app) return <EmptyState title="Loading…" note="" />
  return (
    <div>
      <Link to={'/apps' as never} className="text-[12px] text-text-3 hover:text-text">← Apps</Link>
      <div className="mt-2 mb-4 flex items-center gap-4">
        <div
          className="flex h-14 w-14 items-center justify-center rounded-card font-display text-[18px] font-semibold text-white"
          style={{
            background: app.icon_colors
              ? `linear-gradient(135deg, ${app.icon_colors.c1}, ${app.icon_colors.c2})`
              : 'linear-gradient(135deg,#F5B544,#E0862B)',
          }}
        >
          {app.icon_initials ?? app.name.slice(0, 2).toUpperCase()}
        </div>
        <div>
          <h1 className="font-display text-[22px] font-semibold">{app.name}</h1>
          <div className="font-mono text-[12px] text-text-3">
            CT {app.ctid} · {app.host_name}{app.ip ? ` · ${app.ip}${app.web_port ? `:${app.web_port}` : ''}` : ''}
          </div>
        </div>
        <div className="ml-auto flex items-center gap-3">
          <LifecycleActions target="app" id={app.id} name={app.name} status={app.status} />
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
    </div>
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
          ['IP', app.ip ?? '—'],
          ['Category', app.category ?? '—'],
          ['Web port', app.web_port ?? '—'],
          ['Update', app.update_available ?? 'Up to date'],
        ]} />
      </div>
    </div>
  )
}

// Route objects — imported by router.tsx (cluster.tsx precedent). shellRoute
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
  const ticket = useConsoleTicket('app', appId)
  useEffect(() => { ticket.mutate() }, [appId])
  if (!ticket.data) return <EmptyState title="Opening console…" note="" />
  return (
    <Terminal key={ticket.data.ticket}
      wsUrl={consoleWsUrl('app', appId, ticket.data.ticket)}
      onDrop={() => ticket.mutate()} />
  )
}

function AppConsoleTab() {
  const { appId } = useParams({ strict: false }) as { appId: string }
  return <AppConsole appId={Number(appId)} />
}

export function AppLogs({ appId }: { appId: number }) {
  const { data } = useQuery({
    queryKey: ['apps', appId, 'logs'],
    queryFn: () => api<{ stream: string; message: string }[]>(`/apps/${appId}/logs`),
    refetchInterval: 5_000,
  })
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
