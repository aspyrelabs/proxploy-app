import { useEffect, useRef, useState } from 'react'
import { ApiError } from '../api/client'
import { TERMINAL, useCancelJob, useJob } from '../api/jobs'
import { useUploadContent, type VolumeExists } from '../api/storage'
import { fmtBytes, fmtEta, UNKNOWN } from '../lib/format'
import { notify } from '../lib/notify'
import { JobLog } from './JobLog'
import { Button } from './ui/button'
import { ButtonGroup, ButtonGroupSeparator } from './ui/button-group'
import { Dialog } from './ui/dialog'
import { Progress, ProgressLabel, ProgressValue } from './ui/progress'

/** How far back the speed reading looks, in ms. Long enough that two
 *  progress events a few ms apart (which jitters badly) do not drive it,
 *  short enough that it still tracks a real change in throughput. */
const SPEED_WINDOW_MS = 3000

const LABEL: Record<string, string> = { iso: 'ISO image', vztmpl: 'CT template' }

// PVE lists a datastore's content in its own order, and `["import","vztmpl",
// "iso"]` is common, so taking the first entry opened the form on CT template
// and filed a Windows ISO as one.
const CONTENT_BY_EXT: [RegExp, 'iso' | 'vztmpl'][] = [
  [/\.iso$/i, 'iso'],
  [/\.(tar\.(gz|xz|zst|bz2)|tgz|tzst|txz)$/i, 'vztmpl'],
]

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
  const [content, setContent] = useState<string>(
    uploadable.includes('iso') ? 'iso' : uploadable[0] ?? 'iso')
  const [file, setFile] = useState<File | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  const pickFile = (f: File | null) => {
    setFile(f)
    if (!f) return
    const guess = CONTENT_BY_EXT.find(([re]) => re.test(f.name))?.[1]
    if (guess && uploadable.includes(guess)) setContent(guess)
  }
  const [jobId, setJobId] = useState<number | null>(null)
  const job = useJob(jobId)
  const cancelJob = useCancelJob()
  // Set when the server says the name is already taken. Replacing is a click,
  // not a typed phrase: the typed confirmation is reserved for deletions,
  // which cannot be undone.
  const [collision, setCollision] = useState<VolumeExists | null>(null)
  const [leg1Cancelled, setLeg1Cancelled] = useState(false)
  const [jobCancelledByUser, setJobCancelledByUser] = useState(false)

  const submit = (overwrite = false) => {
    if (!file) return
    setCollision(null)
    setLeg1Cancelled(false)
    upload.mutate({ hostId, storage, node, content, file, overwrite }, {
      onSuccess: (r) => setJobId(r.job.id),
      onError: (e) => {
        // The operator's own Cancel button, not a real failure: nothing to
        // tell them they don't already know.
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
    // Cancel means it now: XHR supports abort (fetch's streaming body did not).
    if (upload.isPending) {
      upload.abort()
      setLeg1Cancelled(true)
      return
    }
    onClose()
  }

  const handleCancelJob = () => {
    if (jobId == null) return
    cancelJob.mutate(jobId, {
      onSuccess: () => setJobCancelledByUser(true),
      onError: () => notify.error('Could not cancel the upload.'),
    })
  }

  // Speed, smoothed over SPEED_WINDOW_MS; resets when upload.progress goes
  // null at the start of each attempt.
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

  // The event only carries a percentage when lengthComputable said so; "X of
  // Y" uses the file's own size, known the moment it is picked.
  const leg1Pct = upload.progress?.total != null
    ? Math.round((upload.progress.loaded / upload.progress.total) * 100)
    : null
  const remaining = upload.progress?.total != null
    ? upload.progress.total - upload.progress.loaded : null
  const eta = speed != null && speed > 0 && remaining != null ? remaining / speed : null
  const leg1DisplayPct = leg1Pct != null ? leg1Pct / 2 : null

  const jobStatus = job.data?.status ?? null
  const jobPct = job.data?.progress_pct ?? null
  const jobDone = jobStatus === 'succeeded'
  const jobDied = jobStatus != null && TERMINAL.includes(jobStatus) && !jobDone
  const jobCancelRequested = cancelJob.isPending || jobCancelledByUser
  const leg2DisplayPct = 50 + (jobPct ?? 0) / 2
  const leg2Label = jobPct != null && jobPct >= 100 ? 'Finishing up' : `Sending to ${node}`

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
        {jobCancelRequested ? (
          <div className="rounded-ctl border border-line bg-panel p-3 text-[12.5px] text-text">
            Upload cancelled. Check Activity for how much reached {node}.
          </div>
        ) : jobDied ? (
          <div className="rounded-ctl border border-red/30 bg-red-dim p-3 text-[12.5px] text-text">
            The upload stopped before it finished. The server may have restarted. Check Activity for the job.
          </div>
        ) : !jobDone && (
          <Progress value={leg2DisplayPct}>
            <ProgressLabel>{leg2Label}</ProgressLabel>
            <ProgressValue />
          </Progress>
        )}
        <div className="mt-3">
          <JobLog jobId={jobId} />
        </div>
        {jobCancelRequested || jobDone || jobDied ? (
          <Button className="mt-3" variant="ghost" onClick={onClose}>Close</Button>
        ) : (
          <div className="mt-3 flex items-center justify-end gap-2">
            <Button variant="ghost" disabled={cancelJob.isPending} onClick={handleCancelJob}>
              Cancel
            </Button>
            <Button variant="primary" onClick={onClose}>Upload in background</Button>
          </div>
        )}
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
            <input id="upload-file" ref={fileRef} type="file" className="hidden"
              onChange={(e) => pickFile(e.target.files?.[0] ?? null)} />
            <ButtonGroup>
              <Button type="button" size="sm" variant="ghost"
                disabled={upload.isPending}
                onClick={() => fileRef.current?.click()}>
                {file ? 'Choose a different file' : 'Choose file'}
              </Button>
              {file && (
                <>
                  <ButtonGroupSeparator />
                  <Button type="button" size="sm" variant="ghost"
                    disabled={upload.isPending}
                    onClick={() => {
                      setFile(null)
                      if (fileRef.current) fileRef.current.value = ''
                    }}>
                    Clear
                  </Button>
                </>
              )}
            </ButtonGroup>
            <p className="mt-1.5 text-[12px] text-text-2">
              {file ? `${file.name} (${fmtBytes(file.size)})` : 'No file chosen yet.'}
            </p>
          </div>
          <div className="text-[12px] text-text-2">
            The file is streamed through Proxploy to the node, it crosses the
            wire twice and needs that much free space on the Proxploy host
            while the job runs.
          </div>
        </div>
        {upload.isPending && (
          <div className="mt-4">
            <Progress value={leg1DisplayPct}>
              {/* The bytes finish sending before the request resolves, the
                  server still has to write the file. Saying "Uploading" at
                  100% would claim the job is done when it is not. */}
              <ProgressLabel>{leg1Pct === 100 ? 'Finishing up' : 'Sending to Proxploy'}</ProgressLabel>
              <ProgressValue />
            </Progress>
            <div className="mt-1 flex items-center justify-between font-mono text-[11px] text-text-3">
              <span>{fmtBytes(upload.progress?.loaded ?? 0)} of {fmtBytes(file?.size)}</span>
              {leg1Pct === 100 ? (
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
        {leg1Cancelled && (
          <div className="mt-4 text-[12px] text-text-2">Upload cancelled. The file was not saved.</div>
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
