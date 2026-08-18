import { useQuery } from '@tanstack/react-query'
import { api } from './client'

// Mirrors backend/proxploy/api/hosts.py::host_tasks' row dict, the node's own
// task list (PVE tasks Proxploy did not necessarily start itself).
export type HostTaskRow = {
  upid: string; type: string | null; id: string | null; node: string | null
  user: string | null; status: string | null; exitstatus: string | null
  starttime: number | null; endtime: number | null
}

export type HostTaskLog = { upid: string; lines: string[] }

// POST /hosts/{id}/test (backend/proxploy/api/hosts.py::test_host).
// `tls_fingerprint` is the pin stored for this host, null when it was never
// pinned. `tls_fingerprint_seen` is the certificate the node is presenting
// right now, and it is only fetched when the pin is what refused the
// connection, so it is null whenever there is nothing to compare: a host that
// connected, a node that is simply down, an unpinned host.
export type HostTestResult = {
  id: number; status: string; pve_version: string | null
  node_power_missing?: boolean | null
  quorate?: boolean | null
  // Per configured capability token, which of its role's privileges it lacks.
  // A capability is absent when it is fully granted or has no token at all;
  // null means PVE refused /access/permissions, which is "could not tell", not
  // a clean bill of health. Privileges do get added to a role (SDN.Use and
  // VM.Config.HWType both landed on 2026-08-18), so an old token drifts.
  capability_gaps?: Record<string, string[] | null>
  tls_fingerprint: string | null; tls_fingerprint_seen: string | null
}

export function useHostTasks(hostId: number | null, enabled = true) {
  return useQuery({
    queryKey: ['hosts', hostId, 'tasks'],
    queryFn: () => api<HostTaskRow[]>(`/hosts/${hostId}/tasks?limit=50`),
    enabled: enabled && hostId != null,
  })
}

// {monitoring, lifecycle, console, backup}, always present with a boolean
// each (backend/proxploy/api/hosts.py::_capability_state never omits a key,
// a host with no credential rows reports every capability False).
export type HostCapabilities = { monitoring: boolean; lifecycle: boolean; console: boolean; backup: boolean }

/**
 * Whether ONE host can run lifecycle actions, open a console, etc, read off
 * the same GET /hosts every other page already fetches on the ['hosts']
 * key (InstallDialog, apps.tsx, MigrateDialog), so this dedupes against
 * whichever of them mounted first instead of adding a second request.
 *
 * `loaded` mirrors useEntitlements()'s `data != null` gate: capabilities
 * read undefined before the first fetch resolves, and a caller that disabled
 * its controls on that alone would grey out every host for the whole first
 * load, not just the ones that actually lack the capability.
 */
export function useHostCapabilities(hostId: number | null) {
  const q = useQuery({
    queryKey: ['hosts'],
    queryFn: () => api<{ id: number; capabilities: HostCapabilities }[]>('/hosts'),
  })
  return {
    loaded: q.data != null,
    capabilities: q.data?.find((h) => h.id === hostId)?.capabilities,
  }
}

// One row per capability a host can be given a token for, monitoring first
// and always `required: true` (backend/proxploy/api/hosts.py). Static and
// server-declared, so HostForm reads labels and the `why` explanation from
// here instead of duplicating them, and a generous staleTime means it is
// fetched at most once per session.
export type HostCapabilityInfo = { key: string; label: string; why: string; required: boolean }

export function useHostCapabilityCatalog() {
  return useQuery({
    queryKey: ['hosts', 'capabilities'],
    queryFn: () => api<HostCapabilityInfo[]>('/hosts/capabilities'),
    staleTime: Infinity,
  })
}

// GET /hosts/{id}/peers (backend/proxploy/api/hosts.py::list_peers). Every
// peer is probed before the route answers, so `reachable`, `tls_fingerprint`
// and `error` are already settled by the time this resolves: there is no row
// whose state is still unknown, and nothing to stream.
export type HostPeer = {
  node: string; address: string; online: boolean; reachable: boolean
  tls_fingerprint: string | null; already_enrolled_as: string | null
  error: { kind: string; detail: string } | null
}

// `cluster` is null on a standalone node, and `peers` is empty with it.
export type HostPeers = {
  cluster: string | null
  team: { id: number; name: string } | null
  capabilities_to_copy: string[]
  multi_host_entitled: boolean
  peers: HostPeer[]
}

// One row per requested node from POST /hosts/{id}/peers
// (backend/proxploy/api/hosts.py::enrol_peers). `skipped` is not a failure:
// the machine was recognised, nothing was written and nothing was wrong.
export type PeerEnrolResult = {
  node: string; status: 'enrolled' | 'failed' | 'skipped'
  host_id: number | null; address: string | null
  capabilities_stored: string[]; capabilities_failed: string[]
  detail: string | null
}

export function useHostPeers(hostId: number | null) {
  return useQuery({
    queryKey: ['hosts', hostId, 'peers'],
    queryFn: () => api<HostPeers>(`/hosts/${hostId}/peers`),
    enabled: hostId != null,
  })
}

export function useHostTaskLog(hostId: number | null, upid: string | null) {
  // Encoded outside the template literal: a UPID is full of characters that
  // must not reach the path raw, and the cast this used to need inline is
  // what the route-coverage audit (backend/tests/test_openapi_surface.py)
  // choked on, silently reading the call as /hosts/{}/tasks/{} with no /log.
  const upidPath = upid == null ? '' : encodeURIComponent(upid)
  return useQuery({
    queryKey: ['hosts', hostId, 'tasks', upid, 'log'],
    queryFn: () => api<HostTaskLog>(`/hosts/${hostId}/tasks/${upidPath}/log`),
    enabled: hostId != null && upid != null,
  })
}
