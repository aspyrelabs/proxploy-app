import { useState } from 'react'
import { toast } from 'sonner'
import { ApiError } from '../api/client'
import { useUploadContent } from '../api/storage'
import { JobLog } from './JobLog'
import { Button } from './ui/button'

const LABEL: Record<string, string> = { iso: 'ISO image', vztmpl: 'CT template' }

export function UploadDialog({ hostId, storage, node, contentTypes, onClose }: {
  hostId: number; storage: string; node: string; contentTypes: string[]; onClose: () => void
}) {
  const upload = useUploadContent()
  // Proxmox's upload endpoint accepts iso and vztmpl only — backups and disk
  // images get there by being written, not posted. Offering the other two would
  // be a 400 dressed up as a feature.
  const uploadable = contentTypes.filter((c) => c === 'iso' || c === 'vztmpl')
  // TS 5.5+ infers `uploadable` as ("iso" | "vztmpl")[] from the filter guard
  // above; the <select>'s onChange hands back a plain string, so the state
  // itself needs the wider type rather than narrowing every read site.
  const [content, setContent] = useState<string>(uploadable[0] ?? 'iso')
  const [file, setFile] = useState<File | null>(null)
  const [jobId, setJobId] = useState<number | null>(null)

  const submit = () => {
    if (!file) return
    upload.mutate({ hostId, storage, node, content, file }, {
      onSuccess: (r) => setJobId(r.job.id),
      onError: (e) => toast.error(
        e instanceof ApiError ? String((e.body as any)?.detail ?? 'Upload rejected') : 'Upload failed'),
    })
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="w-[520px] rounded-card border border-line bg-panel p-5">
        <h2 className="text-[16px] font-semibold text-text">Upload to {storage}</h2>
        <div className="font-mono text-[11px] text-text-3">{node}</div>

        {jobId ? (
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
                The file is streamed through Proxploy to the node — it crosses the
                wire twice and needs that much free space on the Proxploy host
                while the job runs.
              </div>
            </div>
            <div className="mt-4 flex items-center justify-end gap-2">
              {upload.isPending && (
                <span className="mr-auto font-mono text-[11px] text-text-3">Uploading…</span>
              )}
              <Button variant="ghost" onClick={onClose}>Cancel</Button>
              <Button variant="primary" disabled={!file || upload.isPending} onClick={submit}>
                Upload
              </Button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
