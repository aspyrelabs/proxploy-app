import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createRoute, useNavigate, useParams } from '@tanstack/react-router'
import { toast } from 'sonner'
import { api } from '../api/client'
import type { AppRow, NodeRow, Summary, VmRow } from '../api/hooks'
import { useEntitlements, useMetrics } from '../api/hooks'
import { consoleWsUrl, useReconnectingTicket } from '../api/consoles'
import { AppCard } from '../components/AppCard'
import { ActivityFeed } from '../components/ActivityFeed'
import { Button } from '../components/ui/button'
import { EmptyState } from '../components/EmptyState'
import { HostForm } from '../components/HostForm'
import { KVGrid } from '../components/KVGrid'
import { NodeCard } from '../components/NodeCard'
import { QueryState } from '../components/QueryState'
import { Sparkline } from '../components/charts/Sparkline'
import { Ring } from '../components/StatRings'
import { StatusPill } from '../components/StatusPill'
import { Terminal } from '../components/terminal/Terminal'
import { fmtBps, fmtBytes, fmtUptime } from '../lib/format'

const card = 'rounded-card border border-line-soft bg-panel p-5'

function useSummary() {
  return useQuery({
    queryKey: ['cluster', 'summary'],
    queryFn: () => api<Summary>('/cluster/summary'),
    refetchInterval: 30_000,
  })
}

function useNodes() {
  return useQuery({
    queryKey: ['cluster', 'nodes'],
    queryFn: () => api<NodeRow[]>('/cluster/nodes'),
    refetchInterval: 30_000,
  })
}

/** Doc 06 Cluster overview: the Apps section's "Update all" action. One
 *  confirm covers the whole batch, the backend still requires explicit
 *  consent, and enqueues one job per stale app so each has its own transcript. */
export function UpdateAllButton() {
  const ent = useEntitlements()
  const qc = useQueryClient()
  const allowed = ent.has('store.update_all')
  const run = useMutation({
    mutationFn: () => api<{ jobs: { id: number }[]; skipped: { reason: string }[] }>(
      '/apps/update-all', { method: 'POST', body: JSON.stringify({ consent: true }) }),
    onSuccess: (r) => {
      if (r.jobs.length === 0) {
        // Never a bare silence: "nothing happened" and "it is broken" look
        // identical otherwise.
        toast('Nothing to update, every app is on its catalog commit.')
        return
      }
      toast.success(`Updating ${r.jobs.length} app${r.jobs.length === 1 ? '' : 's'}, `
                    + 'follow them in the activity drawer.')
    },
    onError: () => toast.error('Could not start the updates, try again.'),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ['apps'] })
      qc.invalidateQueries({ queryKey: ['jobs'] })
    },
  })
  return (
    <Button variant="ghost" disabled={run.isPending || !allowed}
      title={!allowed ? 'Pro: Update all' : undefined}
      onClick={() => {
      if (window.confirm('Update every app that has a newer catalog commit? '
                         + 'Each update runs a community script as root on its node.')) {
        run.mutate()
      }
    }}>Update all</Button>
  )
}

/** Nodes that share a cluster, under one heading carrying that cluster's own
 *  health.
 *
 *  Grouped by cluster NAME rather than by host, and that is the point: two
 *  Hosts enrolled from the same cluster are two API endpoints into ONE
 *  cluster, so they collapse into a single group instead of drawing the same
 *  cluster twice. */
function ClusterGroup({ name, rows }: { name: string; rows: NodeRow[] }) {
  const down = rows.filter((n) => n.status !== 'connected').length
  return (
    <section className="mb-5">
      <div className="mb-2 flex items-baseline justify-between">
        <h2 className="font-display text-[15px] font-semibold">{name}</h2>
        <span className="text-[11px] text-text-3">
          {rows.length} node{rows.length === 1 ? '' : 's'} ·{' '}
          {down === 0 ? 'all healthy' : `${down} unreachable`}
        </span>
      </div>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        {rows.map((n) => <NodeCard key={`${n.host_id}:${n.node}`} node={n} />)}
      </div>
    </section>
  )
}

function groupByCluster(rows: NodeRow[]) {
  const clusters = new Map<string, NodeRow[]>()
  const standalone: NodeRow[] = []
  for (const n of rows) {
    if (!n.cluster) { standalone.push(n); continue }
    const group = clusters.get(n.cluster)
    if (group) group.push(n)
    else clusters.set(n.cluster, [n])
  }
  return { clusters: [...clusters.entries()], standalone }
}

/** "Add host" where the hosts are, not only buried in Settings.
 *
 *  POST /hosts answers 403 {"error":"entitlement_required","feature":
 *  "hosts.multi"} once one host exists. Saying so BEFORE the form is filled in
 *  is the whole reason this checks the entitlement itself: a raw 403 at the
 *  end of a completed form is the worst possible place to learn it. When the
 *  entitlement fetch itself failed we cannot honestly claim either way, so the
 *  form opens and the backend stays the authority (HostForm renders that 403
 *  in words too). */
function AddHostSection({ hostCount }: { hostCount: number }) {
  const ent = useEntitlements()
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const blocked = hostCount >= 1 && !ent.has('hosts.multi') && !ent.unknown
  return (
    <>
      <div className="mb-3 flex items-center justify-between">
        <h2 className="font-display text-[16px] font-semibold">Nodes</h2>
        <Button variant="ghost" onClick={() => setOpen((o) => !o)}>
          {open ? 'Cancel' : 'Add host'}
        </Button>
      </div>
      {open && (blocked ? (
        <div className={`${card} mb-4`}>
          <p className="text-[13px] text-text-2">
            Managing more than one host needs the multi-host plan.
          </p>
          <p className="mt-1 text-[12px] text-text-3">
            One host is included. Every node of that host's cluster is already
            managed here, at no extra tier.
          </p>
        </div>
      ) : (
        <div className={`${card} mb-4`}>
          <HostForm onCreated={() => {
            setOpen(false)
            toast.success('Host added. Its nodes appear as the first poll lands.')
            qc.invalidateQueries({ queryKey: ['hosts'] })
            qc.invalidateQueries({ queryKey: ['cluster'] })
          }} />
        </div>
      ))}
    </>
  )
}

export function HostsPage() {
  const summaryQuery = useSummary()
  const summary = summaryQuery.data
  const nodesQuery = useNodes()
  const nodes = nodesQuery.data
  const appsQuery = useQuery({
    queryKey: ['apps', {}],
    queryFn: () => api<AppRow[]>('/apps'),
    refetchInterval: 30_000,
  })
  const vmsQuery = useQuery({
    queryKey: ['vms', {}],
    queryFn: () => api<VmRow[]>('/vms'),
    refetchInterval: 30_000,
  })
  const firstHost = nodes?.[0]?.host_id ?? null
  // ponytail: throughput sparkline charts the first host's series; multi-host
  // summed series lands when a real fleet shows it matters (net figures in the
  // header are already fleet-wide from /cluster/summary).
  const net = useMetrics(firstHost ? `host:${firstHost}` : null, 'net_in_bps', 1)

  return (
    <div>
      <div className="mb-5 flex items-center justify-between">
        <div>
          <h1 className="font-display text-[22px] font-semibold">Hosts</h1>
          <div className="text-[12px] text-text-3">
            {summary
              ? `${summary.counts.nodes} nodes · ${summary.counts.apps} apps · ${summary.counts.vms} VMs`
              : '…'}
          </div>
        </div>
      </div>

      <div className={`${card} flex justify-around`}>
        {/* summaryQuery.isError -> unknown: a failed /cluster/summary must not
            draw a calm 0% gauge, which reads as "nothing is being used"
            rather than "we could not check". */}
        <Ring label="CPU" pct={summary?.cpu.pct ?? 0} unknown={summaryQuery.isError}
          sub={summaryQuery.isError ? 'unknown'
            : summary ? `${summary.cpu.used_cores} / ${summary.cpu.total_cores} cores` : 'unknown'}
          stops={['#F5B544', '#E0862B']} />
        <Ring label="Memory" pct={summary?.mem.pct ?? 0} unknown={summaryQuery.isError}
          sub={summaryQuery.isError ? 'unknown'
            : summary ? `${fmtBytes(summary.mem.used_bytes)} / ${fmtBytes(summary.mem.total_bytes)}` : 'unknown'}
          stops={['#34D3C6', '#5B9DF9']} />
        <Ring label="Storage" pct={summary?.storage.pct ?? 0} unknown={summaryQuery.isError}
          sub={summaryQuery.isError ? 'unknown'
            : summary ? `${fmtBytes(summary.storage.used_bytes)} / ${fmtBytes(summary.storage.total_bytes)}` : 'unknown'}
          stops={['#A78BFA', '#6D5AE6']} />
      </div>

      <div className="mt-5">
        <AddHostSection hostCount={new Set((nodes ?? []).map((n) => n.host_id)).size} />
        <QueryState query={nodesQuery}
                    emptyTitle="No nodes yet"
                    emptyNote="Proxmox nodes appear here once a host is added."
                    errorTitle="Nodes not readable"
                    errorNote="Proxploy could not reach the backend to list your nodes.">
          {(rows) => {
            const { clusters, standalone } = groupByCluster(rows)
            return (
              <>
                {clusters.map(([name, group]) => (
                  <ClusterGroup key={name} name={name} rows={group} />
                ))}
                {standalone.length > 0 && (
                  <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
                    {standalone.map((n) => (
                      <NodeCard key={`${n.host_id}:${n.node}`} node={n} />
                    ))}
                  </div>
                )}
              </>
            )
          }}
        </QueryState>
      </div>

      <div className="mt-6">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="font-display text-[16px] font-semibold">Apps</h2>
          <div className="flex items-center gap-3">
            <UpdateAllButton />
            {/* as never: route typing workaround, see router.tsx */}
            <a href="/apps" className="text-[12px] text-amber hover:underline">View all</a>
          </div>
        </div>
        <QueryState query={appsQuery}
                    emptyTitle="No apps yet"
                    emptyNote="Installed or adopted apps appear here. The App Store lands in Phase 4."
                    errorTitle="Apps not readable"
                    errorNote="Proxploy could not reach the backend to list your apps.">
          {(rows) => (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
              {rows.slice(0, 8).map((a) => <AppCard key={a.id} app={a} />)}
            </div>
          )}
        </QueryState>
      </div>

      <div className="mt-6 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className={card}>
          <h2 className="mb-3 font-display text-[16px] font-semibold">Virtual machines</h2>
          <QueryState query={vmsQuery}
                      emptyTitle="No VMs discovered"
                      emptyNote="QEMU guests on connected hosts appear here."
                      errorTitle="VMs not readable"
                      errorNote="Proxploy could not reach the backend to list your VMs.">
            {(rows) => (
              <table className="w-full text-left text-[13px]">
                <thead>
                  <tr className="text-[11px] uppercase text-text-3">
                    <th className="pb-2 font-medium">Name</th>
                    <th className="pb-2 font-medium">Node</th>
                    <th className="pb-2 font-medium">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.slice(0, 4).map((v) => (
                    <tr key={v.id} className="border-t border-line-soft hover:bg-panel-2">
                      <td className="py-2 font-mono">{v.name}</td>
                      <td className="py-2 text-text-2">{v.host_name}</td>
                      <td className="py-2"><StatusPill status={v.status} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </QueryState>
        </div>
        <div className={card}>
          <h2 className="mb-1 font-display text-[16px] font-semibold">Network</h2>
          <div className="mb-2 font-mono text-[12px] text-text-2">
            ↓ {fmtBps(summary?.net.in_bps)} · ↑ {fmtBps(summary?.net.out_bps)}
          </div>
          <Sparkline ts={net.data?.ts ?? []} values={net.data?.value ?? []} color="#5B9DF9" />
          <div className="mt-4 border-t border-line-soft pt-3">
            <div className="mb-1 text-[13px] uppercase text-text-3">Recent activity</div>
            <ActivityFeed />
          </div>
        </div>
      </div>
    </div>
  )
}

// Minimal slice of GET /hosts/{id}, this page only needs the opt-in flag;
// the fleet-overview fields (status, uptime, etc.) already come from `node`.
type HostDetail = { id: number; name: string; node_shell_enabled: boolean }

function useHostDetail(id: number) {
  return useQuery({
    queryKey: ['hosts', id],
    queryFn: () => api<HostDetail>(`/hosts/${id}`),
    enabled: Number.isFinite(id),
  })
}

function NodeShellSection({ hostId, nodeShellEnabled }: { hostId: number; nodeShellEnabled: boolean }) {
  const ent = useEntitlements()
  const [open, setOpen] = useState(false)
  const { ticket, failed, reconnect, giveUp } = useReconnectingTicket('host', hostId)
  const allowed = ent.has('terminal.node') && nodeShellEnabled
  if (open && failed) {
    return <EmptyState title="Console connection failed"
      note="Gave up after repeated attempts. Reload the page to try again." />
  }
  if (open && ticket.data) {
    return (
      <Terminal key={ticket.data.ticket}
        wsUrl={consoleWsUrl('host', hostId, ticket.data.ticket)}
        onDrop={({ fatal }) => (fatal ? giveUp() : reconnect())} />
    )
  }
  return (
    <div className={card}>
      <h2 className="mb-2 text-[13px] uppercase text-text-3">Node shell</h2>
      <Button variant="ghost" disabled={!allowed}
        title={!ent.has('terminal.node') ? 'Pro: Node shells'
             : !nodeShellEnabled ? 'Enable node shell in host settings first' : undefined}
        onClick={() => { setOpen(true); ticket.mutate() }}>
        Open node shell
      </Button>
    </div>
  )
}

export function NodeDetailPage() {
  // `node` is absent on the legacy /hosts/$hostId route, which resolves to the
  // host's entry node. Keying the lookup on (host, node) is the fix for a host
  // with several nodes: `nodes.find(n => n.host_id === id)` used to return
  // whichever one came first.
  const { hostId, node: nodeName } = useParams({ strict: false }) as
    { hostId: string; node?: string }
  const id = Number(hostId)
  const { data: nodes } = useNodes()
  const forHost = nodes?.filter((n) => n.host_id === id)
  const node = nodeName
    ? forHost?.find((n) => n.node === nodeName)
    : forHost?.find((n) => n.is_entry) ?? forHost?.[0]
  const { data: host } = useHostDetail(id)
  const cpu = useMetrics(`host:${id}`, 'cpu_pct', 24)
  const mem = useMetrics(`host:${id}`, 'mem_bytes', 24)
  const nodeAppsQuery = useQuery({
    queryKey: ['apps', { host: id }],
    queryFn: () => api<AppRow[]>(`/apps?host=${id}`),
    refetchInterval: 30_000,
  })
  const nodeVmsQuery = useQuery({
    queryKey: ['vms', { host: id }],
    queryFn: () => api<VmRow[]>(`/vms?host=${id}`),
    refetchInterval: 30_000,
  })
  const apps = nodeAppsQuery.data
  const vms = nodeVmsQuery.data
  if (!node && !host) return <EmptyState title="Node not found" note="It may have been removed." />
  return (
    <div>
      <div className="mb-5 flex items-center justify-between">
        <div>
          <h1 className="font-mono text-[20px] font-semibold">{node?.name ?? host?.name}</h1>
          {node && (
            <div className="text-[12px] text-text-3">
              {node.cluster ? `cluster · ${node.cluster}` : 'standalone'} · PVE {node.pve_version ?? '?'}
            </div>
          )}
        </div>
        {node && <StatusPill status={node.status} />}
      </div>
      {node && (
        <>
          <div className={card}>
            <KVGrid items={[
              ['Node', node.node ?? 'unknown'],
              ['PVE version', node.pve_version ?? 'unknown'],
              ['Uptime', fmtUptime(node.uptime_s)],
              ['Memory', `${fmtBytes(node.mem_bytes)} / ${fmtBytes(node.mem_total_bytes)}`],
              ['Apps', `${node.apps_running}/${node.apps} running`],
              ['VMs', `${node.vms_running}/${node.vms} running`],
            ]} />
          </div>
          {/* Entry node only: the `host:<id>` metric series is recorded from
              the node Proxploy connects through, so drawing it under any other
              node of the cluster would be charting a different machine. */}
          {node.is_entry && (
            <div className="mt-5 grid grid-cols-1 gap-4 lg:grid-cols-2">
              <div className={card}>
                <h2 className="mb-2 text-[13px] uppercase text-text-3">CPU · 24h</h2>
                <Sparkline ts={cpu.data?.ts ?? []} values={cpu.data?.value ?? []} color="#F5B544" width={480} height={120} />
              </div>
              <div className={card}>
                <h2 className="mb-2 text-[13px] uppercase text-text-3">Memory · 24h</h2>
                <Sparkline ts={mem.data?.ts ?? []} values={mem.data?.value ?? []} color="#34D3C6" width={480} height={120} />
              </div>
            </div>
          )}
        </>
      )}
      {/* Also entry-node only: a node shell ticket is minted for the host's
          own node, so offering it here would open a shell on a different box
          than the page is showing. */}
      {(node?.is_entry ?? true) && (
        <div className="mt-5">
          <NodeShellSection hostId={id} nodeShellEnabled={host?.node_shell_enabled ?? false} />
        </div>
      )}
      <div className="mt-5">
        {/* "on this host", not "on this node": neither apps nor vms records
            which node of the cluster a guest sits on, so this list is
            host-wide and says so. */}
        <h2 className="mb-3 font-display text-[16px] font-semibold">
          Guests on this host ({(apps?.length ?? 0) + (vms?.length ?? 0)})
        </h2>
        <QueryState query={nodeAppsQuery}
                    emptyTitle="No apps on this node"
                    emptyNote="Installed or adopted apps on this node appear here."
                    errorTitle="Apps not readable"
                    errorNote="Proxploy could not reach the backend to list apps on this node.">
          {(rows) => (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
              {rows.map((a) => <AppCard key={a.id} app={a} />)}
            </div>
          )}
        </QueryState>
        <QueryState query={nodeVmsQuery}
                    emptyTitle="No VMs on this node"
                    emptyNote="QEMU guests on this node appear here."
                    errorTitle="VMs not readable"
                    errorNote="Proxploy could not reach the backend to list VMs on this node.">
          {(rows) => (
            <div className={`${card} mt-4`}>
              <table className="w-full text-left text-[13px]">
                <tbody>
                  {rows.map((v) => (
                    <tr key={v.id} className="border-t border-line-soft first:border-t-0">
                      <td className="py-2 font-mono">{v.name}</td>
                      <td className="py-2 text-text-2">VMID {v.vmid}</td>
                      <td className="py-2"><StatusPill status={v.status} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </QueryState>
      </div>
    </div>
  )
}

/** /hosts/$hostId, kept alive for every link minted before node detail grew
 *  its node segment (and for anything that only knows a host id).
 *
 *  It resolves to the host's ENTRY node, the one Proxploy connects through,
 *  and renders the same page meanwhile: a redirect that first showed a blank
 *  screen would be a regression for the standalone host this used to serve. */
export function HostEntryRedirect() {
  const { hostId } = useParams({ strict: false }) as { hostId: string }
  const id = Number(hostId)
  const navigate = useNavigate()
  const { data: nodes } = useNodes()
  const forHost = nodes?.filter((n) => n.host_id === id)
  const entry = (forHost?.find((n) => n.is_entry) ?? forHost?.[0])?.node
  useEffect(() => {
    if (entry) {
      navigate({ to: '/hosts/$hostId/$node' as never,
                 params: { hostId: String(id), node: entry } as never,
                 replace: true })
    }
  }, [entry, id, navigate])
  return <NodeDetailPage />
}

// Route objects, imported by router.tsx (settings.tsx precedent). shellRoute
// comes from ./shell, not ../router: importing router.tsx here would force
// its eager createRouter() to run mid-cycle when this file is the import
// entry point (e.g. in tests), before hostsRoute/nodeDetailRoute exist.
import { shellRoute } from './shell'

export const hostsRoute = createRoute({
  getParentRoute: () => shellRoute,
  path: '/hosts',
  component: HostsPage,
})

export const nodeDetailRoute = createRoute({
  getParentRoute: () => shellRoute,
  path: '/hosts/$hostId/$node',
  component: NodeDetailPage,
})

// Still routed, still works: it redirects to the entry node above.
export const hostEntryRoute = createRoute({
  getParentRoute: () => shellRoute,
  path: '/hosts/$hostId',
  component: HostEntryRedirect,
})
