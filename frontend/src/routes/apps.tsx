import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createRoute, useNavigate, useSearch } from '@tanstack/react-router'
import { useState } from 'react'
import { api } from '../api/client'
import { notify } from '../lib/notify'
import type { AppRow, DiscoveredRow, UpdateInfo } from '../api/hooks'
import { useEntitlements } from '../api/hooks'
import { AppTable, AppTableSkeleton } from '../components/AppTable'
import { UpdateAllButton } from '../components/UpdateAllButton'
import { BulkAdoptDialog } from '../components/BulkAdoptDialog'
import { Button, amberLinkCls, quietCls, segment } from '../components/ui/button'
import { EmptyState } from '../components/EmptyState'
import { JobLog } from '../components/JobLog'
import { QueryState } from '../components/QueryState'
import { SkeletonGroup } from '../components/ui/skeleton'
import { TableSorter, useSorted } from '../components/TableSorter'
import { Loading } from '../components/ui/loading'
import { TerminalPanel } from '../components/TerminalPanel'
import { StatusPill } from '../components/StatusPill'

const card = 'rounded-card border border-line-soft bg-panel p-5'
// Hoisted so the loading placeholder lays out in the SAME grid as the cards it
// stands in for. Two copies of the string is one copy too many.
const inputCls ='rounded-ctl border border-line bg-panel px-3 py-1.5 text-[13px] text-text placeholder:text-text-3 focus:outline-none focus:ring-1 focus:ring-amber'

type HostRow = { id: number; name: string }

export function AppsPage() {
  const search = useSearch({ strict: false }) as { host?: number; q?: string; open?: number }
  const navigate = useNavigate()
  const [dismissed, setDismissed] = useState(false)
  const [adopting, setAdopting] = useState(false)
  const hostsQuery = useQuery({
    queryKey: ['hosts'],
    queryFn: () => api<HostRow[]>('/hosts'),
  })
  const hosts = hostsQuery.data
  const appsQuery = useQuery({
    // Every keystroke in the filter box is a new key, and without this each
    // one is isPending, so QueryState swapped the whole grid for eight
    // skeletons between letters and the list strobed while you typed. Keeping
    // the previous rows on screen is what react-query has this for.
    placeholderData: keepPreviousData,
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
  // Client-side, on rows the query already holds (usePaged precedent on
  // /backups). The chosen order is NOT in the URL next to the filters: those
  // change which apps you are looking at and are worth sending someone, this
  // changes only the order they are stacked in.
  const sorted = useSorted(apps ?? [])

  const setSearch = (patch: Partial<{ host?: number; q?: string; open?: number }>) =>
    navigate({ to: '/apps' as never, search: { ...search, ...patch } as never, replace: true })

  return (
    <div>
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="font-display text-[22px] font-semibold">Apps</h1>
          <div className="text-[12px] text-text-3">
            {apps ? `${apps.length} installed across ${hosts?.length ?? 0} hosts` : '…'}
          </div>
        </div>
        <UpdateAllButton />
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
            <button className={`text-[12px] ${quietCls}`} onClick={() => setDismissed(true)}>
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
          <button className={`mt-2 text-[12px] ${amberLinkCls}`} onClick={() => setAdopting(true)}>
            Adopt {discovered.length} container{discovered.length > 1 ? 's' : ''}
          </button>
        </div>
      )}

      <div className="mb-4 flex items-center gap-3">
        <div className="flex overflow-hidden rounded-ctl border border-line">
          <button
            className={`px-3 py-1.5 text-[12px] ${segment(search.host == null)}`}
            onClick={() => setSearch({ host: undefined })}
          >
            All hosts
          </button>
          {(hosts ?? []).map((h) => (
            <button
              key={h.id}
              className={`border-l border-line px-3 py-1.5 text-[12px] ${segment(search.host === h.id)}`}
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
        {/* Last in the row, and outside the filters: host and text NARROW the
            list, this only reorders what they left. */}
        <TableSorter sort={sorted.sort} onSort={sorted.setSort} label="apps" />
      </div>

      <QueryState query={appsQuery}
                  loading={<SkeletonGroup label="Loading apps">
                    <AppTableSkeleton rows={8} />
                  </SkeletonGroup>}
                  emptyTitle="No apps match your filter."
                  emptyNote="Install from the App Store, or adopt a container Proxploy already found."
                  errorTitle="Apps not readable"
                  errorNote="Proxploy could not reach the backend to list your apps.">
        {/* One view, deliberately. This page is for scanning every app at
            once, which is what a table is for; the Hosts page carries the
            icon glance. A switcher here would offer two ways to read the
            same thing on a page that only needs one.

            Which row is expanded lives in the URL, next to the filters, so
            /apps?open=3 opens straight onto that app the way its own page
            used to.

            The sorted rows, not the ones handed in: QueryState is still what
            decides between loading, error, empty and data, it just does not
            own the order. Both are the same fetch. */}
        {() => <AppTable apps={sorted.rows} open={search.open}
                         onOpen={(open) => setSearch({ open })} />}
      </QueryState>

      {adopting && discovered && <BulkAdoptDialog items={discovered} onClose={() => setAdopting(false)} />}
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
        {/* The consent names the risk the operator can actually do something
            about. "Runs as root on the node" was true and useless: it is true
            of every action in this product, it is not a thing to check before
            clicking, and it left the one precaution that matters here unsaid.
            An update rewrites a running container in place, so the question
            worth asking is whether there is a backup to go back to. */}
        <span>
          I confirm that I have backed up and want to update{' '}
          <span className="font-mono">{app.name}</span>.
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
// entry point (e.g. in tests), before appsRoute exists.
import { shellRoute } from './shell'

export const appsRoute = createRoute({
  getParentRoute: () => shellRoute,
  path: '/apps',
  validateSearch: (s: Record<string, unknown>) => ({
    host: s.host != null ? Number(s.host) : undefined,
    q: typeof s.q === 'string' && s.q ? s.q : undefined,
    // The expanded row, same Number coercion as `host`: search params arrive
    // as strings and the table compares this against AppRow.id.
    open: s.open != null ? Number(s.open) : undefined,
  }),
  component: AppsPage,
})

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
