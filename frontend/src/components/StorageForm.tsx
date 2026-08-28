import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ApiError, api } from '../api/client'
import { useEntitlements } from '../api/hooks'
import { notify } from '../lib/notify'
import { useAttachStorage, useDetachStorage, useEditStorage } from '../api/storage'
import type { StorageRow } from '../api/storage'
import { LockVeil } from './LockVeil'
import { inputCls } from './LoginForm'
import { Button } from './ui/button'
import { Dialog } from './ui/dialog'

type HostRow = { id: number; name: string }

const TYPES = ['dir', 'nfs', 'cifs', 'pbs'] as const

// PVE's plugin names said in full. `cifs` is SMB (the name is historical, the
// driver speaks SMB2/SMB3), and `dir` is a folder on the node itself, not
// anything shared: neither is guessable from four letters in a dropdown.
const TYPE_LABEL: Record<string, string> = {
  dir: 'dir · folder on the node',
  nfs: 'nfs · NFS share',
  cifs: 'cifs · SMB or CIFS share',
  pbs: 'pbs · Proxmox Backup Server',
}

// Per-plugin field lists. The backend forwards `config` to Proxmox unvalidated
// on purpose (Proxmox is the authority on what a plugin accepts), so this map
// is a CONVENIENCE, not a schema: an unlisted key is a missing input here, not
// a rejected request there.
const FIELDS: Record<string, [string, string, string, string?][]> = {
  dir: [['path', 'Path', 'text']],
  nfs: [['server', 'Server', 'text'], ['export', 'Export', 'text'],
        ['options', 'Mount options', 'text', 'optional, for example vers=4.2']],
  cifs: [['server', 'Server', 'text'], ['share', 'Share', 'text'],
         ['username', 'Username', 'text'], ['password', 'Password', 'password']],
  pbs: [['server', 'Server', 'text'], ['datastore', 'Datastore', 'text'],
        ['username', 'Username', 'text'], ['password', 'Password', 'password'],
        ['fingerprint', 'Fingerprint', 'text']],
}

// Proxmox's content types, in the order its own storage dialog lists them.
// A free-text box here let a typo ("backups", "isos") through to PVE, and the
// operator only found out when nothing could write to the datastore.
const CONTENT_ALL = ['images', 'rootdir', 'vztmpl', 'iso', 'backup', 'snippets', 'import']
const CONTENT_LABEL: Record<string, string> = {
  images: 'Disk images',
  rootdir: 'Container volumes',
  vztmpl: 'Container templates',
  iso: 'ISO images',
  backup: 'Backups',
  snippets: 'Snippets',
  import: 'Importable disks',
}
// A PBS datastore holds backups and nothing else. Every other plugin takes the
// full set, INCLUDING a type this map has never heard of: Edit opens on any row
// the Storage page lists (lvmthin, zfspool, rbd), and narrowing those by guess
// would hide a tick the datastore already carries.
const CONTENT_FOR: Record<string, string[]> = { pbs: ['backup'] }

const errText = (e: unknown) =>
  e instanceof ApiError
    ? String((e.body as any)?.detail ?? (e.body as any)?.title ?? e.message)
    : 'Request failed'

export function StorageForm({ existing, onClose }:
  { existing: StorageRow | null; onClose: () => void }) {
  const editing = existing != null
  const ent = useEntitlements()
  // ent.has() returns false until the first fetch resolves, so gating on
  // !has() alone veils this for every plan during load (LifecycleActions and
  // settings.tsx carry the same guard).
  const locked = ent.data != null && !ent.has('storage.manage')

  const hosts = useQuery({
    queryKey: ['hosts'], queryFn: () => api<HostRow[]>('/hosts'), enabled: !editing,
  })
  const attach = useAttachStorage()
  const edit = useEditStorage()
  const detach = useDetachStorage()

  const [hostId, setHostId] = useState<number | null>(existing?.host_id ?? null)
  const [name, setName] = useState(existing?.storage ?? '')
  // Editing keeps whatever Proxmox reported, including nothing: defaulting the
  // empty case turned "this datastore reports no type" into a confident "dir".
  const [type, setType] = useState<string>(existing ? existing.type ?? '' : 'dir')
  const [cfg, setCfg] = useState<Record<string, string>>({
    content: existing?.content.join(',') ?? '',
  })
  const set = (k: string, v: string) => setCfg((s) => ({ ...s, [k]: v }))

  const fields: [string, string, string, string?][] = FIELDS[type] ?? []
  // `content` stays a comma string in state, the shape both PVE and the rest
  // of this form already speak; the checkboxes below are just a view of it.
  const ticked = new Set((cfg.content ?? '').split(',').map((c) => c.trim()).filter(Boolean))
  const contentOpts = [...new Set([...(CONTENT_FOR[type] ?? CONTENT_ALL), ...ticked])]
  const toggleContent = (c: string) => {
    const next = new Set(ticked)
    if (!next.delete(c)) next.add(c)
    // Written back in the list's own order, not click order, so the same set
    // of ticks always produces the same string.
    set('content', contentOpts.filter((o) => next.has(o)).join(','))
  }
  // Blank means "not supplied", on edit that is how a password stays
  // unchanged, and on attach it is how an optional plugin key is omitted.
  const filled = Object.fromEntries(
    [...fields.map(([k]) => k), 'content']
      .map((k) => [k, (cfg[k] ?? '').trim()]).filter(([, v]) => v !== ''),
  ) as Record<string, string>

  const canAttach = hostId != null && name.trim() !== '' && Object.keys(filled).length > 0
  const busy = attach.isPending || edit.isPending || detach.isPending

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    if (editing && existing) {
      edit.mutate({ host_id: existing.host_id, storage: existing.storage, config: filled }, {
        onSuccess: (r) => { notify.success(`Updated ${r.updated.join(', ')}`); onClose() },
        onError: (err) => notify.error(errText(err)),
      })
      return
    }
    if (!canAttach || hostId == null) return
    attach.mutate({ host_id: hostId, storage: name.trim(), type, config: filled }, {
      onSuccess: () => { notify.success(`Attached ${name.trim()}`); onClose() },
      onError: (err) => notify.error(errText(err)),
    })
  }

  const remove = () => {
    if (!existing) return
    // window.confirm is this codebase's destructive-but-not-self precedent
    // (routes/settings.tsx). Detaching strands guest disks behind a removed
    // definition, which is exactly the class of misclick that needs a stop.
    if (!window.confirm(
      `Detach storage "${existing.storage}" from ${existing.host_name}? ` +
      'Guests still pointing at it will lose their disks. The data upstream is not deleted.')) return
    detach.mutate({ host_id: existing.host_id, storage: existing.storage }, {
      onSuccess: () => { notify.success(`Detached ${existing.storage}`); onClose() },
      onError: (err) => notify.error(errText(err)),
    })
  }

  return (
    <Dialog title={<>{editing ? `Edit ${existing?.storage}` : 'Add storage'}</>} width={520} onClose={onClose}>

    {/* Never hide a gated feature, veil it. The Close button sits OUTSIDE the
        veil: LockVeil sets pointer-events:none on its children, and a dialog
        you cannot dismiss is worse than the feature being gated. */}
    <LockVeil locked={locked}
      title="Storage management is a Pro feature"
      subtitle="Attach, edit and detach datastores without leaving Proxploy.">
      <form onSubmit={submit} className="space-y-3">
        {!editing && (
          <div>
            <label htmlFor="sf-host"
              className="mb-1 block text-[11px] uppercase tracking-wide text-text-3">Host</label>
            <select id="sf-host" className={inputCls} value={hostId ?? ''}
              disabled={hosts.isError || hosts.isLoading}
              onChange={(e) => setHostId(Number(e.target.value) || null)}>
              {hosts.isError
                ? <option value="">Could not load hosts</option>
                : hosts.isLoading
                  ? <option value="">Loading hosts…</option>
                  : <option value="">Select a host…</option>}
              {(hosts.data ?? []).map((h) => <option key={h.id} value={h.id}>{h.name}</option>)}
            </select>
          </div>
        )}
        <div>
          <label htmlFor="sf-name"
            className="mb-1 block text-[11px] uppercase tracking-wide text-text-3">Name</label>
          <input id="sf-name" className={inputCls} value={name} disabled={editing}
            placeholder="nfs-media" onChange={(e) => setName(e.target.value)} />
        </div>
        <div>
          <label htmlFor="sf-type"
            className="mb-1 block text-[11px] uppercase tracking-wide text-text-3">Type</label>
          <select id="sf-type" className={inputCls} value={type} disabled={editing}
            onChange={(e) => {
              setType(e.target.value)
              // Same reason the initial state pre-ticks it: pbs has one content
              // type and switching to it should not silently clear the set.
              if (e.target.value === 'pbs') set('content', 'backup')
            }}>
            {TYPES.map((t) => <option key={t} value={t}>{TYPE_LABEL[t] ?? t}</option>)}
            {/* Edit opens on any row (lvmthin, zfspool, rbd aren't in TYPES);
                with no matching option the browser picks the first, so editing
                such a datastore read "dir" — a wrong answer for a type the
                caller already knew. */}
            {!TYPES.some((t) => t === type) &&
              <option value={type}>{type === '' ? 'unknown' : type}</option>}
          </select>
        </div>
        {fields.map(([k, label, inputType, placeholder]) => (
          <div key={k}>
            <label htmlFor={`sf-${k}`}
              className="mb-1 block text-[11px] uppercase tracking-wide text-text-3">{label}</label>
            <input id={`sf-${k}`} className={inputCls} type={inputType}
              placeholder={placeholder}
              value={cfg[k] ?? ''} onChange={(e) => set(k, e.target.value)} />
          </div>
        ))}
        <fieldset>
          <legend className="mb-1 block text-[11px] uppercase tracking-wide text-text-3">
            Content
          </legend>
          <div className="grid grid-cols-2 gap-x-4 gap-y-1.5">
            {contentOpts.map((c) => (
              <label key={c} className="flex items-center gap-2 text-[13px]">
                <input type="checkbox" checked={ticked.has(c)}
                  onChange={() => toggleContent(c)} />
                {/* An unknown key can only come from the datastore's own
                    reported content, so it is shown as PVE named it. */}
                <span>{CONTENT_LABEL[c] ?? c}</span>
              </label>
            ))}
          </div>
        </fieldset>
        <div className="flex items-center gap-2 pt-1">
          <Button type="submit" variant="primary" disabled={busy || (!editing && !canAttach)}>
            {editing ? 'Save' : 'Attach'}
          </Button>
          {editing && (
            <Button type="button" variant="danger" disabled={busy} onClick={remove}>
              Detach
            </Button>
          )}
        </div>
      </form>
    </LockVeil>

    <div className="mt-4 flex justify-end">
      <Button variant="ghost" onClick={onClose}>Close</Button>
    </div>
    </Dialog>
  )
}
