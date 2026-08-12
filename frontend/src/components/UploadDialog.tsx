import { useState } from 'react'
import { toast } from 'sonner'
import { ApiError } from '../api/client'
import { useUploadContent, type VolumeExists } from '../api/storage'
import { JobLog } from './JobLog'
import { Button } from './ui/button'
import { Dialog } from './ui/dialog'
import { Loading } from './ui/loading'

const LABEL: Record<string, string> = { iso: 'ISO image', vztmpl: 'CT template' }

export function UploadDialog({ hostId, storage, node, contentTypes, onClose }: {
  hostId: number; storage: string; node: string; contentTypes: string[]; onClose: () => void
}) {
  const upload = useUploadContent()
  // Proxmox's upload endpoint accepts iso and vztmpl only, backups and disk
  // images get there by being written, not posted. Offering the other two would
  // be a 400 dressed up as a feature.
  const uploadable = contentTypes.filter((c) => c === 'iso' || c === 'vztmpl')
  // TS 5.5+ infers `uploadable` as ("iso" | "vztmpl")[] from the filter guard
  // above; the <select>'s onChange hands back a plain string, so the state
  // itself needs the wider type rather than narrowing every read site.
  const [content, setContent] = useState<string>(uploadable[0] ?? 'iso')
  const [file, setFile] = useState<File | null>(null)
  const [jobId, setJobId] = useState<number | null>(null)
  // Set when the server says the name is already taken. Replacing is a click,
  // not a typed phrase: the typed confirmation is reserved for deletions,
  // which cannot be undone.
  const [collision, setCollision] = useState<VolumeExists | null>(null)

  const submit = (overwrite = false) => {
    if (!file) return
    setCollision(null)
    upload.mutate({ hostId, storage, node, content, file, overwrite }, {
      onSuccess: (r) => setJobId(r.job.id),
      onError: (e) => {
        const body = e instanceof ApiError ? (e.body as any) : null
        if (e instanceof ApiError && e.status === 409 && body?.error === 'volume_exists') {
          setCollision(body as VolumeExists)
          return
        }
        toast.error(body ? String(body.detail ?? 'Upload rejected') : 'Upload failed')
      },
    })
  }

  return (
    <Dialog title={<>Upload to {storage}</>} width={520} onClose={onClose}>
    <div className="font-mono text-[11px] text-text-3">{node}</div>

    {collision ? (
      <div className="mt-4">
        <div className="rounded-ctl border border-warn/40 bg-warn/10 p-3">
          <div className="text-[13px] font-semibold text-text">
            {`${collision.filename} already exists`}
          </div>
          <div className="mt-1 font-mono text-[11px] text-text-3">{collision.volid}</div>
          <div className="mt-2 text-[12px] text-text-2">{collision.detail}</div>
        </div>
        <div className="mt-4 flex items-center justify-end gap-2">
          <Button variant="ghost" onClick={() => setCollision(null)}>Cancel</Button>
          <Button variant="primary" disabled={upload.isPending}
            onClick={() => submit(true)}>
            Replace
          </Button>
        </div>
      </div>
    ) : jobId ? (
      // Exactly InstallDialog's pattern: the mutation returned {job:{id}},
      // so the dialog becomes the job's live transcript.
      <div className="mt-4">
        <JobLog jobId={jobId} />
        <Button className="mt-3" variant="ghost" onClick={onClose}>Close</Button>
      </div>
    ) : (
      <>
        <div className="mt-4 space-y-3">
          <div>
            <label htmlFor="upload-content"
              className="mb-1 block text-[11px] uppercase tracking-wide text-text-3">Content type</label>
            <select id="upload-content" value={content}
              onChange={(e) => setContent(e.target.value)}
              className="w-full rounded-ctl border border-line bg-panel px-3 py-1.5 text-[13px]">
              {uploadable.map((c) => <option key={c} value={c}>{LABEL[c] ?? c}</option>)}
            </select>
          </div>
          <div>
            <label htmlFor="upload-file"
              className="mb-1 block text-[11px] uppercase tracking-wide text-text-3">File</label>
            <input id="upload-file" type="file"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              className="w-full rounded-ctl border border-line bg-panel px-3 py-1.5 text-[13px] text-text-2" />
          </div>
          <div className="text-[12px] text-text-2">
            The file is streamed through Proxploy to the node, it crosses the
            wire twice and needs that much free space on the Proxploy host
            while the job runs.
          </div>
        </div>
        <div className="mt-4 flex items-center justify-end gap-2">
          {/* Streamed through `fetch`, no `onUploadProgress`, so there is no
              byte count to show here. XMLHttpRequest could report real bytes
              sent, but that is a separate change this task does not make. */}
          {upload.isPending && <Loading label="Uploading" size={18} className="mr-auto" />}
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button variant="primary" disabled={!file || upload.isPending}
            onClick={() => submit()}>
            Upload
          </Button>
        </div>
      </>
    )}
    </Dialog>
  )
}
