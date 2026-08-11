import { useState } from 'react'
import type { BackupRow } from '../api/backups'
import { useRestoreBackup } from '../api/backups'
// One 409 unwrapper for the whole phase; it landed with the network page.
import { errBody } from '../api/network'
import { ConfirmSelfDialog } from './ConfirmSelfDialog'
import { JobLog } from './JobLog'
import { Button } from './ui/button'
import { fmtBytes } from '../lib/format'
import { Dialog } from './ui/dialog'

/**
 * Restore one archive, in place or as a new guest (doc 01 §7).
 *
 * Three 409 shapes reach this dialog and they are NOT interchangeable:
 *  - `confirm_required`: an in-place restore over another guest. Confirmable:
 *    re-POST with the typed name.
 *  - `self_target`: an in-place restore over the CT Proxploy itself runs in.
 *    Refused unconditionally by api/backups.py; `confirm` does not bypass it and
 *    re-POSTing returns the identical 409. Show the reason, offer nothing.
 *  - `guest_running` / `guest_missing`, same treatment: state the reason.
 */
export function RestoreDialog({ backup, onClose }: {
  backup: BackupRow; onClose: () => void
}) {
  const restore = useRestoreBackup()
  const [mode, setMode] = useState<'new' | 'in_place'>('new')
  const [guard, setGuard] = useState<{ phrase: string; detail: string } | null>(null)
  const [refusal, setRefusal] = useState('')
  const [jobId, setJobId] = useState<number | null>(null)
  const name = backup.guest_name ?? `${backup.guest_type ?? 'guest'} ${backup.guest_vmid ?? ''}`

  const fire = (confirm?: string) => {
    setRefusal('')
    restore.mutate({ id: backup.id, mode, confirm }, {
      onSuccess: (r) => { setGuard(null); setJobId(r.job.id) },
      onError: (e) => {
        const b = errBody(e)
        if (b?.error === 'confirm_required') {
          setGuard({ phrase: String(b.confirm_phrase ?? name), detail: String(b.detail ?? '') })
          return
        }
        setGuard(null)
        setRefusal(String(b?.detail ?? 'Could not start the restore, try again.'))
      },
    })
  }

  return (
    <>
      <Dialog title={<>Restore {name}</>} width={480} onClose={onClose}>
      <div className="mt-2 rounded-ctl border border-line-soft bg-elev p-2 font-mono text-[11px] text-text-3">
        <div className="break-all">{backup.volid}</div>
        <div className="mt-1">
          {fmtBytes(backup.size_bytes)} · {backup.verify_state ?? 'unverified'}
        </div>
      </div>

      {jobId != null ? (
        <div className="mt-4">
          <JobLog jobId={jobId} />
          <Button className="mt-3" variant="ghost" onClick={onClose}>Close</Button>
        </div>
      ) : (
        <>
          <div className="mt-4 space-y-3">
            <label className="flex gap-2 text-[13px] text-text-2">
              <input type="radio" name="restore-mode" checked={mode === 'new'}
                     onChange={() => setMode('new')} />
              <span>
                <span className="text-text">As a new guest</span>
                <span className="block text-[12px] text-text-3">
                  Proxmox takes the next free CTID/VMID. Nothing existing is touched.
                </span>
              </span>
            </label>
            <label className="flex gap-2 text-[13px] text-text-2">
              <input type="radio" name="restore-mode" checked={mode === 'in_place'}
                     onChange={() => setMode('in_place')} />
              <span>
                <span className="text-text">In place</span>
                <span className="block text-[12px] text-text-3">
                  Overwrites {name} ({backup.guest_vmid}) with this archive. The guest must
                  be stopped, and its current disk is replaced.
                </span>
              </span>
            </label>
          </div>

          {refusal && (
            <p className="mt-3 rounded-ctl border border-red/30 bg-red-dim p-2 text-[12.5px] text-text-2">
              {refusal}
            </p>
          )}

          <div className="mt-4 flex justify-end gap-2">
            <Button variant="ghost" onClick={onClose}>Cancel</Button>
            <Button variant={mode === 'in_place' ? 'danger' : 'primary'}
                    disabled={restore.isPending} onClick={() => fire()}>
              {restore.isPending ? 'Starting…' : 'Start restore'}
            </Button>
          </div>
        </>
      )}
      </Dialog>

      {guard && (
        <ConfirmSelfDialog
          title={`Overwrite ${guard.phrase}`}
          phrase={guard.phrase}
          detail={guard.detail}
          onConfirm={(typed) => fire(typed)}
          onCancel={() => setGuard(null)} />
      )}
    </>
  )
}
