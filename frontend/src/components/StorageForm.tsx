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

// Per-plugin field lists. The backend forwards `config` to Proxmox unvalidated
// on purpose (Proxmox is the authority on what a plugin accepts), so this map
// is a CONVENIENCE, not a schema: an unlisted key is a missing input here, not
// a rejected request there.
const FIELDS: Record<string, [string, string, string][]> = {
  dir: [['path', 'Path', 'text']],
  nfs: [['server', 'Server', 'text'], ['export', 'Export', 'text']],
  cifs: [['server', 'Server', 'text'], ['share', 'Share', 'text'],
         ['username', 'Username', 'text'], ['password', 'Password', 'password']],
  pbs: [['server', 'Server', 'text'], ['datastore', 'Datastore', 'text'],
        ['username', 'Username', 'text'], ['password', 'Password', 'password'],
        ['fingerprint', 'Fingerprint', 'text']],
}

const errText = (e: unknown) =>
  e instanceof ApiError
    ? String((e.body as any)?.detail ?? (e.body as any)?.title ?? e.message)
    : 'Request failed'

export function StorageForm({ existing, onClose, defaultType = 'dir' }:
  { existing: StorageRow | null; onClose: () => void; defaultType?: string }) {
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
  // `defaultType` lets the Backups page open this same form pre-set to `pbs`
  // for its "Connect PBS datastore" affordance (doc 10's Phase 6 Backups
  // deliverable), connecting PBS *is* attaching a storage of type pbs, so it
  // reuses this form rather than growing a second, near-identical one.
  // Editing keeps whatever Proxmox reported, including nothing: `?? defaultType`
  // turned "this datastore reports no type" into a confident "dir".
  const [type, setType] = useState<string>(existing ? existing.type ?? '' : defaultType)
  const [cfg, setCfg] = useState<Record<string, string>>({
    content: existing?.content.join(',') ?? '',
  })
  const set = (k: string, v: string) => setCfg((s) => ({ ...s, [k]: v }))

  const fields: [string, string, string][] = [
    ...(FIELDS[type] ?? []), ['content', 'Content', 'text'],
  ]
  // Blank means "not supplied", on edit that is how a password stays
  // unchanged, and on attach it is how an optional plugin key is omitted.
  const filled = Object.fromEntries(
    fields.map(([k]) => [k, (cfg[k] ?? '').trim()]).filter(([, v]) => v !== ''),
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

    {/* doc 06 §e rule 1: never hide a gated feature, veil it. The Close
        button below sits OUTSIDE the veil, because LockVeil sets
        pointer-events:none on its children and a dialog you cannot dismiss
        is a worse bug than the one being gated. */}
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
            onChange={(e) => setType(e.target.value)}>
            {TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
            {/* TYPES is the four plugins this form can ATTACH. Edit opens on
                ANY row the Storage page lists, and a real cluster is full of
                lvmthin, zfspool and rbd, none of which is here. With no
                option matching, the browser selects the first one instead, so
                editing local-lvm read "dir": not a missing answer, a wrong one
                about a datastore the caller already knew the type of. Same
                escape hatch NicForm.tsx keeps for a bridge the node no longer
                reports. */}
            {!TYPES.some((t) => t === type) &&
              <option value={type}>{type === '' ? 'unknown' : type}</option>}
          </select>
        </div>
        {fields.map(([k, label, inputType]) => (
          <div key={k}>
            <label htmlFor={`sf-${k}`}
              className="mb-1 block text-[11px] uppercase tracking-wide text-text-3">{label}</label>
            <input id={`sf-${k}`} className={inputCls} type={inputType}
              value={cfg[k] ?? ''} onChange={(e) => set(k, e.target.value)}
              placeholder={k === 'content' ? 'iso,vztmpl,backup' : ''} />
          </div>
        ))}
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
