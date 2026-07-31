// api/network.ts — Network page server state (doc 05 §Network, doc 06 §a row 44).
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, ApiError } from './client'
import type { JobRow } from './jobs'

export type Iface = {
  iface: string
  type: string | null
  method: string | null
  address: string | null
  netmask: string | null
  cidr: string | null
  gateway: string | null
  bridge_ports: string | null
  slaves: string | null
  vlan_aware: boolean
  vlan_id: number | null
  vlan_raw_device: string | null
  active: boolean
  autostart: boolean
  comments: string | null
}

export type NodeIfaces = {
  host_id: number; host_name: string; node: string; interfaces: Iface[]
}

/** One netN on one guest, as GET /network/bridges reports it. */
export type Attachment = {
  host_id: number; node: string
  guest_type: 'app' | 'vm'; guest_id: number; name: string | null; vmid: number
  iface: string; raw: string
  model: string | null; macaddr: string | null
  bridge: string | null; tag: number | null; firewall: boolean
  rate: string | null; mtu: string | null; link_down: boolean
}

export type Bridges = { nodes: NodeIfaces[]; attachments: Attachment[] }

export type NetSeries = { resolution: string; ts: number[]; value: (number | null)[] }
export type HostThroughput = {
  host_id: number; host_name: string; in: NetSeries; out: NetSeries
}
export type Throughput = { hours: number; resolution: string; hosts: HostThroughput[] }

/**
 * Read a 4xx body.
 *
 * Every dict-bodied `HTTPException` in this app arrives FLAT: `main.py`'s
 * `problem_handler` does `body.update(exc.detail)`, so `HTTPException(409,
 * {"error": "confirm_required", ...})` serialises as
 * `{type, title, status, error, confirm_phrase, detail}` — `detail` is the
 * human-readable string, not a nested object. That is why `LifecycleActions`
 * reads `e.body.error` directly and why it works for Phase 6's routes too.
 * The `detail`-is-an-object branch below is belt-and-braces for a plain
 * string-detail `HTTPException`; it never fires on the routes we ship.
 */
export function errBody(e: unknown): Record<string, unknown> | null {
  if (!(e instanceof ApiError)) return null
  const body = e.body as Record<string, unknown> | null
  if (!body) return null
  const inner = body.detail
  return inner && typeof inner === 'object' ? (inner as Record<string, unknown>) : body
}

export function useBridges(hostId?: number) {
  return useQuery({
    queryKey: ['network', 'bridges', hostId ?? null],
    refetchInterval: 30_000,
    queryFn: () =>
      api<Bridges>(hostId ? `/network/bridges?host=${hostId}` : '/network/bridges'),
  })
}

export function useThroughput(hours = 1) {
  return useQuery({
    queryKey: ['network', 'throughput', hours],
    refetchInterval: false, // SSE-invalidated, like every other metrics read (doc 06 §d)
    queryFn: () => api<Throughput>(`/network/throughput?hours=${hours}`),
  })
}

/**
 * Only the keys the form actually changed. The backend applies
 * `model_dump(exclude_unset=True)`, so an ABSENT key is left alone and an
 * explicit `null` deletes it. `model` and `macaddr` are deliberately not
 * expressible here: they live inside the netN head token
 * (`virtio=AA:BB:CC:DD:EE:FF`) which `services/netconfig.py` round-trips
 * byte-for-byte, and a regenerated MAC breaks every DHCP reservation and
 * MAC-bound licence pointed at that guest.
 */
export type NicPatch = { bridge?: string; tag?: number | null; firewall?: boolean }

export type NicResult = {
  iface: string; value: string; upid: string | null
  pending_reboot: boolean; detail: string
}

export function useSetNic() {
  const qc = useQueryClient()
  return useMutation<NicResult, ApiError,
    { guestType: 'app' | 'vm'; guestId: number; iface: string; patch: NicPatch }>({
    mutationFn: (v) =>
      api<NicResult>(`/${v.guestType === 'app' ? 'apps' : 'vms'}/${v.guestId}/network/${v.iface}`,
        { method: 'PUT', body: JSON.stringify(v.patch) }),
    // A config PUT is not a job (api/network.py::set_guest_nic writes the file
    // synchronously), so useLifecycle's "never invalidate the resource key"
    // rule does not apply — there is no optimistic patch to stomp and the
    // attachment map is exactly what changed.
    onSettled: () => { qc.invalidateQueries({ queryKey: ['network'] }) },
  })
}

/** PVE option names, unpacked straight into the proxmoxer call server-side. */
export type BridgeConfig = Record<string, string | number>

export function useStageBridge() {
  const qc = useQueryClient()
  return useMutation<{ staged: boolean; node: string; iface: string }, ApiError,
    { hostId: number; node: string; iface: string; config: BridgeConfig }>({
    mutationFn: (v) =>
      api('/network/bridges', {
        method: 'POST',
        body: JSON.stringify({ host_id: v.hostId, node: v.node, iface: v.iface,
                               type: 'bridge', config: v.config }),
      }),
    onSettled: () => { qc.invalidateQueries({ queryKey: ['network'] }) },
  })
}

export function useUpdateBridge() {
  const qc = useQueryClient()
  return useMutation<{ staged: boolean; node: string; iface: string }, ApiError,
    { hostId: number; node: string; iface: string; config: BridgeConfig }>({
    mutationFn: (v) =>
      api(`/network/bridges/${v.hostId}/${v.node}/${v.iface}`, {
        method: 'PUT', body: JSON.stringify({ config: v.config }),
      }),
    onSettled: () => { qc.invalidateQueries({ queryKey: ['network'] }) },
  })
}

export function useDeleteBridge() {
  const qc = useQueryClient()
  return useMutation<{ staged: boolean }, ApiError,
    { hostId: number; node: string; iface: string }>({
    mutationFn: (v) =>
      api(`/network/bridges/${v.hostId}/${v.node}/${v.iface}`, { method: 'DELETE' }),
    onSettled: () => { qc.invalidateQueries({ queryKey: ['network'] }) },
  })
}

export function useApplyNetwork() {
  const qc = useQueryClient()
  return useMutation<{ job: JobRow }, ApiError,
    { hostId: number; node: string; confirm?: string }>({
    mutationFn: (v) =>
      api<{ job: JobRow }>(`/network/${v.hostId}/${v.node}/apply`, {
        method: 'POST',
        body: JSON.stringify(v.confirm ? { confirm: v.confirm } : {}),
      }),
    // Job-firing mutation: jobs + activity only, never ['network'] on success
    // (api/jobs.ts::useLifecycle's documented rule). The apply's own terminal
    // `resource` delta is what refreshes the interface list.
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ['jobs'] })
      qc.invalidateQueries({ queryKey: ['cluster', 'activity'] })
    },
  })
}

export function useRevertNetwork() {
  const qc = useQueryClient()
  return useMutation<{ reverted: boolean; node: string }, ApiError,
    { hostId: number; node: string }>({
    mutationFn: (v) =>
      api(`/network/${v.hostId}/${v.node}/revert`, { method: 'POST' }),
    onSettled: () => { qc.invalidateQueries({ queryKey: ['network'] }) },
  })
}
