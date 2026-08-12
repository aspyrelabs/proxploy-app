import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../api/client'
import { useCatalogEntry, useInstall } from '../api/catalog'
import { JobLog } from './JobLog'
import { Button } from './ui/button'
import { Dialog } from './ui/dialog'
import { Loading } from './ui/loading'

type HostRow = { id: number; name: string }

export function InstallDialog({ slug, onClose }: { slug: string; onClose: () => void }) {
  const { data: entry } = useCatalogEntry(slug)
  const hosts = useQuery({ queryKey: ['hosts'], queryFn: () => api<HostRow[]>('/hosts') })
  const install = useInstall()
  const [hostId, setHostId] = useState<number | null>(null)
  const [name, setName] = useState('')
  const [ctid, setCtid] = useState('')
  const [consent, setConsent] = useState(false)
  const [jobId, setJobId] = useState<number | null>(null)
  // services/appstore.py::run_install only calls ctx.progress(80) then (100),
  // so this is null on the freshly-enqueued job the install POST returns.
  // Seeded from that row rather than assumed zero, in case that ever changes.
  const [progress, setProgress] = useState<number | null>(null)

  if (!entry) return null

  const canSubmit = consent && hostId != null && name.trim() !== '' && ctid.trim() !== ''

  const submit = () => {
    if (!canSubmit || hostId == null) return
    install.mutate(
      { slug, host_id: hostId, name, ctid: Number(ctid), overrides: {}, consent },
      { onSuccess: (r) => { setJobId(r.job.id); setProgress(r.job.progress_pct) } },
    )
  }

  return (
    <Dialog title={<>Install {entry.name ?? slug}</>} width={520} onClose={onClose}>

    {jobId ? (
      <div className="mt-4">
        <div className="mb-3 flex items-center gap-2">
          {/* Two or three real steps (services/appstore.py), so the ring
              jumps rather than sweeps: honest, not smoothed. Never shown
              before the first step, a zero here would read as stalled. */}
          {progress != null && <Loading value={progress} label="Install progress" size={28} />}
          <span className="text-[12.5px] text-text-2">Installing {entry.name ?? slug}…</span>
        </div>
        <JobLog jobId={jobId} onProgress={setProgress} />
        <Button className="mt-3" variant="ghost" onClick={onClose}>Close</Button>
      </div>
    ) : (
      <>
        <div className="mt-4 space-y-3">
          <select className="w-full rounded-ctl border border-line bg-panel px-3 py-1.5 text-[13px]"
            value={hostId ?? ''} disabled={hosts.isError}
            onChange={(e) => setHostId(Number(e.target.value) || null)}>
            {hosts.isError
              ? <option value="">Could not load hosts</option>
              : <option value="">Select a host…</option>}
            {(hosts.data ?? []).map((h) => <option key={h.id} value={h.id}>{h.name}</option>)}
          </select>
          <input className="w-full rounded-ctl border border-line bg-panel px-3 py-1.5 text-[13px]"
            placeholder="App name" value={name} onChange={(e) => setName(e.target.value)} />
          <input className="w-full rounded-ctl border border-line bg-panel px-3 py-1.5 text-[13px]"
            placeholder="Container ID (CTID)" value={ctid}
            onChange={(e) => setCtid(e.target.value)} />
          <div className="rounded-ctl border border-line-soft bg-elev p-2 font-mono text-[11px] text-text-3">
            {entry.default_cpu} vCPU · {entry.default_ram_mb}MB RAM · {entry.default_disk_gb}GB disk ·{' '}
            {entry.default_os} {entry.default_os_version}
          </div>
          <div className="text-[12px] text-text-2">
            This installs and executes a community-scripts.org script on the target node,
            exactly as if you ran it yourself.
          </div>
          <label className="flex items-center gap-2 text-[12px] text-text-2">
            <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
            I understand this runs as root on the node
          </label>
        </div>
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button variant="primary" disabled={!canSubmit || install.isPending} onClick={submit}>
            Install
          </Button>
        </div>
      </>
    )}
    </Dialog>
  )
}
