import { useState } from 'react'
import { createRoute } from '@tanstack/react-router'
import { toast } from 'sonner'
import { shellRoute } from './shell'
import { useEntitlements } from '../api/hooks'
import { errBody, useApplyNetwork, useBridges, useDeleteBridge, useRevertNetwork, useThroughput } from '../api/network'
import type { Attachment, HostThroughput, Iface, NetSeries, NodeIfaces } from '../api/network'
import { BridgeForm } from '../components/BridgeForm'
import { ConfirmSelfDialog } from '../components/ConfirmSelfDialog'
import { EmptyState } from '../components/EmptyState'
import { JobLog } from '../components/JobLog'
import { LockVeil } from '../components/LockVeil'
import { NicForm } from '../components/NicForm'
import { Sparkline } from '../components/charts/Sparkline'
import { Button } from '../components/ui/button'
import { fmtBps } from '../lib/format'

const card = 'rounded-card border border-line-soft bg-panel p-5'
const th = 'pb-2 font-medium'

/** Newest non-null sample, or null for an empty window. */
function lastValue(s?: NetSeries): number | null {
  const v = s?.value ?? []
  for (let i = v.length - 1; i >= 0; i--) if (v[i] != null) return v[i] as number
  return null
}

// ponytail: doc 06's "Zone badge" renders the VLAN posture that
// GET /nodes/{node}/network actually reports. PVE SDN zones live behind a
// separate /cluster/sdn/zones API this phase does not read; wire that in when a
// real SDN deployment asks for it.
function zoneLabel(i: Iface): string {
  if (i.vlan_id != null) return `VLAN ${i.vlan_id}`
  if (i.vlan_aware) return 'VLAN-aware'
  return i.type ?? 'unknown'
}

/** Subnet column for both the Bridges card and the per-node interfaces table. */
function subnetLabel(i: Iface): string {
  return i.cidr ?? i.address ?? 'unknown'
}

/** Ports column for both the Bridges card and the per-node interfaces table. */
function portsLabel(i: Iface): string {
  return i.bridge_ports || i.slaves || 'unknown'
}

function BridgesCard({ nodes }: { nodes: NodeIfaces[] }) {
  const rows = nodes.flatMap((n) =>
    n.interfaces.filter((i) => i.type === 'bridge').map((i) => ({ node: n, iface: i })))
  return (
    <div className={`${card} lg:col-span-2`}>
      <h2 className="mb-3 font-display text-[16px] font-semibold">Bridges</h2>
      {rows.length === 0 ? (
        <p className="text-[12.5px] text-text-3">
          No bridges reported yet, Proxploy reads them live from each node on every load.
        </p>
      ) : (
        <table aria-label="Bridges" className="w-full text-left text-[13px]">
          <thead>
            <tr className="text-[11px] uppercase text-text-3">
              <th scope="col" className={th}>Bridge</th>
              <th scope="col" className={th}>Node</th>
              <th scope="col" className={th}>Subnet</th>
              <th scope="col" className={th}>Zone</th>
              <th scope="col" className={th}>Ports</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(({ node, iface }) => (
              <tr key={`${node.host_id}:${node.node}:${iface.iface}`}
                  className="border-t border-line-soft hover:bg-panel-2">
                <td className="py-2.5 font-mono">
                  {iface.iface}
                  {!iface.active && <span className="ml-2 text-[11px] text-text-3">down</span>}
                </td>
                <td className="py-2.5 text-text-2">{node.node}</td>
                <td className="py-2.5 font-mono text-text-2">
                  {subnetLabel(iface)}
                </td>
                <td className="py-2.5">
                  <span className="rounded-full border border-blue/30 bg-blue-dim px-2 py-0.5 text-[11px] text-blue">
                    {zoneLabel(iface)}
                  </span>
                </td>
                <td className="py-2.5 font-mono text-text-2">{portsLabel(iface)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

function ThroughputCard() {
  // 1h window, matching the cluster page's network card.
  const { data } = useThroughput(1)
  const hosts = data?.hosts ?? []
  const total = (pick: (h: HostThroughput) => NetSeries) =>
    hosts.length ? hosts.reduce((a, h) => a + (lastValue(pick(h)) ?? 0), 0) : null
  // ponytail: the two sparklines chart the first host's series, the same
  // simplification cluster.tsx made for its network card, the ↓/↑ figures above
  // them are already fleet-wide. Summed series when a real fleet shows it matters.
  const first = hosts[0]
  return (
    <div className={card}>
      <h2 className="mb-1 font-display text-[16px] font-semibold">Throughput</h2>
      <div className="mb-3 font-mono text-[13px] text-text-2">
        ↓ {fmtBps(total((h) => h.in))} · ↑ {fmtBps(total((h) => h.out))}
      </div>
      <div className="text-[11px] uppercase tracking-wide text-text-3">In</div>
      <Sparkline ts={first?.in.ts ?? []} values={first?.in.value ?? []} color="#5B9DF9" />
      <div className="mt-3 text-[11px] uppercase tracking-wide text-text-3">Out</div>
      <Sparkline ts={first?.out.ts ?? []} values={first?.out.value ?? []} color="#34D3C6" />
      {hosts.length > 1 && (
        <p className="mt-3 text-[11.5px] text-text-3">
          Figures are fleet-wide; the charts show {first?.host_name}.
        </p>
      )}
    </div>
  )
}

function AttachmentMap({ attachments, nodes }: {
  attachments: Attachment[]; nodes: NodeIfaces[]
}) {
  const ent = useEntitlements()
  // has() is false until the first fetch resolves, gating on !has() alone
  // greys the button out for every plan during load.
  const denied = ent.data != null && !ent.has('network.guest_config')
  const [editing, setEditing] = useState<Attachment | null>(null)
  const bridgesOn = (node: string) =>
    nodes.filter((n) => n.node === node)
      .flatMap((n) => n.interfaces.filter((i) => i.type === 'bridge').map((i) => i.iface))

  return (
    <div className={`${card} mt-4`}>
      <h2 className="mb-1 font-display text-[16px] font-semibold">Guest attachments</h2>
      <p className="mb-3 text-[12.5px] text-text-3">Which guest sits on which bridge.</p>
      {attachments.length === 0 ? (
        <p className="text-[12.5px] text-text-3">No guest NICs found on this host.</p>
      ) : (
        <table aria-label="Guest attachments" className="w-full text-left text-[13px]">
          <thead>
            <tr className="text-[11px] uppercase text-text-3">
              <th scope="col" className={th}>Guest</th>
              <th scope="col" className={th}>NIC</th>
              <th scope="col" className={th}>Bridge</th>
              <th scope="col" className={th}>VLAN</th>
              <th scope="col" className={th}>Firewall</th>
              <th scope="col" className={th}>MAC</th>
              <th scope="col" className={th}></th>
            </tr>
          </thead>
          <tbody>
            {attachments.map((a) => (
              <tr key={`${a.guest_type}:${a.guest_id}:${a.iface}`}
                  className="border-t border-line-soft hover:bg-panel-2">
                <td className="py-2.5 font-mono">
                  {a.name ?? `guest ${a.vmid}`}
                  <span className="ml-2 text-[11px] text-text-3">
                    {a.guest_type === 'app' ? 'CT' : 'VM'} {a.vmid}
                  </span>
                </td>
                <td className="py-2.5 font-mono text-text-2">{a.iface}</td>
                <td className="py-2.5 font-mono text-text-2">{a.bridge ?? 'unknown'}</td>
                <td className="py-2.5 font-mono text-text-2">{a.tag ?? 'unknown'}</td>
                <td className={`py-2.5 text-[12px] ${a.firewall ? 'text-green' : 'text-text-3'}`}>
                  {a.firewall ? 'on' : 'off'}
                </td>
                <td className="py-2.5 font-mono text-[12px] text-text-3">{a.macaddr ?? 'unknown'}</td>
                <td className="py-2.5 text-right">
                  <Button variant="ghost" className="px-2 py-1 text-[11px]"
                          disabled={denied}
                          title={denied ? 'Not included in your plan' : undefined}
                          onClick={() => setEditing(a)}>
                    Edit
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {editing && (
        <NicForm nic={editing} bridges={bridgesOn(editing.node)}
                 onClose={() => setEditing(null)} />
      )}
    </div>
  )
}

function HostNetworkSection({ nodes }: { nodes: NodeIfaces[] }) {
  const ent = useEntitlements()
  const locked = ent.data != null && !ent.has('network.host_config')
  const [editing, setEditing] = useState<{ hostId: number; node: string; iface: Iface | null } | null>(null)
  const [guard, setGuard] = useState<{ hostId: number; node: string; phrase: string; detail: string } | null>(null)
  const [jobId, setJobId] = useState<number | null>(null)
  const apply = useApplyNetwork()
  const revert = useRevertNetwork()
  const remove = useDeleteBridge()

  const fire = (hostId: number, node: string, confirm?: string) =>
    apply.mutate({ hostId, node, confirm }, {
      onSuccess: (r) => { setGuard(null); setJobId(r.job.id) },
      onError: (e) => {
        const b = errBody(e)
        // The backend refuses an unconfirmed apply with the node name as the
        // phrase, deliberately the same envelope selfguard uses; escalate to
        // the typed-confirmation dialog and re-fire with what was typed.
        if (b?.error === 'confirm_required') {
          setGuard({ hostId, node, phrase: String(b.confirm_phrase ?? node),
                     detail: String(b.detail ?? '') })
          return
        }
        toast.error('Could not apply the staged config, the node was not changed.')
      },
    })

  const drop = (hostId: number, node: string, iface: string) => {
    if (!window.confirm(
      `Stage removal of ${iface} on ${node}? It disappears from the live config only when you apply.`)) return
    remove.mutate({ hostId, node, iface }, {
      onSuccess: () => toast(`${iface} removal staged on ${node}`),
      onError: () => toast.error(`Could not stage the removal of ${iface}.`),
    })
  }

  return (
    <div className="mt-4">
      <LockVeil locked={locked}
        title="Host network editing is a Pro feature"
        subtitle="Create bridges and VLANs on the node itself, then apply them.">
        <section className={card}>
          <h2 className="font-display text-[16px] font-semibold">Host bridges &amp; VLANs</h2>
          <p className="mt-1 text-[12.5px] text-text-3">
            Edits here are <span className="text-text-2">staged</span>. Proxmox writes them to{' '}
            <span className="font-mono">/etc/network/interfaces.new</span> and changes nothing
            until you apply.
          </p>
          <p className="mt-2 rounded-ctl border border-red/30 bg-red-dim p-2 text-[12.5px] text-text-2">
            <span className="text-red">Applying reloads the node&apos;s interfaces.</span> If the
            staged config is wrong the node loses its network, and the only way back is its
            physical console; there is no undo from here.
          </p>

          {jobId != null && (
            <div className="mt-4">
              <JobLog jobId={jobId} />
              <Button className="mt-3" variant="ghost" onClick={() => setJobId(null)}>Close</Button>
            </div>
          )}

          {nodes.map((n) => (
            <div key={`${n.host_id}:${n.node}`} className="mt-4 border-t border-line-soft pt-4">
              <div className="mb-2 flex flex-wrap items-center gap-2">
                <h3 className="font-mono text-[13px]">{n.node}</h3>
                <span className="text-[11.5px] text-text-3">{n.host_name}</span>
                <div className="ml-auto flex gap-2">
                  <Button variant="ghost" className="px-2 py-1 text-[11px]"
                          onClick={() => setEditing({ hostId: n.host_id, node: n.node, iface: null })}>
                    Add bridge
                  </Button>
                  <Button variant="ghost" className="px-2 py-1 text-[11px]"
                          disabled={revert.isPending}
                          onClick={() => revert.mutate({ hostId: n.host_id, node: n.node }, {
                            onSuccess: () => toast(`Staged changes discarded on ${n.node}`),
                            onError: () => toast.error('Could not discard the staged config.'),
                          })}>
                    Discard staged
                  </Button>
                  <Button variant="danger" className="px-2 py-1 text-[11px]"
                          disabled={apply.isPending}
                          onClick={() => fire(n.host_id, n.node)}>
                    Apply staged config
                  </Button>
                </div>
              </div>
              <table aria-label={`Interfaces on ${n.node}`} className="w-full text-left text-[13px]">
                <thead>
                  <tr className="text-[11px] uppercase text-text-3">
                    <th scope="col" className={th}>Interface</th>
                    <th scope="col" className={th}>Type</th>
                    <th scope="col" className={th}>Subnet</th>
                    <th scope="col" className={th}>Ports</th>
                    <th scope="col" className={th}>State</th>
                    <th scope="col" className={th}></th>
                  </tr>
                </thead>
                <tbody>
                  {n.interfaces.map((i) => (
                    <tr key={i.iface} className="border-t border-line-soft hover:bg-panel-2">
                      <td className="py-2.5 font-mono">{i.iface}</td>
                      <td className="py-2.5 text-text-2">{i.type ?? 'unknown'}</td>
                      <td className="py-2.5 font-mono text-text-2">
                        {subnetLabel(i)}
                      </td>
                      <td className="py-2.5 font-mono text-text-2">
                        {portsLabel(i)}
                      </td>
                      <td className={`py-2.5 text-[12px] ${i.active ? 'text-green' : 'text-text-3'}`}>
                        {i.active ? 'up' : 'down'}
                      </td>
                      <td className="py-2.5 text-right">
                        <Button variant="ghost" className="px-2 py-1 text-[11px]"
                                onClick={() => setEditing({ hostId: n.host_id, node: n.node, iface: i })}>
                          Edit
                        </Button>
                        <Button variant="danger" className="ml-2 px-2 py-1 text-[11px]"
                                onClick={() => drop(n.host_id, n.node, i.iface)}>
                          Remove
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
        </section>
      </LockVeil>

      {editing && (
        <BridgeForm hostId={editing.hostId} node={editing.node} iface={editing.iface}
                    onClose={() => setEditing(null)} />
      )}
      {guard && (
        <ConfirmSelfDialog
          title={`Apply network config on ${guard.node}`}
          phrase={guard.phrase}
          detail={guard.detail}
          onConfirm={(typed) => fire(guard.hostId, guard.node, typed)}
          onCancel={() => setGuard(null)} />
      )}
    </div>
  )
}

export function NetworkPage() {
  const { data, isError } = useBridges()
  const nodes = data?.nodes ?? []
  const errors = data?.errors ?? []
  const bridgeCount = nodes.reduce(
    (a, n) => a + n.interfaces.filter((i) => i.type === 'bridge').length, 0)

  return (
    <div>
      <div className="mb-5">
        <h1 className="font-display text-[22px] font-semibold">Network</h1>
        <div className="text-[12px] text-text-3">
          {data ? `${bridgeCount} bridges across ${nodes.length} nodes` : '…'}
        </div>
      </div>

      {isError ? (
        <EmptyState title="Network not readable"
          note="Proxploy reads bridges live from each node, check that the host is connected." />
      ) : (
        <>
          {errors.length > 0 && (
            // list_bridges() degrades per host instead of 500ing the whole
            // page (BLOCKING 3), everything below is genuinely partial, so
            // that must be visible, not just a smaller-than-expected count.
            // Same amber/warning vocabulary as RetentionSection's dry-run
            // banner, not a new one.
            <p role="alert"
               className="mb-4 rounded-ctl border border-amber/30 bg-amber-dim p-2 text-[12.5px] text-text-2">
              <span className="text-amber">
                {errors.length === 1 ? '1 host' : `${errors.length} hosts`} could not be read.
              </span>{' '}
              {errors.map((e) => e.host_name).join(', ')}; the page below is missing whatever
              those hosts would have shown.
            </p>
          )}
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
            <BridgesCard nodes={nodes} />
            <ThroughputCard />
          </div>
          <AttachmentMap attachments={data?.attachments ?? []} nodes={nodes} />
          <HostNetworkSection nodes={nodes} />
        </>
      )}
    </div>
  )
}

// shellRoute comes from ./shell, never ../router; importing router.tsx here
// would force its eager createRouter() to run mid-cycle (cluster.tsx:273-277).
export const networkRoute = createRoute({
  getParentRoute: () => shellRoute,
  path: '/network',
  component: NetworkPage,
})
