import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../api/client'
import { useCatalogEntry, useInstall } from '../api/catalog'
import { StorageFields } from './install/StorageFields'
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
  // Default asks nothing that has an honest default; Advanced expands the
  // container-customization block Tasks 9-11 fill in. CTID has an honest
  // default too (blank -> node assigns the next free id) but stays in the
  // base section: unlike vCPU/RAM/disk, operators commonly want to pick it
  // even on an otherwise-default install, and Task 12 hangs its collision
  // check off this same field.
  const [mode, setMode] = useState<'default' | 'advanced'>('default')
  // Empty string means "let resolve_storage_pools decide" (backend/proxploy/
  // services/appstore.py): its own fallbacks (remembered host default, then
  // sole candidate) are honest defaults, so Default mode never has to touch
  // this state at all.
  const [storage, setStorage] = useState({ container: '', template: '' })
  const [jobId, setJobId] = useState<number | null>(null)
  // services/appstore.py::run_install only calls ctx.progress(80) then (100),
  // so this is null on the freshly-enqueued job the install POST returns.
  // Seeded from that row rather than assumed zero, in case that ever changes.
  const [progress, setProgress] = useState<number | null>(null)

  if (!entry) return null

  // CTID is no longer required: blank means the node assigns the next free
  // id (InstallIn.ctid, backend/proxploy/api/catalog.py). Host consent is
  // still asked here every time; the catalog/host payloads this dialog can
  // see do not yet expose Host.install_consent_at, so there is no way to
  // tell from here whether this host already acknowledged.
  const canSubmit = consent && hostId != null && name.trim() !== ''

  const submit = () => {
    if (!canSubmit || hostId == null) return
    // Only send a key the operator actually picked. An empty string here
    // would reach resolve_storage_pools as a supplied-but-blank value; its
    // own `.strip() or None` treats that the same as absent, but sending
    // nothing is more honest about "the operator did not choose."
    const overrides: Record<string, string> = {}
    if (storage.container) overrides.container_storage = storage.container
    if (storage.template) overrides.template_storage = storage.template
    install.mutate(
      { slug, host_id: hostId, name, ctid: ctid.trim() === '' ? null : Number(ctid), overrides, consent },
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
          <div className="space-y-2">
            <label className="flex items-start gap-2 text-[13px] text-text-2">
              <input type="radio" name="install-mode" className="mt-0.5" checked={mode === 'default'}
                onChange={() => setMode('default')} />
              <span>
                <span className="text-text">Default</span>
                <span className="block text-[12px] text-text-3">
                  Installs with {entry.name ?? slug}&rsquo;s own defaults.
                </span>
              </span>
            </label>
            <label className="flex items-start gap-2 text-[13px] text-text-2">
              <input type="radio" name="install-mode" className="mt-0.5" checked={mode === 'advanced'}
                onChange={() => setMode('advanced')} />
              <span>
                <span className="text-text">Advanced</span>
                <span className="block text-[12px] text-text-3">
                  Customize vCPU, RAM, disk, storage and more before install.
                </span>
              </span>
            </label>
          </div>
          <select className="w-full rounded-ctl border border-line bg-panel px-3 py-1.5 text-[13px]"
            aria-label="Host"
            value={hostId ?? ''} disabled={hosts.isError}
            onChange={(e) => {
              setHostId(Number(e.target.value) || null)
              // Storage pools are per host (StorageFields): a pool picked on
              // the old host is not necessarily valid on the new one, so a
              // host switch clears the picks instead of letting a name that
              // may not exist there reach the install as an override.
              setStorage({ container: '', template: '' })
            }}>
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
          {mode === 'advanced' && (
            <div className="rounded-ctl border border-dashed border-line-soft p-3 text-[12px] text-text-3">
              <span className="text-text">Container customization</span>
              <span className="block mt-1">
                Resource and OS options land here in a later task.
              </span>
              <StorageFields hostId={hostId} container={storage.container} template={storage.template}
                onChange={setStorage} />
            </div>
          )}
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
