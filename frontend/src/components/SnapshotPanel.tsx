import { useState } from 'react'
import { toast } from 'sonner'
import { ApiError } from '../api/client'
import { useEntitlements } from '../api/hooks'
import { useSnapshotAction, useSnapshots } from '../api/snapshots'
import type { SnapshotRow } from '../api/snapshots'
import { ConfirmSelfDialog } from './ConfirmSelfDialog'
import { EmptyState } from './EmptyState'
import { inputCls } from './LoginForm'
import { Button } from './ui/button'
import { fmtBytes } from '../lib/format'

const card = 'rounded-card border border-line-soft bg-panel p-5'

type Guard = { phrase: string; detail: string; name: string }

const ROLLBACK_DETAIL =
  'Rolling back discards every change made since the snapshot was taken.'

/** Unix seconds → "YYYY-MM-DD HH:MM" in UTC. Deterministic, unlike toLocaleString. */
function fmtWhen(t: number | null | undefined): string {
  if (!t) return 'unknown'
  return new Date(t * 1000).toISOString().replace('T', ' ').slice(0, 16)
}

/**
 * Doc 06 §(a) row 48: "Snapshots: table (Name/Created/Size) with Rollback +
 * Delete row actions and 'Take snapshot'". The with-RAM (vmstate) checkbox is
 * doc 01 §4's "with-RAM option surfaced".
 *
 * This panel only ever mounts under /vms/$vmId, i.e. qemu guests, which is why
 * the vmstate checkbox is unconditional, PVE rejects vmstate for LXC, so an
 * LXC consumer would have to hide it before reusing this component.
 */
export function SnapshotPanel({ vmId, vmName }: { vmId: number; vmName: string }) {
  const ent = useEntitlements()
  const { data, isError } = useSnapshots(vmId)
  const run = useSnapshotAction()
  const [guard, setGuard] = useState<Guard | null>(null)
  const [name, setName] = useState('')
  const [desc, setDesc] = useState('')
  const [withRam, setWithRam] = useState(false)

  // useEntitlements().has() is false until /entitlements resolves, gate on
  // ent.data != null too or every plan sees a dead panel during the first fetch.
  const denied = ent.data != null && !ent.has('vms.snapshots')
  const planTitle = denied ? 'Not included in your plan' : undefined

  // PVE's list carries a synthetic `current` row describing the live state; it
  // is not a snapshot and cannot be rolled back to or deleted.
  const rows: SnapshotRow[] = (data ?? []).filter((s) => s.name !== 'current')

  const fire = (op: 'create' | 'rollback' | 'delete', target: string, confirm?: string) =>
    run.mutate(
      { vmId, op, name: target, description: desc, vmstate: withRam, confirm },
      {
        onError: (e) => {
          const body = e instanceof ApiError ? (e.body as Record<string, unknown>) : null
          if (body?.error === 'confirm_required' || body?.error === 'self_target') {
            setGuard({
              phrase: String(body.confirm_phrase ?? vmName),
              detail: String(body.detail ?? ROLLBACK_DETAIL),
              name: target,
            })
            return
          }
          toast.error(`Could not ${op} snapshot "${target}"`)
        },
        onSuccess: () => {
          setGuard(null)
          if (op === 'create') { setName(''); setDesc(''); setWithRam(false) }
          toast.success(`Snapshot ${op} queued`)
        },
      },
    )

  const removeSnapshot = (s: SnapshotRow) => {
    // Destructive but not self-targeted, so the settings.tsx precedent applies:
    // native window.confirm, not a second bespoke typed-confirmation dialog.
    if (window.confirm(`Delete snapshot "${s.name}"? This cannot be undone.`)) {
      fire('delete', s.name)
    }
  }

  if (isError) {
    return <EmptyState title="Snapshots not available"
      note="Proxploy could not read this VM's snapshot list from Proxmox. Check the host connection." />
  }

  return (
    <>
      <div className={card}>
        <h2 className="mb-3 text-[13px] uppercase text-text-3">Take snapshot</h2>
        <form
          className="flex flex-wrap items-end gap-3"
          onSubmit={(e) => { e.preventDefault(); fire('create', name.trim()) }}
        >
          <div className="w-[200px]">
            <label htmlFor="snap-name" className="mb-1 block text-[11px] uppercase tracking-wide text-text-3">
              Snapshot name
            </label>
            <input id="snap-name" className={inputCls} value={name} placeholder="pre-upgrade"
              onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="w-[260px]">
            <label htmlFor="snap-desc" className="mb-1 block text-[11px] uppercase tracking-wide text-text-3">
              Description (optional)
            </label>
            <input id="snap-desc" className={inputCls} value={desc}
              onChange={(e) => setDesc(e.target.value)} />
          </div>
          <label htmlFor="snap-ram" className="flex items-center gap-2 pb-2 text-[13px] text-text-2">
            <input id="snap-ram" type="checkbox" checked={withRam}
              onChange={(e) => setWithRam(e.target.checked)} />
            Include RAM (vmstate)
          </label>
          <Button type="submit" className="mb-0.5" disabled={denied || run.isPending || name.trim() === ''}
            title={planTitle}>
            Take snapshot
          </Button>
        </form>
        <p className="mt-2 text-[12px] text-text-3">
          Including RAM captures the running state so a rollback resumes mid-boot,
          but writes the whole memory allocation to disk and briefly pauses the guest.
        </p>
      </div>

      <div className={`${card} mt-4`}>
        {rows.length === 0 ? (
          <EmptyState title="No snapshots" note="Snapshots taken here and in Proxmox both show up in this list." />
        ) : (
          <table className="w-full text-left text-[13px]">
            <thead>
              <tr className="text-[11px] uppercase text-text-3">
                <th scope="col" className="pb-2 font-medium">Name</th>
                <th scope="col" className="pb-2 font-medium">Created</th>
                <th scope="col" className="pb-2 font-medium">Size</th>
                <th scope="col" className="pb-2 font-medium"></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((s) => (
                <tr key={s.name} className="border-t border-line-soft hover:bg-panel-2">
                  <td className="py-2.5 font-mono">
                    {s.name}
                    {s.vmstate && (
                      <span className="ml-2 rounded-full border border-amber/30 bg-amber-dim px-1.5 py-0.5 font-mono text-[9.5px] text-amber">
                        RAM
                      </span>
                    )}
                    {s.description && (
                      <div className="font-ui text-[11.5px] text-text-3">{s.description}</div>
                    )}
                  </td>
                  <td className="py-2.5 font-mono text-text-2">{fmtWhen(s.snaptime)}</td>
                  <td className="py-2.5 font-mono text-text-2"
                    title={s.size_bytes == null ? 'Proxmox does not report a size for this storage plugin' : undefined}>
                    {s.size_bytes == null ? 'unknown' : fmtBytes(s.size_bytes)}
                  </td>
                  <td className="flex items-center gap-2 py-2.5">
                    <Button variant="go" className="px-2 py-1 text-[11px]"
                      disabled={denied || run.isPending} title={planTitle}
                      onClick={() => fire('rollback', s.name)}>
                      Rollback
                    </Button>
                    <Button variant="danger" className="px-2 py-1 text-[11px]"
                      disabled={denied || run.isPending} title={planTitle}
                      onClick={() => removeSnapshot(s)}>
                      Delete
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {guard && (
        <ConfirmSelfDialog
          phrase={guard.phrase}
          detail={guard.detail}
          onCancel={() => setGuard(null)}
          onConfirm={(typed) => fire('rollback', guard.name, typed)}
        />
      )}
    </>
  )
}
