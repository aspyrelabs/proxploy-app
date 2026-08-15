import { useEffect, useRef, useState } from 'react'
import { ApiError } from '../api/client'
import { useUploadContent, type VolumeExists } from '../api/storage'
import { fmtBytes, fmtEta, UNKNOWN } from '../lib/format'
import { notify } from '../lib/notify'
import { JobLog } from './JobLog'
import { Button } from './ui/button'
import { Dialog } from './ui/dialog'
import { Progress, ProgressLabel, ProgressValue } from './ui/progress'

/** How far back the speed reading looks, in ms. Long enough that two
 *  progress events a few ms apart (which jitters badly) do not drive it,
 *  short enough that it still tracks a real change in throughput. */
const SPEED_WINDOW_MS = 3000

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
        // The operator's own Cancel button, not a real failure, see
        // api/storage.ts's uploadForm. Nothing to tell them that they do
        // not already know.
        if (e instanceof DOMException && e.name === 'AbortError') return
        const body = e instanceof ApiError ? (e.body as any) : null
        if (e instanceof ApiError && e.status === 409 && body?.error === 'volume_exists') {
          setCollision(body as VolumeExists)
          return
        }
        notify.error(body ? String(body.detail ?? 'Upload rejected') : 'Upload failed')
      },
    })
  }

  const handleCancel = () => {
    // Closing the dialog used to leave the upload running in the background,
    // fetch's streaming body had no abort. XHR does, so Cancel now means it.
    if (upload.isPending) upload.abort()
    onClose()
  }

  // Speed, smoothed over SPEED_WINDOW_MS rather than read from the raw delta
  // between two progress events, which arrive close together and jitter
  // badly. Resets whenever upload.progress goes back to null, at the start
  // of every attempt (api/storage.ts's mutationFn does that).
  const [speed, setSpeed] = useState<number | null>(null)
  const samples = useRef<{ t: number; loaded: number }[]>([])
  useEffect(() => {
    if (!upload.progress) { samples.current = []; setSpeed(null); return }
    const now = Date.now()
    const list = samples.current
    list.push({ t: now, loaded: upload.progress.loaded })
    const cutoff = now - SPEED_WINDOW_MS
    while (list.length > 1 && list[0].t < cutoff) list.shift()
    const span = list[list.length - 1].t - list[0].t
    // Fewer than two samples, or a span too short to trust, and there is no
    // honest rate yet, an instantaneous divide would jitter or divide by
    // (near) zero.
    if (list.length < 2 || span < 200) { setSpeed(null); return }
    setSpeed((list[list.length - 1].loaded - list[0].loaded) / (span / 1000))
  }, [upload.progress])

  // The event only carries a percentage when lengthComputable said so; the
  // file's own size (known the moment it is picked, independent of the
  // network) is what "X of Y" always shows.
  const pct = upload.progress?.total != null
    ? Math.round((upload.progress.loaded / upload.progress.total) * 100)
    : null
  const remaining = upload.progress?.total != null
    ? upload.progress.total - upload.progress.loaded : null
  const eta = speed != null && speed > 0 && remaining != null ? remaining / speed : null

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
        {upload.isPending && (
          <div className="mt-4">
            <Progress value={pct}>
              {/* The bytes finish sending before the request resolves, the
                  server still has to write the file. Saying "Uploading" at
                  100% would claim the job is done when it is not. */}
              <ProgressLabel>{pct === 100 ? 'Finishing up' : 'Uploading'}</ProgressLabel>
              <ProgressValue />
            </Progress>
            <div className="mt-1 flex items-center justify-between font-mono text-[11px] text-text-3">
              <span>{fmtBytes(upload.progress?.loaded ?? 0)} of {fmtBytes(file?.size)}</span>
              {pct === 100 ? (
                <span>Sent. Waiting for the server to finish.</span>
              ) : (
                <span>
                  {speed == null ? UNKNOWN : `${fmtBytes(speed)}/s`}
                  {' · '}
                  {eta == null ? UNKNOWN : `${fmtEta(eta)} left`}
                </span>
              )}
            </div>
          </div>
        )}
        <div className="mt-4 flex items-center justify-end gap-2">
          <Button variant="ghost" onClick={handleCancel}>Cancel</Button>
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
