import { useQuery } from '@tanstack/react-query'
import { api } from './client'

export type Me = { id: number; email: string; display_name: string | null; role: string }
export type Entitlements = {
  tier: string
  features: Record<string, boolean>
  grace: { expires_at: string; grace_until: string; in_grace: boolean } | null
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
    has: (key: string) => q.data?.features[key] ?? false,
  }
}

// ---- Phase 2 (Observe) row types — mirror the backend response shapes -------
export type Summary = {
  updated_at: string | null
  cpu: { pct: number; used_cores: number; total_cores: number }
  mem: { pct: number; used_bytes: number; total_bytes: number }
  storage: { pct: number; used_bytes: number; total_bytes: number }
  net: { in_bps: number; out_bps: number }
  counts: { hosts: number; hosts_online: number; nodes: number; apps: number
    apps_running: number; vms: number; vms_running: number }
}

export type NodeRow = {
  host_id: number; name: string; node: string; status: string
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
