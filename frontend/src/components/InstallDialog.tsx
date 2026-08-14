import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../api/client'
import { useCatalogEntry, useInstall } from '../api/catalog'
import { CoreFields, type CoreFieldsValue } from './install/CoreFields'
import { StorageFields } from './install/StorageFields'
import { JobLog } from './JobLog'
import { Button } from './ui/button'
import { Dialog } from './ui/dialog'
import { Loading } from './ui/loading'

type HostRow = {
  id: number; name: string
  // Set once Default has asked the storage question and the operator has
  // answered it (Task 13; written back by POST .../install). NULL/absent
  // means "not chosen yet".
  default_container_storage?: string | null
  default_template_storage?: string | null
}
type StorageRow = { host_id: number; node: string; storage: string; content: string[] }

export function InstallDialog({ slug, onClose }: { slug: string; onClose: () => void }) {
  const { data: entry } = useCatalogEntry(slug)
  const hosts = useQuery({ queryKey: ['hosts'], queryFn: () => api<HostRow[]>('/hosts') })
  // Same queryKey StorageFields uses, so react-query dedupes this against
  // Advanced mode's own fetch rather than doubling the request.
  const storages = useQuery({ queryKey: ['storage'], queryFn: () => api<StorageRow[]>('/storage') })
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
  // Each field is null until the operator types into it, meaning "still
  // tracking the derived default computed below." cpu/ram/disk/os/version
  // derive from the catalog entry's script-parsed default_* columns (Task
  // 7): NOT raw.metadata.install_methods[].resources, which disagrees for
  // some slugs (dockge is 2/2048/18 in the script and 0/0/0 in that
  // metadata). hostname derives from the app name typed above instead,
  // since there is no script-parsed default for it. unprivileged has no
  // per-entry default at all: every community-scripts install script
  // defaults var_unprivileged to 1, so the checkbox starts checked.
  const [coreOverride, setCoreOverride] = useState<{
    cpu: string | null; ram: string | null; disk: string | null; os: string | null
    version: string | null; hostname: string | null; unprivileged: boolean
  }>({ cpu: null, ram: null, disk: null, os: null, version: null, hostname: null, unprivileged: true })
  const [jobId, setJobId] = useState<number | null>(null)
  // services/appstore.py::run_install only calls ctx.progress(80) then (100),
  // so this is null on the freshly-enqueued job the install POST returns.
  // Seeded from that row rather than assumed zero, in case that ever changes.
  const [progress, setProgress] = useState<number | null>(null)

  if (!entry) return null

  // The values CoreFields actually displays: whatever the operator typed,
  // else the derived default. Computed here rather than stored directly so
  // a still-loading `entry` (undefined on the very first render, before
  // this early return) never gets baked into useState's one-shot initial
  // value.
  const core: CoreFieldsValue = {
    cpu: coreOverride.cpu ?? (entry.default_cpu != null ? String(entry.default_cpu) : ''),
    ram: coreOverride.ram ?? (entry.default_ram_mb != null ? String(entry.default_ram_mb) : ''),
    disk: coreOverride.disk ?? (entry.default_disk_gb != null ? String(entry.default_disk_gb) : ''),
    os: coreOverride.os ?? (entry.default_os ?? ''),
    version: coreOverride.version ?? (entry.default_os_version ?? ''),
    hostname: coreOverride.hostname ?? name,
    unprivileged: coreOverride.unprivileged,
  }

  const host = (hosts.data ?? []).find((h) => h.id === hostId)
  const rootdirPools = (storages.data ?? [])
    .filter((r) => r.host_id === hostId && r.content.includes('rootdir'))
    .map((r) => r.storage)
  const vztmplPools = (storages.data ?? [])
    .filter((r) => r.host_id === hostId && r.content.includes('vztmpl'))
    .map((r) => r.storage)

  // Default asks no question THAT HAS AN HONEST DEFAULT. Two rootdir pools
  // have no default: build.func has none and we do not invent one, so this
  // is the one question Default has to ask. One candidate is not a choice,
  // and a remembered answer (Host.default_container_storage) is shown
  // rather than re-asked.
  const needsStoragePrompt =
    hostId != null && !host?.default_container_storage && rootdirPools.length > 1

  // Remembering must not become deciding silently: once the pool is known
  // (remembered, or the sole candidate), DISPLAY it rather than asking
  // again, so the operator can always see which pool an install will use.
  const showsStorageSummary = hostId != null && !needsStoragePrompt
  const resolvedContainer = host?.default_container_storage
    ?? (rootdirPools.length === 1 ? rootdirPools[0] : null)
  const resolvedTemplate = host?.default_template_storage
    ?? (vztmplPools.length === 1 ? vztmplPools[0] : null)

  // CTID is no longer required: blank means the node assigns the next free
  // id (InstallIn.ctid, backend/proxploy/api/catalog.py). Host consent is
  // still asked here every time; the catalog/host payloads this dialog can
  // see do not yet expose Host.install_consent_at, so there is no way to
  // tell from here whether this host already acknowledged.
  const canSubmit = consent && hostId != null && name.trim() !== ''
    && (!needsStoragePrompt || storage.container !== '')

  const submit = () => {
    if (!canSubmit || hostId == null) return
    // Only send a key the operator actually picked or that a field with an
    // honest fallback (an empty string) would otherwise mangle. An empty
    // string for storage would reach resolve_storage_pools as a
    // supplied-but-blank value; its own `.strip() or None` treats that the
    // same as absent, but sending nothing is more honest about "the
    // operator did not choose." Same reasoning for the core fields below:
    // Default mode never customized anything, so it sends none of these,
    // and even in Advanced mode a field the operator cleared to blank is
    // withheld rather than sent as `var_x=""`.
    const overrides: Record<string, string> = {}
    if (storage.container) overrides.container_storage = storage.container
    if (storage.template) overrides.template_storage = storage.template
    if (mode === 'advanced') {
      const setIfFilled = (key: string, val: string) => { if (val.trim() !== '') overrides[key] = val.trim() }
      setIfFilled('cpu', core.cpu)
      setIfFilled('ram', core.ram)
      setIfFilled('disk', core.disk)
      setIfFilled('os', core.os)
      setIfFilled('version', core.version)
      setIfFilled('hostname', core.hostname)
      overrides.unprivileged = core.unprivileged ? '1' : '0'
    }
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
                  Customize resources, OS, storage and more before install.
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
          {mode === 'default' && needsStoragePrompt && (
            <div>
              <label htmlFor="default-container-storage"
                className="mb-1 block text-[11px] uppercase tracking-wide text-text-3">
                Container storage
              </label>
              <select id="default-container-storage"
                className="w-full rounded-ctl border border-line bg-panel px-3 py-1.5 text-[13px]"
                value={storage.container}
                onChange={(e) => setStorage({ ...storage, container: e.target.value })}>
                <option value="">Select a pool…</option>
                {rootdirPools.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
            </div>
          )}
          {mode === 'default' && showsStorageSummary && (resolvedContainer || resolvedTemplate) && (
            <div className="rounded-ctl border border-line-soft bg-elev p-2 text-[11px] text-text-3">
              Storage: container {resolvedContainer ?? '—'} · template {resolvedTemplate ?? '—'}
            </div>
          )}
          {mode === 'advanced' && (
            <div className="rounded-ctl border border-dashed border-line-soft p-3 text-[12px] text-text-3">
              <span className="text-text">Container customization</span>
              <span className="block mt-1">
                Network and remaining advanced options land here in a later task.
              </span>
              <CoreFields value={core} onChange={(patch) => setCoreOverride((c) => ({ ...c, ...patch }))} />
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
