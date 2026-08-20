import { useState } from 'react'
import { ApiError } from '../api/client'
import { useEntitlements } from '../api/hooks'
import { useSnapshotAction, useSnapshots } from '../api/snapshots'
import type { SnapshotRow } from '../api/snapshots'
import { ConfirmSelfDialog } from './ConfirmSelfDialog'
import { EmptyState } from './EmptyState'
import { TakeSnapshotDialog } from './TakeSnapshotDialog'
import { Button } from './ui/button'
import { SkeletonGroup, SkeletonTable } from './ui/skeleton'
import { fmtBytes } from '../lib/format'
import { notify } from '../lib/notify'

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
 * This panel only ever mounts inside a VM's row on /vms, i.e. qemu guests,
 * which is why
 * the vmstate checkbox is unconditional, PVE rejects vmstate for LXC, so an
 * LXC consumer would have to hide it before reusing this component.
 */
export function SnapshotPanel({ vmId, vmName }: { vmId: number; vmName: string }) {
  const ent = useEntitlements()
  const { data, isError, isPending } = useSnapshots(vmId)
  const run = useSnapshotAction()
  const [guard, setGuard] = useState<Guard | null>(null)
  const [taking, setTaking] = useState(false)

  // useEntitlements().has() is false until /entitlements resolves, gate on
  // ent.data != null too or every plan sees a dead panel during the first fetch.
  const denied = ent.data != null && !ent.has('vms.snapshots')
  const planTitle = denied ? 'Not included in your plan' : undefined

  // PVE's list carries a synthetic `current` row describing the live state; it
  // is not a snapshot and cannot be rolled back to or deleted.
  const rows: SnapshotRow[] = (data ?? []).filter((s) => s.name !== 'current')

  // `create` carries the dialog's fields; rollback and delete carry none. They
  // used to read the open form's state whichever op was running, so typing a
  // description and then pressing Rollback sent that description with the
  // rollback. Nothing downstream read it, but it was never true.
  const fire = (
    op: 'create' | 'rollback' | 'delete',
    target: string,
    confirm?: string,
    create?: { description: string; vmstate: boolean },
  ) =>
    run.mutate(
      { vmId, op, name: target, confirm,
        description: create?.description, vmstate: create?.vmstate },
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
          notify.error(`Could not ${op} snapshot "${target}"`)
        },
        onSuccess: () => {
          setGuard(null)
          // The dialog owns the form fields and unmounts with them, so there
          // is nothing to clear here.
          if (op === 'create') setTaking(false)
          notify.success(`Snapshot ${op} queued`)
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
      {/* The panel is a LIST now. Taking a snapshot moved into a dialog behind
          this button: it is an occasional, deliberate act, and the form used to
          sit permanently open above the table, putting three inputs and a
          paragraph of vmstate caveats between the reader and the rollback
          points they came to look at.

          No card of its own here. VmDetailPanel already wraps this in one, and
          two nested cards drew two borders around the same content. */}
      <div className="mb-3 flex items-center justify-between gap-3">
        <h3 className="text-[11px] uppercase tracking-wide text-text-3">Snapshots</h3>
        <Button size="sm" disabled={denied || run.isPending} title={planTitle}
          onClick={() => setTaking(true)}>
          Take snapshot
        </Button>
      </div>

      <div>
        {/* Checked BEFORE `rows.length === 0`, the same ordering BridgesCard
            uses and for the same reason: `data` is undefined until the list
            comes back from PVE, so `rows` is empty during the fetch and this
            card was answering "No snapshots" before anyone had looked. That
            is the wrong answer to give about a VM whose rollback points
            somebody is here to check. */}
        {isPending ? (
          <SkeletonGroup label="Loading snapshots">
            {/* Name, Created, Size, and the Rollback/Delete pair. */}
            <SkeletonTable rows={3} cols={['w-32', 'w-32', 'w-16', 'w-36']} />
          </SkeletonGroup>
        ) : rows.length === 0 ? (
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

      {taking && (
        <TakeSnapshotDialog
          vmName={vmName}
          pending={run.isPending}
          onClose={() => setTaking(false)}
          onSubmit={(v) => fire('create', v.name, undefined,
                                { description: v.description, vmstate: v.vmstate })}
        />
      )}

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
