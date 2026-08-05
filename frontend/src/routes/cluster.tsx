import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createRoute, useParams } from '@tanstack/react-router'
import { toast } from 'sonner'
import { api } from '../api/client'
import type { AppRow, NodeRow, Summary, VmRow } from '../api/hooks'
import { useEntitlements, useMetrics } from '../api/hooks'
import { consoleWsUrl, useReconnectingTicket } from '../api/consoles'
import { AppCard } from '../components/AppCard'
import { ActivityFeed } from '../components/ActivityFeed'
import { Button } from '../components/ui/button'
import { EmptyState } from '../components/EmptyState'
import { KVGrid } from '../components/KVGrid'
import { LivePulse } from '../components/LiveProvider'
import { NodeCard } from '../components/NodeCard'
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
 *  confirm covers the whole batch — the backend still requires explicit
 *  consent, and enqueues one job per stale app so each has its own transcript. */
export function UpdateAllButton() {
  const qc = useQueryClient()
  const run = useMutation({
    mutationFn: () => api<{ jobs: { id: number }[]; skipped: { reason: string }[] }>(
      '/apps/update-all', { method: 'POST', body: JSON.stringify({ consent: true }) }),
    onSuccess: (r) => {
      if (r.jobs.length === 0) {
        // Never a bare silence: "nothing happened" and "it is broken" look
        // identical otherwise.
        toast('Nothing to update — every app is on its catalog commit.')
        return
      }
      toast.success(`Updating ${r.jobs.length} app${r.jobs.length === 1 ? '' : 's'} — `
                    + 'follow them in the activity drawer.')
    },
    onError: () => toast.error('Could not start the updates — try again.'),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ['apps'] })
      qc.invalidateQueries({ queryKey: ['jobs'] })
    },
  })
  return (
    <Button variant="ghost" disabled={run.isPending} onClick={() => {
      if (window.confirm('Update every app that has a newer catalog commit? '
                         + 'Each update runs a community script as root on its node.')) {
        run.mutate()
      }
    }}>Update all</Button>
  )
}

export function ClusterPage() {
  const { data: summary } = useSummary()
  const { data: nodes } = useNodes()
  const { data: apps } = useQuery({
    queryKey: ['apps', {}],
    queryFn: () => api<AppRow[]>('/apps'),
    refetchInterval: 30_000,
  })
  const { data: vms } = useQuery({
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
          <h1 className="font-display text-[22px] font-semibold">Cluster</h1>
          <div className="text-[12px] text-text-3">
            {summary
              ? `${summary.counts.nodes} nodes · ${summary.counts.apps} apps · ${summary.counts.vms} VMs`
              : '…'}
          </div>
        </div>
        <LivePulse />
      </div>

      <div className={`${card} flex justify-around`}>
        <Ring label="CPU" pct={summary?.cpu.pct ?? 0}
          sub={summary ? `${summary.cpu.used_cores} / ${summary.cpu.total_cores} cores` : '—'}
          stops={['#F5B544', '#E0862B']} />
        <Ring label="Memory" pct={summary?.mem.pct ?? 0}
          sub={summary ? `${fmtBytes(summary.mem.used_bytes)} / ${fmtBytes(summary.mem.total_bytes)}` : '—'}
          stops={['#34D3C6', '#5B9DF9']} />
        <Ring label="Storage" pct={summary?.storage.pct ?? 0}
          sub={summary ? `${fmtBytes(summary.storage.used_bytes)} / ${fmtBytes(summary.storage.total_bytes)}` : '—'}
          stops={['#A78BFA', '#6D5AE6']} />
      </div>

      <div className="mt-5 grid grid-cols-1 gap-4 md:grid-cols-3">
        {(nodes ?? []).map((n) => <NodeCard key={n.host_id} node={n} />)}
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
        {apps && apps.length > 0 ? (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
            {apps.slice(0, 8).map((a) => <AppCard key={a.id} app={a} />)}
          </div>
        ) : (
          <EmptyState title="No apps yet"
            note="Installed or adopted apps appear here. The App Store lands in Phase 4." />
        )}
      </div>

      <div className="mt-6 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className={card}>
          <h2 className="mb-3 font-display text-[16px] font-semibold">Virtual machines</h2>
          {vms && vms.length > 0 ? (
            <table className="w-full text-left text-[13px]">
              <thead>
                <tr className="text-[11px] uppercase text-text-3">
                  <th className="pb-2 font-medium">Name</th>
                  <th className="pb-2 font-medium">Node</th>
                  <th className="pb-2 font-medium">Status</th>
                </tr>
              </thead>
              <tbody>
                {vms.slice(0, 4).map((v) => (
                  <tr key={v.id} className="border-t border-line-soft hover:bg-panel-2">
                    <td className="py-2 font-mono">{v.name}</td>
                    <td className="py-2 text-text-2">{v.host_name}</td>
                    <td className="py-2"><StatusPill status={v.status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <EmptyState title="No VMs discovered" note="QEMU guests on connected hosts appear here." />
          )}
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

// Minimal slice of GET /hosts/{id} — this page only needs the opt-in flag;
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
        title={!ent.has('terminal.node') ? 'Pro — Node shells'
             : !nodeShellEnabled ? 'Enable node shell in host settings first' : undefined}
        onClick={() => { setOpen(true); ticket.mutate() }}>
        Open node shell
      </Button>
    </div>
  )
}

export function NodeDetailPage() {
  const { hostId } = useParams({ strict: false }) as { hostId: string }
  const id = Number(hostId)
  const { data: nodes } = useNodes()
  const node = nodes?.find((n) => n.host_id === id)
  const { data: host } = useHostDetail(id)
  const cpu = useMetrics(`host:${id}`, 'cpu_pct', 24)
  const mem = useMetrics(`host:${id}`, 'mem_bytes', 24)
  const { data: apps } = useQuery({
    queryKey: ['apps', { host: id }],
    queryFn: () => api<AppRow[]>(`/apps?host=${id}`),
    refetchInterval: 30_000,
  })
  const { data: vms } = useQuery({
    queryKey: ['vms', { host: id }],
    queryFn: () => api<VmRow[]>(`/vms?host=${id}`),
    refetchInterval: 30_000,
  })
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
              ['Node', node.node],
              ['PVE version', node.pve_version ?? '—'],
              ['Uptime', fmtUptime(node.uptime_s)],
              ['Memory', `${fmtBytes(node.mem_bytes)} / ${fmtBytes(node.mem_total_bytes)}`],
              ['Apps', `${node.apps_running}/${node.apps} running`],
              ['VMs', `${node.vms_running}/${node.vms} running`],
            ]} />
          </div>
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
        </>
      )}
      <div className="mt-5">
        <NodeShellSection hostId={id} nodeShellEnabled={host?.node_shell_enabled ?? false} />
      </div>
      <div className="mt-5">
        <h2 className="mb-3 font-display text-[16px] font-semibold">
          Guests on this node ({(apps?.length ?? 0) + (vms?.length ?? 0)})
        </h2>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {(apps ?? []).map((a) => <AppCard key={a.id} app={a} />)}
        </div>
        {vms && vms.length > 0 && (
          <div className={`${card} mt-4`}>
            <table className="w-full text-left text-[13px]">
              <tbody>
                {vms.map((v) => (
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
      </div>
    </div>
  )
}

// Route objects — imported by router.tsx (settings.tsx precedent). shellRoute
// comes from ./shell, not ../router: importing router.tsx here would force
// its eager createRouter() to run mid-cycle when this file is the import
// entry point (e.g. in tests), before clusterRoute/nodeDetailRoute exist.
import { shellRoute } from './shell'

export const clusterRoute = createRoute({
  getParentRoute: () => shellRoute,
  path: '/cluster',
  component: ClusterPage,
})

export const nodeDetailRoute = createRoute({
  getParentRoute: () => shellRoute,
  path: '/cluster/$hostId',
  component: NodeDetailPage,
})
