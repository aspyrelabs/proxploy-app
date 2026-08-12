import { useQuery } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'
import { api } from '../api/client'
import { fmtBytes } from '../lib/format'
import { KVGrid } from './KVGrid'

/** GET /hosts/{id}/nodes/{node}/hardware.
 *
 *  Every section is gathered independently by the backend, so any one of them
 *  can be `null` with its reason named in `unreadable` while its siblings
 *  carry data: a token narrow enough to be refused /hardware/pci still answers
 *  the disks. Only a node that answered NOTHING reaches the error branch. */
type Disk = {
  devpath: string
  model: string | null
  serial: string | null
  size: number | null
  type: string | null
  health: string | null
  wearout: number | null
  used: string | null
  osd_id: number | null
}

type Iface = {
  iface: string
  type: string | null
  method: string | null
  method6: string | null
  families: string[]
  active: boolean
  exists: boolean
  autostart: boolean
  cidr: string | null
  gateway: string | null
  bridge_ports: string | null
  altnames: string[]
}

type Pci = {
  id: string
  class_id: string | null
  class_name: string | null
  device_id: string | null
  device_name: string | null
  vendor_id: string | null
  vendor_name: string | null
  subsystem_vendor_name: string | null
  iommu_group: number | null
}

type Service = {
  name: string
  desc: string | null
  state: string | null
  active_state: string | null
  unit_state: string | null
}

type Refusal = { error: string; detail: string }

type Hardware = {
  disks: Disk[] | null
  network: Iface[] | null
  pci: Pci[] | null
  services: Service[] | null
  subscription: { status: string | null; message: string | null
                  level: string | null; server_id: string | null } | null
  dns: { servers: string[]; search: string | null } | null
  time: { timezone: string | null; localtime: number | null; utc: number | null } | null
  unreadable: Record<string, Refusal>
}

const card = 'rounded-card border border-line-soft bg-panel p-5'
const th = 'pb-2 font-normal'
const headRow = 'text-[10.5px] uppercase tracking-wide text-text-3'

/** One section of the tab, with the three states it can be in kept distinct.
 *
 *  "The node refused to tell us" and "the node has none of these" look
 *  identical as a bare empty table, and they call for opposite reactions:
 *  one is a privilege to widen, the other is just the truth about the box. */
function Section({ title, noun, refusal, hint, empty, children }: {
  title: string
  noun: string
  refusal?: Refusal
  hint?: ReactNode
  empty?: boolean
  children?: ReactNode
}) {
  return (
    <section className={card}>
      <h2 className="mb-3 font-display text-[15px] font-semibold">{title}</h2>
      {refusal ? (
        <>
          <p className="text-[13px] text-text-2">
            This node would not report its {noun}.
          </p>
          <p className="mt-1 break-words font-mono text-[11.5px] text-text-3">
            {refusal.detail}
          </p>
          {hint && <p className="mt-1 text-[12px] text-text-3">{hint}</p>}
        </>
      ) : empty ? (
        <p className="text-[13px] text-text-2">This node reports no {noun}.</p>
      ) : children}
    </section>
  )
}

export function HardwareTab({ hostId, node }: { hostId: number; node: string }) {
  const q = useQuery({
    queryKey: ['hosts', hostId, 'node', node, 'hardware'],
    queryFn: () => api<Hardware>(`/hosts/${hostId}/nodes/${node}/hardware`),
    retry: false,
  })

  if (q.isError) {
    // The backend only 502s when NOT ONE section came back, which is the node
    // being unreachable rather than a token missing a privilege.
    return (
      <section className={card}>
        <h2 className="mb-2 font-display text-[15px] font-semibold">Hardware</h2>
        <p className="text-[13px] text-text-2">
          This node would not report its hardware.
        </p>
        <p className="mt-1 text-[12px] text-text-3">
          Nothing at all could be read from {node}, so this is the node being
          out of reach rather than one privilege being missing.
        </p>
      </section>
    )
  }
  if (!q.data) return null
  const d = q.data
  const bad = d.unreadable ?? {}

  return (
    <div className="space-y-4">
      <Section title="Disks" noun="disks" refusal={bad.disks}
        empty={d.disks?.length === 0}
        hint={<>Reading /nodes/{node}/disks/list needs Sys.Audit on the node.
          A token without it can still run everything else on this page.</>}>
        <Table head={['Device', 'Model', 'Serial', 'Size', 'Type', 'Used by',
                      'Health', 'Wearout']}>
          {(d.disks ?? []).map((disk) => (
            <tr key={disk.devpath} className="border-t border-line-soft align-middle">
              <td className="py-2 font-mono">{disk.devpath}</td>
              <td className="py-2 text-text-2">{disk.model ?? 'unknown'}</td>
              <td className="py-2 font-mono text-text-3">{disk.serial ?? 'unknown'}</td>
              <td className="py-2 font-mono">
                {disk.size != null ? fmtBytes(disk.size) : 'unknown'}
              </td>
              <td className="py-2 text-text-2">{disk.type ?? 'unknown'}</td>
              <td className="py-2 text-text-2">
                {disk.osd_id != null ? `Ceph OSD ${disk.osd_id}` : disk.used ?? 'unknown'}
              </td>
              <td className={`py-2 ${disk.health === 'PASSED' ? 'text-green' : 'text-amber'}`}>
                {disk.health ?? 'unknown'}
              </td>
              {/* PVE reports wearout as life REMAINING, not consumed. 99 is
                  a nearly-new disk, so labelling it "used" inverts it. */}
              <td className="py-2 font-mono">
                {disk.wearout != null ? `${disk.wearout}% left` : 'unknown'}
              </td>
            </tr>
          ))}
        </Table>
      </Section>

      <Section title="Network interfaces" noun="network interfaces"
        refusal={bad.network} empty={d.network?.length === 0}>
        <Table head={['Interface', 'Type', 'Address', 'Gateway', 'Ports', 'State']}>
          {(d.network ?? []).map((n) => (
            <tr key={n.iface} className="border-t border-line-soft align-middle">
              <td className="py-2 font-mono">{n.iface}</td>
              <td className="py-2 text-text-2">{n.type ?? 'unknown'}</td>
              <td className="py-2 font-mono">
                {n.cidr ?? (n.method === 'dhcp' ? 'from DHCP' : 'none')}
              </td>
              <td className="py-2 font-mono text-text-2">{n.gateway ?? 'unknown'}</td>
              <td className="py-2 font-mono text-text-2">{n.bridge_ports ?? 'unknown'}</td>
              <td className={`py-2 ${n.active ? 'text-green' : 'text-text-3'}`}>
                {n.active ? 'up' : 'down'}
                {!n.autostart && n.exists ? ' · no autostart' : ''}
              </td>
            </tr>
          ))}
        </Table>
        {/* PVE's /nodes/{n}/network carries no link speed, so this table does
            not pretend to one. */}
      </Section>

      <PciSection devices={d.pci} refusal={bad.pci} />
      <ServicesSection services={d.services} refusal={bad.services} />
      <NodeFacts subscription={d.subscription} dns={d.dns} time={d.time} bad={bad} />
    </div>
  )
}

function Table({ head, children }: { head: string[]; children: ReactNode }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-[13px]">
        <thead>
          <tr className={headRow}>
            {head.map((h) => <th key={h} className={th}>{h}</th>)}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  )
}

/** Eleven devices in one flat list is a wall of hex ids. Grouped by the PCI
 *  base class the backend resolved, it is four or five short groups a person
 *  can skim for the one they want to pass through to a guest. */
function PciSection({ devices, refusal }: { devices: Pci[] | null; refusal?: Refusal }) {
  const groups = new Map<string, Pci[]>()
  for (const p of devices ?? []) {
    const key = p.class_name ?? p.class_id ?? 'Unknown class'
    groups.set(key, [...(groups.get(key) ?? []), p])
  }
  return (
    <Section title="PCI devices" noun="PCI devices" refusal={refusal}
      empty={devices?.length === 0}>
      <div className="space-y-4">
        {[...groups.entries()].map(([cls, rows]) => (
          <div key={cls}>
            <div className="mb-1 text-[10.5px] uppercase tracking-wide text-text-3">
              {cls}
            </div>
            <table className="w-full text-left text-[13px]">
              <tbody>
                {rows.map((p) => (
                  <tr key={p.id} className="border-t border-line-soft align-middle">
                    <td className="w-32 py-2 font-mono text-text-2">{p.id}</td>
                    <td className="py-2">{p.device_name ?? p.device_id ?? 'unknown'}</td>
                    <td className="py-2 text-text-2">{p.vendor_name ?? 'unknown'}</td>
                    {/* The IOMMU group is what decides whether this device can
                        be handed to a guest on its own, which is the only
                        reason most people open this list. */}
                    <td className="w-28 py-2 text-right font-mono text-text-3">
                      {p.iommu_group != null ? `IOMMU ${p.iommu_group}` : ''}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
      </div>
    </Section>
  )
}

/** Twenty-three rows of "running" is not information. What an operator came
 *  here for is the one unit that is NOT running, so that is what shows by
 *  default; the rest are counted, never silently dropped, and one click away. */
function ServicesSection({ services, refusal }: {
  services: Service[] | null; refusal?: Refusal
}) {
  const [all, setAll] = useState(false)
  const list = services ?? []
  const stopped = list.filter((s) => s.state !== 'running')
  const shown = all ? list : stopped

  return (
    <Section title="Services" noun="services" refusal={refusal}
      empty={list.length === 0}>
      {stopped.length === 0 && !all ? (
        <p className="text-[13px] text-text-2">
          All {list.length} services are running.
        </p>
      ) : (
        <Table head={['Service', 'Description', 'State', 'On boot']}>
          {shown.map((s) => (
            <tr key={s.name} className="border-t border-line-soft align-middle">
              <td className="py-2 font-mono">{s.name}</td>
              <td className="py-2 text-text-2">{s.desc ?? ''}</td>
              <td className={`py-2 ${s.state === 'running' ? 'text-green' : 'text-text-3'}`}>
                {s.state ?? 'unknown'}
              </td>
              <td className="py-2 text-text-2">{s.unit_state ?? 'unknown'}</td>
            </tr>
          ))}
        </Table>
      )}
      <div className="mt-3 flex items-center gap-3 text-[12px] text-text-3">
        {!all && stopped.length > 0 && (
          <span>{list.length - stopped.length} running services hidden.</span>
        )}
        <button type="button" onClick={() => setAll((v) => !v)}
          className="rounded-md border border-line-soft px-2 py-1 text-[12px] text-text-2 hover:bg-panel-2">
          {all ? 'Show only what is not running' : `Show all ${list.length}`}
        </button>
      </div>
    </Section>
  )
}

/** Subscription, resolvers and clock: three tiny reads that each deserve a
 *  row, not a card. Each is separately refusable, so a refused one names
 *  itself here rather than emptying the block. */
function NodeFacts({ subscription, dns, time, bad }: {
  subscription: Hardware['subscription']
  dns: Hardware['dns']
  time: Hardware['time']
  bad: Record<string, Refusal>
}) {
  const items: [string, ReactNode][] = []

  if (subscription) {
    // "notfound" is simply what an unsubscribed install reports. PVE nags
    // about it; Proxploy states it and moves on.
    const status = subscription.status
    items.push(['Subscription', status === 'notfound' || !status
      ? 'No subscription key'
      : status === 'active'
        ? `Active${subscription.level ? ` · ${subscription.level}` : ''}`
        : status])
  }
  if (dns) {
    items.push(['DNS servers', dns.servers.length
      ? dns.servers.join(' · ') : 'none configured'])
    items.push(['Search domain', dns.search ?? 'none'])
  }
  if (time) {
    items.push(['Timezone', time.timezone ?? 'unknown'])
    const clock = nodeClock(time.utc, time.timezone)
    if (clock) items.push(['Node clock', clock])
  }

  const refused = ['subscription', 'dns', 'time'].filter((k) => bad[k])

  return (
    <section className={card}>
      <h2 className="mb-3 font-display text-[15px] font-semibold">Node facts</h2>
      {items.length > 0 && <KVGrid items={items} />}
      {refused.map((k) => (
        <p key={k} className="mt-2 text-[12px] text-text-3">
          This node would not report its {k === 'dns' ? 'resolvers'
            : k === 'time' ? 'clock' : 'subscription status'}: {bad[k].detail}
        </p>
      ))}
    </section>
  )
}

/** The node's own wall clock, rendered in the node's timezone rather than the
 *  browser's, because reading a Kolkata box's time in London time is the
 *  confusion this row exists to remove. */
function nodeClock(utc: number | null, tz: string | null): string | null {
  if (utc == null) return null
  try {
    return new Intl.DateTimeFormat(undefined, {
      dateStyle: 'medium', timeStyle: 'short', ...(tz ? { timeZone: tz } : {}),
    }).format(new Date(utc * 1000))
  } catch {
    return null
  }
}
