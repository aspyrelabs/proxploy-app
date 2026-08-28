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
import { ButtonGroup } from '../components/ui/button-group'
import { Dialog } from '../components/ui/dialog'
import { useJob } from '../api/jobs'
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
// stands in for.
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
        {/* Pushed to the far right by ml-auto, away from the filters: host and
            text NARROW the list, this only reorders what they left, and the two
            jobs should not read as one row of controls. */}
        <div className="ml-auto">
          <TableSorter sort={sorted.sort} onSort={sorted.setSort} label="apps" />
        </div>
      </div>

      <QueryState query={appsQuery}
                  loading={<SkeletonGroup label="Loading apps">
                    <AppTableSkeleton rows={8} />
                  </SkeletonGroup>}
                  emptyTitle="No apps match your filter."
                  emptyNote="Install from the App Store, or adopt a container Proxploy already found."
                  errorTitle="Apps not readable"
                  errorNote="Proxploy could not reach the backend to list your apps.">
        {/* Deliberately one view: the table is for scanning every app at once,
            the Hosts page has the icon glance. The expanded row lives in the
            URL (`open`); sorted rows are passed because QueryState owns state,
            not order. */}
        {() => <AppTable apps={sorted.rows} open={search.open}
                         onOpen={(open) => setSearch({ open })} />}
      </QueryState>

      {adopting && discovered && <BulkAdoptDialog items={discovered} onClose={() => setAdopting(false)} />}
    </div>
  )
}

/** "Update to vX": X is a short commit sha, not a version
 *  (services/appstore.py::mark_updates_available). */
export function UpdatePanel({ appId, app }:
  { appId: number; app: { name: string; update_available: string | null } }) {
  const qc = useQueryClient()
  const ent = useEntitlements()
  const [consent, setConsent] = useState(false)
  const [jobId, setJobId] = useState<number | null>(null)
  const [logOpen, setLogOpen] = useState(false)
  // run_update reports ctx.progress(10)/(80)/(100): three steps, so a ring
  // drawn from them sat still and then jumped to full without ever having
  // measured anything. The spinner says "working" without claiming to know
  // how far along it is, and the transcript is where the real answer is.
  const job = useJob(jobId)
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
    const status = job.data?.status
    const settled = status != null && status !== 'running' && status !== 'queued'
    return (
      <div className="flex flex-col items-center gap-2 py-2">
        {!settled && <Loading label={`Updating ${app.name}`} size={28} />}
        <span className="text-[12.5px] text-text-2">
          {!settled ? 'Updating…'
            : status === 'succeeded' ? `Updated ${app.name}.`
              : `Update ${status}. Open the log to see why.`}
        </span>
        <ButtonGroup>
          <Button size="sm" variant="ghost" onClick={() => setLogOpen(true)}>Logs</Button>
        </ButtonGroup>
        {logOpen && (
          <Dialog title={<>{app.name} update log</>} width="max(640px, 70vw)"
                  onClose={() => setLogOpen(false)}>
            <div className="mt-3 flex h-[60vh] min-h-0 flex-col
                            [&>div]:min-h-0 [&>div]:flex-1">
              <JobLog jobId={jobId} height="fill" />
            </div>
          </Dialog>
        )}
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
        {/* An update rewrites the running container in place, so the consent
            asks about a backup to go back to, not the generic "runs as root". */}
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

export function AppLogs({ appId, height }: { appId: number; height?: number | 'fill' }) {
  const { data, isError } = useQuery({
    queryKey: ['apps', appId, 'logs'],
    queryFn: () => api<{ stream: string; message: string }[]>(`/apps/${appId}/logs`),
    // Stop polling once the backend has answered with an error: a stopped
    // container answers the same way every five seconds.
    refetchInterval: (query) => (query.state.error ? false : 5_000),
    retry: false,
  })
  if (isError) {
    return <EmptyState title="Logs not readable"
      note="Proxploy reads a container's logs over SSH to its host. Check that the host is
            connected and the container is running." />
  }
  return <TerminalPanel lines={data ?? []} height={height} />
}
