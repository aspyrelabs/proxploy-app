import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../api/client'
import { useCatalogEntry, useInstall } from '../api/catalog'
import { CoreFields, type CoreFieldsValue } from './install/CoreFields'
import { knownPool, useStoragePools } from './install/pools'
import { StorageFields } from './install/StorageFields'
import { JobLog } from './JobLog'
import { Button } from './ui/button'
import { Dialog } from './ui/dialog'
import { Loading } from './ui/loading'
import { Skeleton, SkeletonGroup, SkeletonLine } from './ui/skeleton'

type HostRow = {
  id: number; name: string
  // The node whose datastores an install on this host lands on: the same
  // host.node_name _storage_pools queries (services/appstore.py).
  node_name?: string | null
  // Set once Default has asked the storage question and the operator has
  // answered it (Task 13; written back by POST .../install). NULL/absent
  // means "not chosen yet".
  default_container_storage?: string | null
  default_template_storage?: string | null
  // Non-null once this host has acknowledged that installs run a
  // community-scripts.org script as root (api/catalog.py). Asking again
  // surfaces no new information, so the tick is only shown while this is null.
  install_consent_at?: string | null
}

export function InstallDialog({ slug, onClose }: { slug: string; onClose: () => void }) {
  const { data: entry, isError: entryFailed } = useCatalogEntry(slug)
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
  // Each field is null until the operator types into it, meaning "still
  // tracking the derived default computed below." cpu/ram/disk/os/version
  // derive from the catalog entry's script-parsed default_* columns (Task
  // 7): NOT raw.metadata.install_methods[].resources, which disagrees for
  // some slugs (dockge is 2/2048/18 in the script and 0/0/0 in that
  // metadata). hostname derives from the app name typed above instead,
  // since there is no script-parsed default for it. unprivileged is null
  // until toggled and stays null: MOST community-scripts install scripts
  // default var_unprivileged to 1, but not all (a ct script declaring
  // var_unprivileged="0" disagrees), and Proxploy has no parsed column for
  // it. Inventing 1 and then sending it would overrule those scripts merely
  // because the operator opened Advanced.
  const [coreOverride, setCoreOverride] = useState<{
    cpu: string | null; ram: string | null; disk: string | null; os: string | null
    version: string | null; hostname: string | null; unprivileged: boolean | null
  }>({ cpu: null, ram: null, disk: null, os: null, version: null, hostname: null, unprivileged: null })
  const [jobId, setJobId] = useState<number | null>(null)
  // services/appstore.py::run_install only calls ctx.progress(80) then (100),
  // so this is null on the freshly-enqueued job the install POST returns.
  // Seeded from that row rather than assumed zero, in case that ever changes.
  const [progress, setProgress] = useState<number | null>(null)

  const host = (hosts.data ?? []).find((h) => h.id === hostId)
  // Called above the early return, and with the same queryKey StorageFields
  // uses, so react-query dedupes it against Advanced mode's own fetch rather
  // than doubling the request.
  const pools = useStoragePools(hostId, host?.node_name)

  // `return null` here meant the operator pressed Install on a store card and
  // the screen did nothing at all until the entry arrived, with no way to tell
  // a slow catalog from a click that missed. The dialog opens immediately
  // instead, titled with the slug it was opened for, which is already known
  // from the props and needs nothing fetched.
  //
  // The failure branch is here because the placeholder created the need for
  // it: `!entry` is also true forever after a failed fetch, and a dialog that
  // pulses for ever is worse than the blank it replaced. Cancel stays live in
  // both, so a dialog that cannot fill itself in can still be closed.
  if (!entry) {
    return (
      <Dialog title={<>Install {slug}</>} width={520} onClose={onClose}>
        {entryFailed ? (
          <p className="mt-4 text-[12.5px] text-text-3">
            Proxploy could not read this catalog entry, so there is nothing to install from
            yet. Close this and try again.
          </p>
        ) : (
          <SkeletonGroup label="Loading install options" className="mt-4 space-y-3">
            {/* Default and Advanced, each a radio beside a name and a line of
                explanation. */}
            <div className="space-y-2">
              {[0, 1].map((i) => (
                <div key={i} className="flex items-start gap-2">
                  <Skeleton className="mt-0.5 h-3.5 w-3.5 rounded-full" />
                  <div className="min-w-0 flex-1">
                    <SkeletonLine className="w-20 text-[13px]" />
                    <SkeletonLine className="w-64 max-w-full text-[12px]" />
                  </div>
                </div>
              ))}
            </div>
            {/* Host, App name, CTID. `px-3 py-1.5` around a 13px line box
                inside a 1px border is 33px, which is this dialog's control
                height and not the 37px the settings forms use. */}
            <Skeleton className="h-[33px] w-full rounded-ctl" />
            <Skeleton className="h-[33px] w-full rounded-ctl" />
            <Skeleton className="h-[33px] w-full rounded-ctl" />
            {/* The derived-defaults strip: p-2 around one 11px mono line. */}
            <Skeleton className="h-[34px] w-full rounded-ctl" />
            <SkeletonLine className="w-full text-[12px]" />
            <SkeletonLine className="w-2/3 text-[12px]" />
          </SkeletonGroup>
        )}
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
        </div>
      </Dialog>
    )
  }

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

  // Whether the snapshot behind GET /storage has been read at all. Empty
  // candidate lists mean two opposite things (this host has no such pool /
  // we have not looked yet) and only this tells them apart, so it gates
  // submit: a form that cannot see the pools must not look complete.
  const storageUnknown = hostId != null && pools.state !== 'ok'

  // Remembering must not become deciding silently: once the pool is known
  // (remembered and still a candidate, or the sole candidate), DISPLAY it
  // rather than asking again, so the operator can always see which pool an
  // install will use.
  const knownContainer = knownPool(host?.default_container_storage, pools.rootdir)
  const knownTemplate = knownPool(host?.default_template_storage, pools.vztmpl)

  // Default asks no question THAT HAS AN HONEST DEFAULT. Several candidates
  // and no remembered answer has no default: build.func has none and we do
  // not invent one, so these are the questions Default has to ask. BOTH
  // content types get asked, not just rootdir: resolve_storage_pools refuses
  // just as flatly on an ambiguous vztmpl (one rootdir pool plus `local` and
  // any NFS/dir storage carrying vztmpl is an ordinary Proxmox layout), and
  // a Default mode with no field for it fails there forever.
  //
  // `length >= 1`, not `> 1`: knownPool returning null no longer implies "0
  // or 2+ candidates". A remembered value that is no longer a candidate
  // resolves to null even with exactly one candidate left, because
  // resolve_storage_pools refuses to quietly swap a remembered pool for the
  // sole survivor, it re-asks. A `> 1` gate would swallow that one case
  // (a field never rendering, canSubmit never requiring it, the job failing
  // on the stale name with no way to fix it in Default mode), while still
  // correctly asking nothing when there are zero real candidates (an empty
  // select nobody could ever fill in).
  const asksContainer = !storageUnknown && knownContainer == null && pools.rootdir.length >= 1
  const asksTemplate = !storageUnknown && knownTemplate == null && pools.vztmpl.length >= 1
  const storageSummary = [
    knownContainer && `container ${knownContainer}`,
    knownTemplate && `template ${knownTemplate}`,
  ].filter(Boolean).join(' · ')

  // Asked once per host, then remembered on Host.install_consent_at: re-asking
  // an operator who already acknowledged surfaces no new information. Also
  // true (so still asked) while no host is selected.
  const needsConsent = host?.install_consent_at == null

  // CTID is no longer required: blank means the node assigns the next free
  // id (InstallIn.ctid, backend/proxploy/api/catalog.py).
  const canSubmit = (consent || !needsConsent) && hostId != null && name.trim() !== ''
    && !storageUnknown
    && (!asksContainer || storage.container !== '')
    && (!asksTemplate || storage.template !== '')

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
      // Only once the operator actually toggled it: untouched means "whatever
      // this app's script declares", which is not ours to answer.
      if (core.unprivileged != null) overrides.unprivileged = core.unprivileged ? '1' : '0'
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
            value={hostId ?? ''} disabled={hosts.isError || hosts.isLoading}
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
              : hosts.isLoading
                ? <option value="">Loading hosts…</option>
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
          {storageUnknown && (
            <div className="rounded-ctl border border-line-soft bg-elev p-2 text-[12px] text-text-3">
              {pools.state === 'error'
                ? 'Could not read the storage pools for this host, so there is no way to tell '
                  + 'which pool an install would land on. Install stays disabled until they load.'
                : 'Reading the storage pools for this host…'}
            </div>
          )}
          {mode === 'default' && asksContainer && (
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
                {pools.rootdir.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
            </div>
          )}
          {mode === 'default' && asksTemplate && (
            <div>
              <label htmlFor="default-template-storage"
                className="mb-1 block text-[11px] uppercase tracking-wide text-text-3">
                Template storage
              </label>
              <select id="default-template-storage"
                className="w-full rounded-ctl border border-line bg-panel px-3 py-1.5 text-[13px]"
                value={storage.template}
                onChange={(e) => setStorage({ ...storage, template: e.target.value })}>
                <option value="">Select a pool…</option>
                {pools.vztmpl.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
            </div>
          )}
          {mode === 'default' && storageSummary !== '' && (
            <div className="rounded-ctl border border-line-soft bg-elev p-2 text-[11px] text-text-3">
              Storage: {storageSummary}
            </div>
          )}
          {mode === 'advanced' && (
            <div className="rounded-ctl border border-dashed border-line-soft p-3 text-[12px] text-text-3">
              <span className="text-text">Container customization</span>
              <span className="block mt-1">
                Resources, OS and storage are adjustable here. Networking, tags and SSH keys
                are not: those use the app script&rsquo;s own defaults.
              </span>
              <CoreFields value={core} onChange={(patch) => setCoreOverride((c) => ({ ...c, ...patch }))} />
              <StorageFields hostId={hostId} node={host?.node_name} container={storage.container}
                template={storage.template} onChange={setStorage} />
            </div>
          )}
          <div className="text-[12px] text-text-2">
            This installs and executes a community-scripts.org script on the target node,
            exactly as if you ran it yourself.
          </div>
          {needsConsent && (
            <label className="flex items-center gap-2 text-[12px] text-text-2">
              <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
              I understand this runs as root on the node
            </label>
          )}
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
