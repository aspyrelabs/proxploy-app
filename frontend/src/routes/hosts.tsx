import { useEffect, useState } from 'react'
import { useQuery, useQueryClient, type UseQueryResult } from '@tanstack/react-query'
import { createRoute, Link, Outlet, useNavigate, useParams } from '@tanstack/react-router'
import { api } from '../api/client'
import { openConsoleWindow } from '../lib/console-window'
import { notify } from '../lib/notify'
import type { AppRow, NodeRow, Summary, VmRow } from '../api/hooks'
import { useEntitlements } from '../api/hooks'
import { AppIconGrid, IconGridSkeleton, VmIconGrid } from '../components/IconGrid'
import { Button, amberLinkCls } from '../components/ui/button'
import { tabTrigger } from '../components/ui/tabs'

// The two controls in a node's header: one opens a shell, one opens Proxmox.
// They read as a pair and one of them is an <a>, which Button cannot render,
// so the shared thing is a class string. Transparent until pointed at, so a
// header does not stack two filled boxes next to the node name.
const headerCtl = 'rounded-ctl border border-line px-2.5 py-1 text-[12px] text-text-2 ' +
  'transition hover:border-amber hover:text-amber'

import { EmptyState } from '../components/EmptyState'
import { GuestList, GuestListSkeleton, toGuests } from '../components/GuestList'
import { HardwareTab } from '../components/HardwareTab'
import { HostActionsMenu } from '../components/HostActionsMenu'
import { NodeIdentityRail } from '../components/NodeIdentityRail'
import { AddHostDialog } from '../components/AddHostDialog'
import { NodeCard, NodeCardSkeleton } from '../components/NodeCard'
import { dedupeNodes, type MergedNode } from '../lib/nodes'
import { QueryState } from '../components/QueryState'
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from '../components/ui/resizable'
import { MetricChart } from '../components/charts/MetricChart'
import { NetworkStat, NetworkStatSkeleton, Ring, RingSkeleton } from '../components/StatRings'
import { StatusPill } from '../components/StatusPill'
import { Skeleton, SkeletonGroup, SkeletonLine } from '../components/ui/skeleton'
import { fmtBytes } from '../lib/format'
import { useMediaQuery } from '../lib/use-media-query'
import { useThroughput } from '../api/network'
import { combineThroughput } from '../lib/throughput'

const card = 'rounded-card border border-line-soft bg-panel p-5'
// Hoisted because the loading placeholder has to lay out in the SAME grid as
// the content it replaces.
const nodeGrid = 'grid grid-cols-1 gap-4 md:grid-cols-3'
function useSummary() {
  return useQuery({
    queryKey: ['cluster', 'summary'],
    queryFn: () => api<Summary>('/cluster/summary'),
    refetchInterval: 30_000,
  })
}

/** Exported for routes/network.tsx, which needs the same cluster lookup to
 *  dedupe its throughput. Same query key, so the two share one fetch. */
export function useNodes() {
  return useQuery({
    queryKey: ['cluster', 'nodes'],
    queryFn: () => api<NodeRow[]>('/cluster/nodes'),
    refetchInterval: 30_000,
  })
}


/** Nodes that share a cluster, under one heading carrying that cluster's own
 *  health. Grouped by cluster NAME, not by host: two Hosts enrolled from the
 *  same cluster are two API endpoints into ONE cluster, so they collapse into
 *  a single group instead of drawing the same cluster twice. */
function ClusterGroup({ name, rows }: { name: string; rows: MergedNode[] }) {
  const down = rows.filter((n) => n.status !== 'connected').length
  // Every node connected is not the same as the cluster being usable: without
  // quorum /etc/pve is read-only, so every write fails while every read
  // answers, and "all healthy" would read as fine on a cluster that cannot
  // accept an install.
  const noQuorum = rows.some((n) => n.quorate === false)
  return (
    <section className="mb-5">
      <div className="mb-2 flex items-baseline justify-between gap-3">
        <h2 className="font-display text-[15px] font-semibold">
          {/* The cluster's name alone is not self-describing: "lab-cluster" as a
              bare heading reads as a section title, not as the thing these
              nodes are members OF. */}
          <span className="text-text-3">Cluster </span>{name}
        </h2>
        <span className="text-[11px] text-text-3">
          {rows.length} node{rows.length === 1 ? '' : 's'} ·{' '}
          {noQuorum
            ? <span className="text-red">no quorum</span>
            : down === 0 ? 'all healthy' : `${down} unreachable`}
        </span>
      </div>
      <div className={nodeGrid}>
        {rows.map((n) => <NodeCard key={`${n.host_id}:${n.node}`} node={n} />)}
      </div>
    </section>
  )
}

/** Grouped AND sorted, because /cluster/nodes answers in no defined order:
 *  unsorted, the cards reshuffled under the operator on every 30s refetch.
 *  Sorting the rows first is enough, since a Map keeps insertion order and
 *  each group inherits it; only the cluster headings need their own sort. */
function groupByCluster(rows: MergedNode[]) {
  const clusters = new Map<string, MergedNode[]>()
  const standalone: MergedNode[] = []
  for (const n of [...rows].sort((a, b) => (a.node ?? '').localeCompare(b.node ?? ''))) {
    if (!n.cluster) { standalone.push(n); continue }
    const group = clusters.get(n.cluster)
    if (group) group.push(n)
    else clusters.set(n.cluster, [n])
  }
  return {
    clusters: [...clusters.entries()].sort(([a], [b]) => a.localeCompare(b)),
    standalone,
  }
}

/** "Add host" where the hosts are, not only buried in Settings.
 *
 *  POST /hosts answers 403 {"error":"entitlement_required","feature":
 *  "hosts.multi"} once one host exists, and a raw 403 at the end of a filled
 *  form is the worst place to learn it. When the entitlement fetch itself
 *  failed we cannot claim either way, so the form opens and the backend stays
 *  the authority. */
function AddHostSection({ hostCount }: { hostCount: number }) {
  const ent = useEntitlements()
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  // ent.data != null covers the pending window as well as the error one:
  // !unknown alone is true while the fetch is still running, so clicking
  // "Add host" in that sliver replaced the form with the upsell.
  const blocked = hostCount >= 1 && ent.data != null && !ent.has('hosts.multi')
  return (
    <>
      <div className="mb-3 flex items-center justify-between">
        <h2 className="font-display text-[16px] font-semibold">Nodes</h2>
        <Button variant="ghost" onClick={() => setOpen(true)}>Add host</Button>
      </div>
      {open && (
        <AddHostDialog blocked={blocked} onClose={() => setOpen(false)}
          onCreated={() => {
            setOpen(false)
            notify.success('Host added. Its nodes appear as the first poll lands.')
            qc.invalidateQueries({ queryKey: ['hosts'] })
            qc.invalidateQueries({ queryKey: ['cluster'] })
          }} />
      )}
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

  const wide = useMediaQuery('(min-width: 1024px)')

  // History for the Network tile's spark. An hour is the SHORTEST window
  // /network/throughput serves (1 <= hours <= 48), so the tile's footer reads
  // the window off the timestamps it got rather than claiming one.
  //
  // combineThroughput, never a sum: two hosts enrolled into one cluster each
  // record that whole cluster's traffic, so adding the rows reports it
  // twice.
  const throughputQuery = useThroughput(1)
  const clusterOf = (hostId: number) =>
    (nodes ?? []).find((n) => n.host_id === hostId)?.cluster ?? null
  const net = combineThroughput(throughputQuery.data?.hosts ?? [], clusterOf)

  /* The two inventories, built once and placed by the branch below. Consts
     rather than components because they close over the two queries above and
     take nothing else. */
  const appsColumn = (
    <div>
      {/* One icon per app with its status, and nothing else: this section is a
          glance at what is installed, not the place to operate on it. Every
          app, with no cap, so a missing app cannot also mean "the ninth". */}
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-display text-[16px] font-semibold">Apps</h2>
        {/* as never: route typing workaround, see router.tsx */}
        <a href="/apps" className={`text-[12px] ${amberLinkCls}`}>View all</a>
      </div>
      <QueryState query={appsQuery}
                  loading={<SkeletonGroup label="Loading apps">
                    <IconGridSkeleton count={8} />
                  </SkeletonGroup>}
                  emptyTitle="No apps yet"
                  emptyNote="Installed or adopted apps appear here. Install one from the App Store, or adopt a container Proxploy already found."
                  errorTitle="Apps not readable"
                  errorNote="Proxploy could not reach the backend to list your apps.">
        {(rows) => <AppIconGrid apps={rows} />}
      </QueryState>
    </div>
  )

  /* Heading outside the panel, matching Apps beside it, whose heading row has
     to sit outside because it carries the view switch. The same flex wrapper
     keeps both headings on one baseline across the row. */
  const vmsColumn = (
    <div>
      {/* The same icon grid the Apps column draws, grouped the same way. The
          grid carries its own panel, so there is no card wrapper here. */}
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-display text-[16px] font-semibold">Virtual machines</h2>
        {/* as never: route typing workaround, see router.tsx */}
        <a href="/vms" className={`text-[12px] ${amberLinkCls}`}>View all</a>
      </div>
      <QueryState query={vmsQuery}
                  loading={<SkeletonGroup label="Loading virtual machines">
                    <IconGridSkeleton count={4} />
                  </SkeletonGroup>}
                  emptyTitle="No VMs discovered"
                  emptyNote="QEMU guests on connected hosts appear here."
                  errorTitle="VMs not readable"
                  errorNote="Proxploy could not reach the backend to list your VMs.">
        {(rows) => <VmIconGrid vms={rows} />}
      </QueryState>
    </div>
  )

  return (
    <div>
      <div className="mb-5 flex items-center justify-between">
        <div>
          <h1 className="font-display text-[22px] font-semibold">Hosts</h1>
          <div className="text-[12px] text-text-3">
            {summaryQuery.isPending
              ? <SkeletonLine className="w-52 text-[12px]" />
              : summary
                ? `${summary.counts.nodes} nodes · ${summary.counts.apps} apps · ${summary.counts.vms} VMs`
                : '…'}
          </div>
        </div>
      </div>

      <div className={`${card} flex justify-around`}>
        {/* The pending case has the same problem the error case does:
            `pct={summary?.cpu.pct ?? 0}` is 0 until the fetch returns, so all
            three gauges drew a confident empty ring over a cluster that was
            simply not measured yet. `unknown` is wrong here too: that word is
            an answer, and there is no answer yet. */}
        {summaryQuery.isPending ? (
          <SkeletonGroup label="Loading cluster usage" className="flex flex-1 justify-around">
            <RingSkeleton label="CPU" />
            <RingSkeleton label="Memory" />
            <RingSkeleton label="Storage" />
            <NetworkStatSkeleton />
          </SkeletonGroup>
        ) : (
        <>
        {/* summaryQuery.isError -> unknown: a failed /cluster/summary must not
            draw a calm 0% gauge, which reads as "nothing is being used"
            rather than "we could not check". */}
        <Ring label="CPU" pct={summary?.cpu.pct ?? 0}
          unknown={summaryQuery.isError || summary?.cpu.pct == null}
          sub={summaryQuery.isError || summary?.cpu.pct == null ? 'unknown'
            : `${summary.cpu.used_cores} / ${summary.cpu.total_cores} cores`}
          stops={['#F5B544', '#E0862B']} />
        <Ring label="Memory" pct={summary?.mem.pct ?? 0}
          unknown={summaryQuery.isError || summary?.mem.pct == null}
          sub={summaryQuery.isError || summary?.mem.pct == null ? 'unknown'
            : `${fmtBytes(summary.mem.used_bytes)} / ${fmtBytes(summary.mem.total_bytes)}`}
          stops={['#34D3C6', '#5B9DF9']} />
        <Ring label="Storage" pct={summary?.storage.pct ?? 0}
          unknown={summaryQuery.isError || summary?.storage.pct == null}
          sub={summaryQuery.isError || summary?.storage.pct == null ? 'unknown'
            : `${fmtBytes(summary.storage.used_bytes)} / ${fmtBytes(summary.storage.total_bytes)}`}
          stops={['#A78BFA', '#6D5AE6']} />
        {/* No `scope`: every reading in this row is the whole fleet, so
            naming it would state the obvious. The prop is for a per-node
            caller. */}
        <NetworkStat inBps={summary?.net.in_bps} outBps={summary?.net.out_bps}
          ts={net.ts} inValues={net.inValues} outValues={net.outValues}
          unknown={summaryQuery.isError || summary?.net.in_bps == null} />
        </>
        )}
      </div>

      <div className="mt-5">
        <AddHostSection hostCount={new Set((nodes ?? []).map((n) => n.host_id)).size} />
        <QueryState query={nodesQuery}
                    loading={<SkeletonGroup label="Loading nodes" className={nodeGrid}>
                      {Array.from({ length: 3 }, (_, i) => <NodeCardSkeleton key={i} />)}
                    </SkeletonGroup>}
                    emptyTitle="No nodes yet"
                    emptyNote="Proxmox nodes appear here once a host is added."
                    errorTitle="Nodes not readable"
                    errorNote="Proxploy could not reach the backend to list your nodes.">
          {(rows) => {
            const { clusters, standalone } = groupByCluster(dedupeNodes(rows))
            return (
              <>
                {clusters.map(([name, group]) => (
                  <ClusterGroup key={name} name={name} rows={group} />
                ))}
                {standalone.length > 0 && (
                  /* No heading here on purpose: each card already says
                     "standalone" or "in <cluster>", so a group heading would
                     repeat per-card text that is never ambiguous. */
                  <div className={nodeGrid}>
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

      {/* Apps and Virtual machines side by side: an operator comparing the two
          inventories wants both in view at once, and the split is draggable
          because which one deserves the width is a fact about the fleet. No
          border on the group, only the bar: each inventory carries its own
          panel (IconGrid's PANEL).

          `height: auto` overrides the library's inline `height: 100%`, which
          would otherwise resolve against this page's own auto height. NEITHER
          GRID CAPS ITS ROWS, so any fixed height here clips the twenty-first
          app the day somebody installs it: the panels divide width, height
          stays whatever the taller inventory needs.

          minSize is 16rem, not a percentage: the grid inside wants a 10rem
          column plus the panel's padding, which is pixels. They stack below
          lg, where half a row is too narrow for either. */}
      {wide ? (
        <ResizablePanelGroup orientation="horizontal" className="mt-6"
                             style={{ height: 'auto' }}>
          <ResizablePanel defaultSize="50%" minSize="16rem">{appsColumn}</ResizablePanel>
          <ResizableHandle withHandle className="mx-2" />
          <ResizablePanel defaultSize="50%" minSize="16rem">{vmsColumn}</ResizablePanel>
        </ResizablePanelGroup>
      ) : (
        <div className="mt-6 grid grid-cols-1 gap-4">
          {appsColumn}
          {vmsColumn}
        </div>
      )}
    </div>
  )
}

// Minimal slice of GET /hosts/{id}: the opt-in flag and the address the
// "Open Proxmox web UI" button links to; the fleet-overview fields come from
// `node`. node_power_missing feeds HostActionsMenu's Reboot and Power off
// items, null/undefined meaning "not probed since this existed", not
// "granted".
type HostDetail = {
  id: number; name: string; address: string; node_shell_enabled: boolean
  node_power_missing?: boolean | null
  // False ONLY when PVE reported its cluster non-quorate. Null/undefined is a
  // standalone node or a host not polled since the field existed, neither of
  // which is a warning.
  quorate?: boolean | null
  // {capability: [missing privilege]}, {} when clean, undefined/null when never
  // probed. A capability mapped to null means its token could not be read.
  capability_gaps?: Record<string, string[] | null> | null
}

function useHostDetail(id: number) {
  return useQuery({
    queryKey: ['hosts', id],
    queryFn: () => api<HostDetail>(`/hosts/${id}`),
    enabled: Number.isFinite(id),
  })
}

/** Opens the node shell in a window of its own and NEVER goes grey.
 *
 *  Two independent gates could disable it (the terminal.node entitlement and
 *  the per-host opt-in), and a tooltip on a greyed control is invisible on
 *  touch, so the honest reading of it was "this feature is broken". It always
 *  works; when a gate is shut it says which one, and where to open it. */
function NodeShellButton({ hostId, nodeShellEnabled }:
  { hostId: number; nodeShellEnabled: boolean | undefined }) {
  const ent = useEntitlements()
  return (
    <button type="button" className={headerCtl} onClick={() => {
        if (ent.data != null && !ent.has('terminal.node')) {
          notify.error('Not included in your plan.', {
            description: 'Everything else on this page works without it.',
          })
          return
        }
        if (nodeShellEnabled === false) {
          notify.error('Node shells are switched off for this host.', {
            description: 'Turn them on in Settings → Hosts, then try again. '
                       + 'Proxploy keeps this switch separate from your role on '
                       + 'purpose: a root shell on the hypervisor is not '
                       + 'something to inherit by accident.',
          })
          return
        }
        // A console wants its own window rather than a tab: it is a working
        // surface you keep beside the page. Shared with the VM and app
        // consoles (lib/console-window.ts), which is what makes a second click
        // focus the first window instead of opening another session.
        openConsoleWindow('host', hostId)
      }}>
      Node shell ↗
    </button>
  )
}

/** (host id, node row, host detail) for whichever of the three host routes is
 *  mounted. `node` is absent on the legacy /hosts/$hostId route, which
 *  resolves to the entry node. Keyed on (host, node): on a host with several
 *  nodes, `nodes.find(n => n.host_id === id)` returns whichever came first. */
function useNodeContext() {
  const { hostId, node: nodeName } = useParams({ strict: false }) as
    { hostId: string; node?: string }
  const id = Number(hostId)
  const nodesQuery = useNodes()
  const nodes = nodesQuery.data
  const forHost = nodes?.filter((n) => n.host_id === id)
  const node = nodeName
    ? forHost?.find((n) => n.node === nodeName)
    : forHost?.find((n) => n.is_entry) ?? forHost?.[0]
  // The page needs to NAME the entry node, not just know it is not this one.
  const entry = forHost?.find((n) => n.is_entry)
  const hostQuery = useHostDetail(id)
  // Both lookups are undefined until their query lands, so "no node and no
  // host" is true on every cold navigation before it is true of any missing
  // node. Callers need to tell those apart.
  const pending = nodesQuery.isPending || hostQuery.isPending
  return { id, node, host: hostQuery.data, entry, pending }
}

const TABS = [
  { path: '.', label: 'Overview' },
  { path: 'hardware', label: 'Hardware' },
]

/** The host page's frame: who this machine is, where to open it, and the
 *  tabs. The body is a routed child. */
export function NodeDetailPage({ inline = false }: { inline?: boolean }) {
  const { id, node, host, pending } = useNodeContext()
  // Capabilities whose token is short of a privilege its role now carries, or
  // whose token could not be read at all. {} is the clean case and undefined
  // means never probed; both count as zero.
  const gapCount = Object.keys(host?.capability_gaps ?? {}).length
  // Without this check, a cold load of /hosts/1/pve showed "Node not found,
  // it may have been removed" for as long as /nodes took to answer: the page
  // picking the most alarming answer while it still had none.
  //
  // Returning early also keeps the Outlet from mounting, so NodeOverview and
  // NodeHardware need no placeholder of their own.
  if (pending) {
    return (
      <SkeletonGroup label="Loading node">
        <div className="mb-5 flex items-center justify-between gap-3">
          <div>
            <SkeletonLine className="w-40 text-[20px]" />
            <SkeletonLine className="w-56 text-[12px]" />
          </div>
          <div className="flex items-center gap-3">
            <Skeleton className="h-[30px] w-24 rounded-ctl" />
            <Skeleton className="h-[27px] w-44 rounded-ctl" />
            <Skeleton className="h-[19px] w-20 rounded-full" />
            <Skeleton className="h-[30px] w-10 rounded-ctl" />
          </div>
        </div>
        <div className="mb-5 flex gap-1 border-b border-line-soft">
          {TABS.map((t) => (
            <SkeletonLine key={t.path} className="mx-3 my-2 w-16 text-[13px]" />
          ))}
        </div>
      </SkeletonGroup>
    )
  }
  if (!node && !host) {
    return <EmptyState title="Node not found" note="It may have been removed." />
  }
  return (
    <div>
      <div className="mb-5 flex items-center justify-between gap-3">
        <div>
          <h1 className="font-mono text-[20px] font-semibold">{node?.name ?? host?.name}</h1>
          {node && (
            <div className="text-[12px] text-text-3">
              {node.cluster ? `cluster · ${node.cluster}` : 'standalone'} · PVE {node.pve_version ?? '?'}
            </div>
          )}
        </div>
        <div className="flex items-center gap-3">
          {/* Entry node only: a shell ticket is minted for the host's own
              node, so offering it elsewhere would open a shell on a different
              box than the page is showing. */}
          {(node?.is_entry ?? true) && (
            <NodeShellButton hostId={id} nodeShellEnabled={host?.node_shell_enabled} />
          )}
          {host?.address && (
            // rel="noopener": without it the opened page can steer this one
            // through window.opener.
            <a href={host.address} target="_blank" rel="noopener noreferrer"
              className={headerCtl}>
              Open Proxmox web UI ↗
            </a>
          )}
          {node && <StatusPill status={node.status} />}
          {/* A node without quorum answers /version and /cluster/resources
              perfectly and refuses every WRITE, so "Connected" on its own is a
              lie an operator acts on. Sits beside the status rather than
              replacing it, because reads really do work. */}
          {/* Privilege drift, shown WITHOUT anyone pressing Test connection: a
              role gains privileges over time and a token generated earlier
              then fails with a 403 partway through a job. The poll loop
              refreshes this every half hour. */}
          {gapCount > 0 && (
            <Link to="/settings" search={{ section: 'hosts' } as never}
              title="Re-run the setup script from Settings to grant them."
              className="rounded-ctl border border-amber/30 bg-amber-dim px-2 py-0.5
                         text-[12px] text-amber">
              {gapCount === 1 ? '1 token missing privileges'
                : `${gapCount} tokens missing privileges`}
            </Link>
          )}
          {host?.quorate === false && (
            <span title="Proxmox reports this cluster has lost quorum. /etc/pve is
                         read-only, so installs, guest edits and storage changes will
                         fail until quorum returns."
              className="rounded-ctl border border-red/30 bg-red-dim px-2 py-0.5
                         text-[12px] text-red">
              No quorum: writes will fail
            </span>
          )}
          {/* Node-scoped (Reboot/Power off target THIS node) and host-scoped
              (Edit changes the Host record) both live behind one trigger, so
              both must resolve before it can render. */}
          {node?.node && host && (
            <HostActionsMenu hostId={id} node={node.node}
              host={{ name: host.name, address: host.address }}
              nodePowerMissing={host.node_power_missing} />
          )}
        </div>
      </div>
      <div className="mb-5 flex gap-1 border-b border-line-soft">
        {TABS.map((t) => (
          <Link key={t.path} to={t.path as never}
            from={'/hosts/$hostId/$node' as never}
            activeOptions={{ exact: t.path === '.' }}
            className={tabTrigger}>
            {t.label}
          </Link>
        ))}
      </div>
      {/* The legacy /hosts/$hostId route has no routed children to fill an
          Outlet and renders this page while its redirect resolves; the inline
          Overview keeps that moment from being a blank frame. */}
      {inline ? <NodeOverview /> : <Outlet />}
    </div>
  )
}

/** Charts and the node shell belong to the entry node: the `host:<id>` series
 *  is recorded there and the shell ticket is minted for it. Absent elsewhere,
 *  they read as a missing feature rather than a deliberate one. */
function EntryNodeNote({ hostId, entry }: { hostId: number; entry?: NodeRow }) {
  const entryNode = entry?.node
  return (
    <div className="rounded-card border border-line border-l-2 border-l-amber
                    bg-panel p-4 text-[13px] text-text-2">
      Metrics and the node shell are recorded on{' '}
      {entryNode
        ? <span className="font-mono text-text">{entryNode}</span>
        : <span>this host&rsquo;s entry node</span>}
      , the node Proxploy connects through.{' '}
      {entryNode && (
        <Link to={'/hosts/$hostId/$node' as never}
          params={{ hostId: String(hostId), node: entryNode } as never}
          className={amberLinkCls}>
          Open {entryNode} →
        </Link>
      )}
    </div>
  )
}

/** What to draw for "Guests on this host", derived from BOTH the apps and
 *  VMs queries at once.
 *
 *  The one behaviour that must hold: if either list has rows, those rows
 *  render. Pending if either query is still pending; a hard error only when
 *  BOTH failed; otherwise whatever rows the succeeding side has, empty only
 *  when that combined count is zero, and a partial-failure note, not a
 *  swallowed error, when one side failed and the other still has rows. */
type GuestsState =
  | { kind: 'loading' }
  | { kind: 'error'; title: string; note: string }
  | { kind: 'empty' }
  | { kind: 'ok'; guests: ReturnType<typeof toGuests>; warning?: string }

function combineGuestQueries(
  appsQuery: UseQueryResult<AppRow[]>,
  vmsQuery: UseQueryResult<VmRow[]>,
): GuestsState {
  if (appsQuery.isPending || vmsQuery.isPending) return { kind: 'loading' }
  const appsFailed = appsQuery.isError
  const vmsFailed = vmsQuery.isError
  if (appsFailed && vmsFailed) {
    return {
      kind: 'error', title: 'Guests not readable',
      note: 'Proxploy could not reach the backend to list guests on this node.',
    }
  }
  const apps = appsFailed ? [] : appsQuery.data ?? []
  const vms = vmsFailed ? [] : vmsQuery.data ?? []
  const guests = toGuests(apps, vms)
  if (guests.length === 0) {
    // The failed side might genuinely have guests we simply could not read;
    // saying "no guests" here would be no more honest than the bug this
    // replaces. Name the side that failed instead.
    if (appsFailed) {
      return {
        kind: 'error', title: 'Apps not readable',
        note: 'Proxploy could not reach the backend to list apps on this node. '
            + 'This node has no VMs either, but that count is only certain, not the apps one.',
      }
    }
    if (vmsFailed) {
      return {
        kind: 'error', title: 'VMs not readable',
        note: 'Proxploy could not reach the backend to list VMs on this node. '
            + 'This node has no apps either, but that count is only certain, not the VMs one.',
      }
    }
    return { kind: 'empty' }
  }
  return {
    kind: 'ok', guests,
    warning: appsFailed
      ? 'Apps could not be read. This list is missing whatever apps this node has.'
      : vmsFailed
        ? 'VMs could not be read. This list is missing whatever VMs this node has.'
        : undefined,
  }
}

export function NodeOverview() {
  const { id, node, host, entry } = useNodeContext()
  // mem_pct, not mem_bytes: charting the percentage puts all three of these
  // on one 0..100 scale so they can be read side by side. The absolute figures
  // are one row up, in the KV grid.
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
  const guestsState = combineGuestQueries(nodeAppsQuery, nodeVmsQuery)
  const guestCount = guestsState.kind === 'ok' ? guestsState.guests.length : 0
  if (!node && !host) return null
  return (
    <div className="lg:grid lg:grid-cols-[290px_minmax(0,1fr)] lg:items-start lg:gap-5">
      {/* minmax(0,1fr), not 1fr: it lets the track shrink below the charts'
          intrinsic content width instead of refusing to shrink at all. */}
      <div className="mb-5 lg:sticky lg:top-16 lg:mb-0 lg:max-h-[calc(100vh-5rem)] lg:overflow-y-auto">
        {/* The rail is dense reference material, not worth pinning at the
            cost of reachability: with /status answering it runs to roughly
            700px, and lg:top-16 alone left its bottom rows below the fold on
            any viewport under ~765px tall, comfortably inside `lg`. max-h +
            overflow-y-auto trades that for a nested scrollbar, which can
            always reach the bottom. */}
        {node?.node && (
          <NodeIdentityRail hostId={id} node={node.node} snapshot={node} />
        )}
      </div>
      <div>
        {/* Entry node only: the `host:<id>` series is recorded from the node
            Proxploy connects through, so drawing it under any other node would
            be charting a different machine. */}
        {node && (node.is_entry
          ? (
            /* Each chart owns its range: "is the CPU spiking now" and "did
               storage creep all week" are different questions.
               @container/@3xl, not lg: a chart card needs roughly 200px of
               inner width for its non-wrapping range group, and this RIGHT
               COLUMN, not the viewport, decides that width. The 290px rail
               plus its gap can hold the column under 200px well past `lg`,
               which is what a viewport-keyed `lg:grid-cols-3` missed. */
            <div className="@container">
              <div className="grid grid-cols-1 gap-4 @3xl:grid-cols-3">
                <div className={card}>
                  <MetricChart target={`host:${id}`} metric="cpu_pct"
                    unit="percent" label="CPU" accent="amber" />
                </div>
                <div className={card}>
                  <MetricChart target={`host:${id}`} metric="mem_pct"
                    unit="percent" label="Memory" accent="cyan" />
                </div>
                {/* Already recorded every cycle by the poller (`disk_pct`), and
                    correctly shared-vs-local deduped there, so this series is
                    the host's real fill, not the sum of the node rows. */}
                <div className={card}>
                  <MetricChart target={`host:${id}`} metric="disk_pct"
                    unit="percent" label="Storage" accent="violet" />
                </div>
              </div>
            </div>
          )
          : <EntryNodeNote hostId={id} entry={entry} />)}
        <div className="mt-5">
          {/* "on this host", not "on this node": neither apps nor vms records
              which node of the cluster a guest sits on, so this list is
              host-wide and says so. */}
          <h2 className="mb-3 font-display text-[16px] font-semibold">
            Guests on this host ({guestCount})
          </h2>
          {guestsState.kind === 'loading' && (
            <SkeletonGroup label="Loading guests"><GuestListSkeleton /></SkeletonGroup>
          )}
          {guestsState.kind === 'error' && (
            <EmptyState title={guestsState.title} note={guestsState.note} />
          )}
          {guestsState.kind === 'empty' && (
            <EmptyState title="No guests on this node"
              note="Installed or adopted apps and QEMU guests on this node appear here." />
          )}
          {guestsState.kind === 'ok' && (
            <>
              {guestsState.warning && (
                <p role="alert" className="mb-3 rounded-ctl border border-amber/30
                                           bg-amber-dim p-2 text-[12.5px] text-text-2">
                  <span className="text-amber">{guestsState.warning}</span>
                </p>
              )}
              <GuestList guests={guestsState.guests} />
            </>
          )}
        </div>
      </div>
    </div>
  )
}

export function NodeHardware() {
  const { id, node } = useNodeContext()
  if (!node?.node) return null
  return <HardwareTab hostId={id} node={node.node} />
}

/** /hosts/$hostId, kept alive for every link minted before node detail grew
 *  its node segment. It resolves to the host's ENTRY node and renders the same
 *  page meanwhile: a redirect that first showed a blank screen would be a
 *  regression for the standalone host this used to serve. */
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
  return <NodeDetailPage inline />
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

export const hostOverviewRoute = createRoute({
  getParentRoute: () => nodeDetailRoute,
  path: '/',
  component: NodeOverview,
})

export const hostHardwareRoute = createRoute({
  getParentRoute: () => nodeDetailRoute,
  path: 'hardware',
  component: NodeHardware,
})

export const hostEntryRoute = createRoute({
  getParentRoute: () => shellRoute,
  path: '/hosts/$hostId',
  component: HostEntryRedirect,
})
