import { useQuery } from '@tanstack/react-query'
import { api } from './client'

export type Me = { id: number; email: string; display_name: string | null; role: string }
export type Entitlements = {
  tier: string
  features: Record<string, boolean>
  grace: { expires_at: string; grace_until: string; in_grace: boolean } | null
  clock_skew: boolean
}

export function useMe() {
  return useQuery({ queryKey: ['me'], queryFn: () => api<Me>('/auth/me') })
}

export function useEntitlements() {
  const q = useQuery({
    queryKey: ['entitlements'],
    queryFn: () => api<Entitlements>('/entitlements'),
    refetchInterval: 5 * 60_000,
  })
  return {
    ...q,
    tier: q.data?.tier ?? 'builtin',
    grace: q.data?.grace ?? null,
    clockSkew: q.data?.clock_skew ?? false,
    // `has` stays fail-closed: a feature must never unlock because a fetch
    // failed, that would be a security bug. `unknown` is what lets a
    // consumer tell "not entitled" apart from "could not check" and render
    // "could not check" instead of the UI of a tenant who simply lacks the
    // feature.
    has: (key: string) => q.data?.features[key] ?? false,
    unknown: q.isError,
  }
}

export type Summary = {
  updated_at: string | null
  // pct is null when nothing was measured -- not the same claim as 0%.
  cpu: { pct: number | null; used_cores: number; total_cores: number }
  mem: { pct: number | null; used_bytes: number; total_bytes: number }
  storage: { pct: number | null; used_bytes: number; total_bytes: number }
  net: { in_bps: number; out_bps: number }
  counts: { hosts: number; hosts_online: number; nodes: number; apps: number
    apps_running: number; vms: number; vms_running: number }
}

// One row per NODE (not per host): a Host is one Proxmox API endpoint and the
// cluster behind it can have many nodes. `name` is still the HOST's name, and
// `node` the node's own; `is_entry` marks the one node we connect through, of
// which every host has exactly one. `node` is null only for a host the poller
// has not reached yet.
export type NodeRow = {
  host_id: number; name: string; node: string | null; status: string
  is_entry: boolean
  cluster: string | null; pve_version: string | null
  cpu_pct: number | null; mem_pct: number | null
  mem_bytes: number | null; mem_total_bytes: number | null
  // This node's storage, shared datastores included (storage it can really
  // use). Never sum these across a cluster: that double-counts shared pools.
  disk_pct: number | null; disk_bytes: number | null
  disk_total_bytes: number | null
  uptime_s: number | null; apps: number; apps_running: number
  vms: number; vms_running: number; last_seen_at: string | null
  // Host-level: quorum belongs to the cluster behind the endpoint. False only
  // when PVE reported it lost; null is standalone or not yet polled.
  quorate?: boolean | null
}

export type AppRow = {
  id: number; name: string; slug: string; host_id: number; host_name: string
  node: string; ctid: number; category: string | null; catalog_slug: string | null
  icon_initials: string | null; icon_colors: { c1: string; c2: string } | null
  // The icon of the catalog entry this app was installed from, resolved by the
  // backend through the Store's own pipeline (services/catalog_icons.py). Null
  // whenever there is nothing to show -- no catalog slug, a slug the catalog no
  // longer has, or an entry with no logo -- which is the initials tile.
  icon_url: string | null
  web_port: number | null; web_protocol: string | null; web_path: string | null
  // What the install script printed about itself. Read-only: the three
  // fields above override it, it never overrides them.
  installed_url: string | null
  // "Open web UI" target port, resolved from this app's catalog entry every
  // request (services/catalog.py). Null when there is no catalog entry or the
  // entry names no port, which is what hides the action rather than offering
  // one with nothing to point at.
  catalog_port: number | null
  status: string; ip: string | null; cpu_pct: number | null
  mem_bytes: number | null; mem_total_bytes: number | null
  // Used and allocated bytes, from /cluster/resources' `disk`/`maxdisk`.
  disk_bytes: number | null; disk_total_bytes: number | null
  // Bytes per second, diffed by the poller from PVE's netin/netout counters.
  // Null on the first cycle for an app and on the cycle after a container
  // restart zeroes the counters, both of which are "no reading", never zero
  // traffic.
  net_in_bps: number | null; net_out_bps: number | null
  uptime_s: number | null; update_available: string | null; adopted: boolean
}

export type DiscoveredRow = {
  host_id: number; host_name: string; ctid: number; name: string | null
  node: string | null; status: string; suggestion: string | null
}

export type VmRow = {
  id: number; host_id: number; host_name: string; vmid: number; name: string
  status: string; os_type: string | null; cpu_cores: number | null
  cpu_pct: number | null
  // Used bytes, the SAME meaning these names carry on AppRow. Allocated size
  // lives in the _total_ fields below: how big a VM is reads those, how much
  // it is using reads these.
  mem_bytes: number | null; mem_total_bytes: number | null
  // disk_bytes is null, not zero, on a VM with no QEMU guest agent: PVE cannot
  // see inside the disk image without one, so there is no reading to report.
  // The allocated size is known either way.
  disk_bytes: number | null; disk_total_bytes: number | null
  // Bytes per second, diffed by the poller from PVE's netin/netout counters.
  // Null on the first cycle for a VM and on the cycle after a reboot zeroes
  // the counters, both of which are "no reading", never zero traffic.
  net_in_bps: number | null; net_out_bps: number | null
  uptime_s: number | null
  // Whether the QEMU guest agent is installed and answering inside this VM.
  // THREE states, and they must not be collapsed to a boolean:
  //   true   the agent answered.
  //   false  Proxmox says this VM has no working guest agent. This is the
  //          reason disk_bytes above is null, and it is something an operator
  //          can fix by installing the agent in the guest.
  //   null   nobody knows: the poller has not probed it yet, the VM is
  //          stopped so nothing inside it can answer, or its host was
  //          unreachable. Rendered as "unknown", never as "not installed".
  guest_agent_ok: boolean | null
  // PVE accepts a linked clone only FROM a template, so the clone dialog gates
  // that option on this rather than letting PVE refuse every time.
  template?: boolean
  // The node the guest runs on, which is not its host's node on a cluster.
  node?: string | null
}

export type UpdateInfo = {
  update_available: string | null
  from_ref: string | null
  to_ref: string | null
  diff_vs_upstream: string | null
}

export type Series = {
  target: string; metric: string; resolution: string
  ts: number[]; value: number[]; min?: number[]; max?: number[]
}

export function useMetrics(target: string | null, metric: string, hours = 24) {
  return useQuery({
    queryKey: ['metrics', target, metric, hours],
    enabled: !!target,
    refetchInterval: false, // SSE-invalidated (doc 06 §d)
    queryFn: () => {
      const to = new Date()
      const from = new Date(to.getTime() - hours * 3600_000)
      return api<Series>(
        `/metrics/query?target=${target}&metric=${metric}` +
        `&from=${from.toISOString()}&to=${to.toISOString()}`,
      )
    },
  })
}
