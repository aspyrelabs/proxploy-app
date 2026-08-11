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
    // feature, see components/HealthFooter.tsx for the same distinction.
    has: (key: string) => q.data?.features[key] ?? false,
    unknown: q.isError,
  }
}

// ---- Phase 2 (Observe) row types, mirror the backend response shapes -------
export type Summary = {
  updated_at: string | null
  cpu: { pct: number; used_cores: number; total_cores: number }
  mem: { pct: number; used_bytes: number; total_bytes: number }
  storage: { pct: number; used_bytes: number; total_bytes: number }
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
  uptime_s: number | null; apps: number; apps_running: number
  vms: number; vms_running: number; last_seen_at: string | null
}

export type AppRow = {
  id: number; name: string; slug: string; host_id: number; host_name: string
  node: string; ctid: number; category: string | null; catalog_slug: string | null
  icon_initials: string | null; icon_colors: { c1: string; c2: string } | null
  web_port: number | null; web_protocol: string | null; web_path: string | null
  status: string; ip: string | null; cpu_pct: number | null
  mem_bytes: number | null; mem_total_bytes: number | null
  uptime_s: number | null; update_available: string | null; adopted: boolean
}

export type DiscoveredRow = {
  host_id: number; host_name: string; ctid: number; name: string | null
  node: string | null; status: string; suggestion: string | null
}

export type VmRow = {
  id: number; host_id: number; host_name: string; vmid: number; name: string
  status: string; os_type: string | null; cpu_cores: number | null
  cpu_pct: number | null; mem_bytes: number | null; disk_bytes: number | null
  uptime_s: number | null; synced_at: string | null
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
