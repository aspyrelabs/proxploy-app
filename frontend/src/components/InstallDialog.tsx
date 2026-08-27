import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../api/client'
import { useCatalogEntry, useInstall } from '../api/catalog'
import { PromptFields } from './install/PromptFields'
import { unanswered } from '../lib/install-prompts'
import { figure, text } from '../api/catalogMetadata'
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
  // Needed to tell a sibling node of the same cluster apart from an unrelated
  // host when reading GET /storage, which does not key rows by host_id.
  cluster_name?: string | null
  // "connected" or "unreachable", the only two values. An unreachable host
  // fails every job the install would enqueue, so the picker disables it rather
  // than letting it be chosen only to fail.
  status?: string | null
  // Non-null once this host has acknowledged that installs run a
  // community-scripts.org script as root (api/catalog.py), so the tick is only
  // shown while this is null.
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
  const [answers, setAnswers] = useState<Record<string, string>>({})
  // Default asks nothing that has an honest default; Advanced expands the
  // container-customization block. CTID has an honest default too (blank means
  // the node assigns the next free id) but stays in the base section, since
  // operators commonly want to pick it.
  const [mode, setMode] = useState<'default' | 'advanced'>('default')
  // Empty string means "let resolve_storage_pools decide" (services/
  // appstore.py): its one fallback is an honest default, so Default mode never
  // has to touch this state.
  const [storage, setStorage] = useState({ container: '', template: '' })
  // Each field is null until the operator types into it, meaning "still
  // tracking the derived default below." cpu/ram/disk/os/version derive from
  // the entry's script-parsed default_* columns, NOT
  // raw.metadata.install_methods[].resources, which disagrees for some slugs
  // (dockge is 2/2048/18 in the script and 0/0/0 there). unprivileged stays
  // null until toggled: MOST community-scripts scripts default var_unprivileged
  // to 1 but not all, and inventing 1 would overrule the script merely because
  // Advanced was opened.
  const [coreOverride, setCoreOverride] = useState<{
    cpu: string | null; ram: string | null; disk: string | null; os: string | null
    version: string | null; hostname: string | null; unprivileged: boolean | null
  }>({ cpu: null, ram: null, disk: null, os: null, version: null, hostname: null, unprivileged: null })
  const [jobId, setJobId] = useState<number | null>(null)
  // services/appstore.py::run_install only calls ctx.progress(80) then (100),
  // so this is null on the freshly-enqueued job the install POST returns.
  // Seeded from that row rather than assumed zero.
  const [progress, setProgress] = useState<number | null>(null)

  const host = (hosts.data ?? []).find((h) => h.id === hostId)
  // The node it lands on, falling back to the host record's own name: a
  // standalone host is usually named after its only node.
  const installTarget = host?.node_name ?? host?.name ?? null
  // Called above the early return, with the same queryKey StorageFields uses,
  // so react-query dedupes it against Advanced mode's own fetch.
  const pools = useStoragePools(hostId, host?.node_name, host?.cluster_name)

  // The dialog opens immediately, titled with the slug from the props:
  // `return null` here left the operator with no way to tell a slow catalog
  // from a click that missed. The failure branch is needed because `!entry` is
  // also true forever after a failed fetch. Cancel stays live in both.
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
            {/* Host, App name, CTID. 33px is this dialog's control height,
                not the 37px the settings forms use. */}
            <Skeleton className="h-[33px] w-full rounded-ctl" />
            <Skeleton className="h-[33px] w-full rounded-ctl" />
            <Skeleton className="h-[33px] w-full rounded-ctl" />
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

  // The values CoreFields displays: whatever the operator typed, else the
  // derived default. Computed here rather than stored, so a still-loading
  // `entry` never gets baked into useState's one-shot initial value.
  const core: CoreFieldsValue = {
    cpu: coreOverride.cpu ?? (entry.default_cpu != null ? String(entry.default_cpu) : ''),
    ram: coreOverride.ram ?? (entry.default_ram_mb != null ? String(entry.default_ram_mb) : ''),
    disk: coreOverride.disk ?? (entry.default_disk_gb != null ? String(entry.default_disk_gb) : ''),
    os: coreOverride.os ?? (entry.default_os ?? ''),
    version: coreOverride.version ?? (entry.default_os_version ?? ''),
    hostname: coreOverride.hostname ?? name,
    unprivileged: coreOverride.unprivileged,
  }

  // The one-line summary of what the script would build, with the missing
  // halves left out rather than printed as bare units. Every default_* column
  // is nullable: discovery parses them out of the ct script and plenty of
  // scripts do not set them. figure()/text() decide what counts as missing, so
  // 0 and "" render as nothing here and on the Store detail page alike.
  const defaultsLine = [
    figure(entry.default_cpu) && `${entry.default_cpu} vCPU`,
    figure(entry.default_ram_mb) && `${entry.default_ram_mb}MB RAM`,
    figure(entry.default_disk_gb) && `${entry.default_disk_gb}GB disk`,
    text(entry.default_os)
      && [text(entry.default_os), text(entry.default_os_version)].filter(Boolean).join(' '),
  ].filter(Boolean).join(' · ')

  // Whether the snapshot behind GET /storage has been read at all. An empty
  // candidate list means two opposite things (no such pool here / we have not
  // looked yet), and only this tells them apart, so it gates submit.
  const storageUnknown = hostId != null && pools.state !== 'ok'

  // The sole candidate is not a real choice, so it is DISPLAYED rather than
  // asked for. Nothing is remembered across installs: knownPool consults only
  // the current candidate list, so a host with two or more pools is asked every
  // time.
  const knownContainer = knownPool(pools.rootdir)
  const knownTemplate = knownPool(pools.vztmpl)

  // Default asks no question THAT HAS AN HONEST DEFAULT, and several candidates
  // has none: build.func has none and we do not invent one. BOTH content types
  // get asked: resolve_storage_pools refuses just as flatly on an ambiguous
  // vztmpl, an ordinary Proxmox layout (one rootdir pool plus `local` and any
  // NFS/dir storage carrying vztmpl).
  const asksContainer = !storageUnknown && knownContainer == null && pools.rootdir.length >= 1
  const asksTemplate = !storageUnknown && knownTemplate == null && pools.vztmpl.length >= 1
  const storageSummary = [
    knownContainer && `container ${knownContainer}`,
    knownTemplate && `template ${knownTemplate}`,
  ].filter(Boolean).join(' · ')

  // Asked once per host, then remembered on Host.install_consent_at. Also true,
  // so still asked, while no host is selected.
  const needsConsent = host?.install_consent_at == null

  // CTID is no longer required: blank means the node assigns the next free
  // id (InstallIn.ctid, backend/proxploy/api/catalog.py).
  // What the upstream script asks that build.func cannot answer from the
  // environment. Empty for every app that was installable before this existed.
  const prompts = entry?.prompts ?? []
  // A gate is unticked until the operator ticks it, and a prompt with no
  // default has no value to fall back on, so both block Install. Letting either
  // through produces an install that blocks on a closed stdin.
  const missingAnswers = unanswered(prompts, answers)

  const canSubmit = (consent || !needsConsent) && hostId != null && name.trim() !== ''
    && !storageUnknown
    && (!asksContainer || storage.container !== '')
    && (!asksTemplate || storage.template !== '')
    && missingAnswers.length === 0

  const submit = () => {
    if (!canSubmit || hostId == null) return
    // Only send a key the operator actually picked. An empty string would reach
    // resolve_storage_pools as supplied-but-blank; its `.strip() or None` treats
    // that as absent anyway, but sending nothing is more honest. Same for the
    // core fields: a field cleared to blank is withheld, not sent as `var_x=""`.
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
      if (core.unprivileged != null) overrides.unprivileged = core.unprivileged ? '1' : '0'
    }
    install.mutate(
      { slug, host_id: hostId, name, ctid: ctid.trim() === '' ? null : Number(ctid),
        overrides, consent, answers },
      { onSuccess: (r) => { setJobId(r.job.id); setProgress(r.job.progress_pct) } },
    )
  }

  return (
    /* Two states, two widths. The form reads fine at 520; the install
       transcript is a terminal, and 520 wrapped community-scripts' output
       mid-line, where the useful part lives: the finished URL, the port, and
       whatever went wrong. max() keeps it from ever being NARROWER than the
       form. */
    <Dialog title={<>Install {entry.name ?? slug}</>}
            width={jobId ? 'max(520px, 60vw)' : 520} onClose={onClose}>

    {jobId ? (
      <div className="mt-4">
        <div className="mb-3 flex items-center gap-2">
          {/* Two or three real steps (services/appstore.py), so the ring jumps
              rather than sweeps. Never shown before the first step: a zero
              would read as stalled. */}
          {progress != null && <Loading value={progress} label="Install progress" size={28} />}
          {/* The DESTINATION, not the app again: "Installing Alpine-IT-Tools…"
              under the title "Install Alpine-IT-Tools" tells the reader nothing
              the heading did not, and where it is going is the one thing the
              dialog stops saying once the transcript replaces the form. Bare
              verb when the host is not readable. */}
          <span className="text-[12.5px] text-text-2">
            {installTarget ? `Installing on ${installTarget}…` : 'Installing…'}
          </span>
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
              // Storage pools are per host: a pool picked on the old host is
              // not necessarily valid on the new one, so a host switch clears
              // the picks.
              setStorage({ container: '', template: '' })
            }}>
            {hosts.isError
              ? <option value="">Could not load hosts</option>
              : hosts.isLoading
                ? <option value="">Loading hosts…</option>
                : <option value="">Select a host…</option>}
            {(hosts.data ?? []).map((h) => (
              <option key={h.id} value={h.id} disabled={h.status === 'unreachable'}>
                {h.name}{h.status === 'unreachable' ? ' (unreachable, cannot install here)' : ''}
              </option>
            ))}
          </select>
          {/* Labelled, not just placeheld, and asked in BOTH modes. A second
              install of the same app is ordinary, and the name is then the only
              thing telling the two apart. Deliberately NOT prefilled with the
              catalog name. */}
          <div>
            <label className="mb-1 block text-[11px] uppercase tracking-wide text-text-3"
              htmlFor="install-app-name">App name</label>
            <input id="install-app-name" required
              className="w-full rounded-ctl border border-line bg-panel px-3 py-1.5 text-[13px]"
              placeholder="jellyfin-prod" value={name}
              onChange={(e) => setName(e.target.value)} />
          </div>
          <input className="w-full rounded-ctl border border-line bg-panel px-3 py-1.5 text-[13px]"
            placeholder="Container ID (CTID)" value={ctid}
            onChange={(e) => setCtid(e.target.value)} />
          {/* Nothing recorded at all means no box, not an empty one. Default
              mode only: this is the APP's own script-parsed defaults, while
              Advanced mode's CoreFields shows the fields that actually decide
              the install. Showing both was one true line and one stale one. */}
          {mode === 'default' && defaultsLine !== '' && (
            <div className="rounded-ctl border border-line-soft bg-elev p-2 font-mono text-[11px] text-text-3">
              {defaultsLine}
            </div>
          )}
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
              <StorageFields hostId={hostId} node={host?.node_name}
              clusterName={host?.cluster_name} container={storage.container}
                template={storage.template} onChange={setStorage} />
            </div>
          )}
          <PromptFields prompts={prompts} answers={answers} onChange={setAnswers} />
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
