// api/storage.ts — read hooks for the Storage page (doc 05 §Storage, doc 06 §d).
// Same shape as api/catalog.ts: plain useQuery wrappers, no client-side state.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError, api } from './client'

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

export type JobResponse = { job: { id: number; kind: string } }

/**
 * The ONE place in this codebase that must NOT go through `api()`.
 *
 * api/client.ts sets `Content-Type: application/json` whenever `opts.body` is
 * non-null. A FormData body needs the BROWSER to set
 * `multipart/form-data; boundary=…` itself; overwriting it strips the boundary
 * and FastAPI's UploadFile parse 422s before a byte of the ISO is read.
 *
 * Everything else `api()` does is reproduced here verbatim — the /api/v1
 * prefix, credentials: 'include', the X-CSRF-Token header read from the
 * pp_csrf cookie, ApiError(status, body) on non-ok — so this stays an
 * exemption exactly one header wide. DO NOT "fix" it back to api().
 *
 * ponytail: fetch fires no upload-progress events, so the dialog shows an
 * indeterminate "Uploading…" for the browser→Proxploy leg; the
 * Proxploy→PVE leg is a real JobLog with real percentages the moment this
 * resolves. Swap to XMLHttpRequest + upload.onprogress if a multi-GB ISO ever
 * makes that first leg feel dead.
 */
async function postForm<T>(path: string, form: FormData): Promise<T> {
  const csrf = document.cookie.split('; ')
    .find((c) => c.startsWith('pp_csrf='))?.split('=')[1] ?? ''
  const r = await fetch('/api/v1' + path, {
    method: 'POST',
    credentials: 'include',
    headers: { 'X-CSRF-Token': csrf },
    body: form,
  })
  const body = r.status === 204 ? null : await r.json().catch(() => null)
  if (!r.ok) throw new ApiError(r.status, body)
  return body as T
}

export type UploadVars = {
  hostId: number; storage: string; node: string; content: string; file: File
}

export function useUploadContent() {
  const qc = useQueryClient()
  return useMutation<JobResponse, ApiError, UploadVars>({
    mutationFn: (v) => {
      const form = new FormData()
      form.append('file', v.file)
      form.append('content', v.content)
      form.append('node', v.node)
      return postForm<JobResponse>(`/storage/${v.hostId}/${v.storage}/content`, form)
    },
    // Same rule as api/jobs.ts::useLifecycle — the resource key is NOT
    // invalidated here. The volume does not exist until the job succeeds, and
    // the SSE `resource` event applyResource now routes to ['storage'] is what
    // refreshes the browser at exactly the right moment (Task 12).
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ['jobs'] })
      qc.invalidateQueries({ queryKey: ['cluster', 'activity'] })
    },
  })
}

export type AttachVars = {
  host_id: number; storage: string; type: string; config: Record<string, string>
}

export function useAttachStorage() {
  const qc = useQueryClient()
  return useMutation<{ host_id: number; storage: string; type: string }, ApiError, AttachVars>({
    mutationFn: (v) => api('/storage', { method: 'POST', body: JSON.stringify(v) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['storage'] }),
  })
}

export type EditVars = { host_id: number; storage: string; config: Record<string, string> }

export function useEditStorage() {
  const qc = useQueryClient()
  return useMutation<{ host_id: number; storage: string; updated: string[] }, ApiError, EditVars>({
    mutationFn: (v) => api(`/storage/${v.host_id}/${v.storage}`, {
      method: 'PATCH', body: JSON.stringify({ config: v.config }),
    }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['storage'] }),
  })
}

export function useDetachStorage() {
  const qc = useQueryClient()
  return useMutation<{ host_id: number; storage: string; detached: boolean }, ApiError,
                     { host_id: number; storage: string }>({
    mutationFn: (v) => api(`/storage/${v.host_id}/${v.storage}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['storage'] }),
  })
}

export function useDeleteVolume() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (v: { hostId: number; storage: string; node: string; volid: string }) =>
      api<{ job: { id: number; kind: string } }>(
        `/storage/${v.hostId}/${v.storage}/content/${encodeURIComponent(v.volid)}?node=${encodeURIComponent(v.node)}`,
        { method: 'DELETE' },
      ),
    onSettled: (_d, _e, v) => {
      qc.invalidateQueries({ queryKey: ['jobs'] })
      qc.invalidateQueries({ queryKey: ['cluster', 'activity'] })
      // The content listing is a live passthrough, not a poll-stomped resource
      // cache, so re-reading it after the job is enqueued is correct here —
      // the opposite of useLifecycle's rule for ['vms'].
      qc.invalidateQueries({ queryKey: ['storage', v.hostId, v.storage, 'content'] })
    },
  })
}
