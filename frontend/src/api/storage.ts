// api/storage.ts — read hooks for the Storage page (doc 05 §Storage, doc 06 §d).
// Same shape as api/catalog.ts: plain useQuery wrappers, no client-side state.
import { useQuery } from '@tanstack/react-query'
import { api } from './client'

export type StorageRow = {
  host_id: number
  host_name: string
  node: string
  storage: string
  type: string | null
  content: string[]
  shared: boolean
  status: string
  used_bytes: number
  total_bytes: number
  used_pct: number
}

export type StorageDetail = StorageRow & { avail_bytes: number; nodes: string[] }

export type VolumeRow = {
  volid: string
  format: string | null
  size: number
  used: number
  vmid: number | null
  ctime: number | null
  content: string | null
  notes: string | null
  verification: { state?: string } | null
}

/** Whole-cluster datastore list. Served from the poll snapshot, so it is cheap
 *  and 60 s is the doc 06 §d interval for it. */
export function useStorage() {
  return useQuery({
    queryKey: ['storage'],
    refetchInterval: 60_000,
    queryFn: () => api<StorageRow[]>('/storage'),
  })
}

/** One datastore, live from Proxmox — the only source of `avail_bytes` and the
 *  full `nodes` list.
 *
 *  ponytail: keyed on (host, name) with no node, matching the interface
 *  contract. The backend resolves the node itself (first node the last poll saw
 *  serving that name), so two same-named LOCAL datastores on different nodes
 *  share this entry and both show the first node's free space. Every number on
 *  the CARD comes from the clicked row and stays exact; only this panel's
 *  free-space line is affected. Add `node` to the key and the query string if a
 *  real fleet ever hits it. */
export function useStorageDetail(hostId: number | null, name: string | null) {
  return useQuery({
    queryKey: ['storage', hostId, name],
    enabled: hostId != null && name != null,
    queryFn: () => api<StorageDetail>(`/storage/${hostId}/${name}`),
  })
}

export function useStorageContent(hostId: number | null, name: string | null,
                                  contentType?: string) {
  return useQuery({
    queryKey: ['storage', hostId, name, 'content', contentType],
    enabled: hostId != null && name != null,
    queryFn: () => {
      const p = new URLSearchParams()
      if (contentType) p.set('content', contentType)
      const qs = p.toString()
      return api<VolumeRow[]>(`/storage/${hostId}/${name}/content${qs ? `?${qs}` : ''}`)
    },
  })
}
