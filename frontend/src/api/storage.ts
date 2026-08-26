import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { ApiError, api } from './client'

export type StorageRow = {
  host_id: number
  host_name: string
  /** The cluster of the host whose poll produced this row, null when it is
   *  standalone. GET /storage keeps one row per (cluster, node, storage) and
   *  drops host_id from that key, so host_id names whichever host polled
   *  first, NOT the only host that can serve the pool. Filter with
   *  components/install/pools.ts::servedTo, never on host_id alone. */
  cluster_name: string | null
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

/** One datastore, live from Proxmox; the only source of `avail_bytes` and the
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

export type UploadProgress = {
  /** Bytes sent so far. */
  loaded: number
  /** Total bytes the browser will send, or null when the progress event was
   *  not `lengthComputable`: no honest percentage can be derived then. */
  total: number | null
}

/**
 * The ONE place in this codebase that must NOT go through `api()`.
 *
 * api/client.ts sets `Content-Type: application/json` whenever `opts.body` is
 * non-null. A FormData body needs the BROWSER to set
 * `multipart/form-data; boundary=…` itself; overwriting it strips the boundary
 * and FastAPI's UploadFile parse 422s before a byte of the ISO is read.
 *
 * Everything else `api()` does is reproduced here verbatim, the /api/v1
 * prefix, credentials (`xhr.withCredentials`, XHR's form of `include`), the
 * X-CSRF-Token header read from the pp_csrf cookie, ApiError(status, body) on
 * non-ok; so this stays an exemption exactly one header wide. DO NOT "fix" it
 * back to api().
 *
 * XMLHttpRequest rather than fetch, on purpose: fetch has no upload-progress
 * event and no way to cancel a request already sent, and a multi-GB ISO can
 * sit on the browser→Proxploy leg for minutes. `xhr.upload.onprogress` is
 * what lets UploadDialog show real bytes/speed/ETA there, and `xhr.abort()`
 * is what lets its Cancel button actually stop the transfer instead of just
 * closing the dialog on top of it.
 */
function uploadForm<T>(path: string, form: FormData, onProgress: (p: UploadProgress) => void,
): { promise: Promise<T>; xhr: XMLHttpRequest } {
  const xhr = new XMLHttpRequest()
  const csrf = document.cookie.split('; ')
    .find((c) => c.startsWith('pp_csrf='))?.split('=')[1] ?? ''
  const promise = new Promise<T>((resolve, reject) => {
    xhr.open('POST', '/api/v1' + path)
    xhr.withCredentials = true
    xhr.setRequestHeader('X-CSRF-Token', csrf)
    xhr.upload.onprogress = (e) => {
      onProgress({ loaded: e.loaded, total: e.lengthComputable ? e.total : null })
    }
    xhr.onload = () => {
      let body: unknown = null
      if (xhr.status !== 204 && xhr.responseText) {
        try { body = JSON.parse(xhr.responseText) } catch { body = null }
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(body as T)
      else reject(new ApiError(xhr.status, body))
    }
    // A network failure never reaches onload; same fallback shape as
    // fetch's rejected promise, `body: null` reads as "Upload failed" below.
    xhr.onerror = () => reject(new ApiError(0, null))
    // Cancel's abort() lands here, not onerror: UploadDialog reads the name
    // to tell "the operator stopped this" apart from a real failure and
    // skip the error toast for it.
    xhr.onabort = () => reject(new DOMException('Upload cancelled', 'AbortError'))
    xhr.send(form)
  })
  return { promise, xhr }
}

export type UploadVars = {
  hostId: number; storage: string; node: string; content: string; file: File
  // Set only after the operator answered the "replace it?" prompt. Absent on
  // the first attempt so the server is the one that detects the collision.
  overwrite?: boolean
}

/** The 409 body the upload route returns when the name is already taken. */
export type VolumeExists = {
  error: 'volume_exists'; volid: string; filename: string
  size_bytes: number | null; detail: string
}

export function useUploadContent() {
  const qc = useQueryClient()
  const xhrRef = useRef<XMLHttpRequest | null>(null)
  const [progress, setProgress] = useState<UploadProgress | null>(null)
  const mutation = useMutation<JobResponse, ApiError, UploadVars>({
    mutationFn: (v) => {
      setProgress(null)
      const form = new FormData()
      form.append('file', v.file)
      form.append('content', v.content)
      form.append('node', v.node)
      if (v.overwrite) form.append('overwrite', 'true')
      const { promise, xhr } = uploadForm<JobResponse>(
        `/storage/${v.hostId}/${v.storage}/content`, form, setProgress,
      )
      xhrRef.current = xhr
      return promise
    },
    // Same rule as api/jobs.ts::useLifecycle, the resource key is NOT
    // invalidated here. The volume does not exist until the job succeeds, and
    // the SSE `resource` event applyResource now routes to ['storage'] is what
    // refreshes the browser at exactly the right moment (Task 12).
    onSettled: () => {
      xhrRef.current = null
      qc.invalidateQueries({ queryKey: ['jobs'] })
    },
  })
  return {
    ...mutation,
    /** Bytes sent so far, or null before the first upload progress event
     *  (or once a new attempt has reset it). */
    progress,
    /** Aborts the in-flight upload. A no-op once it has already settled. */
    abort: () => xhrRef.current?.abort(),
  }
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
      // The content listing is a live passthrough, not a poll-stomped resource
      // cache, so re-reading it after the job is enqueued is correct here; 
      // the opposite of useLifecycle's rule for ['vms'].
      qc.invalidateQueries({ queryKey: ['storage', v.hostId, v.storage, 'content'] })
    },
  })
}
