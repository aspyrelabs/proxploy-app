import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate } from '@tanstack/react-router'
import { api } from '../api/client'
import type { AppRow } from '../api/hooks'
import type { JobRow } from '../api/jobs'
import { errBody } from '../api/network'
import { ConfirmSelfDialog } from './ConfirmSelfDialog'
import { JobLog } from './JobLog'
import { AlertDialog, AlertDialogCancel } from './ui/alert-dialog'
import { Button } from './ui/button'

type UninstallResult = { job: JobRow } | { removed: true; ct_kept: true }

/**
 * DELETE /apps/{id} has two outcomes that must never be confused: destroy the
 * CT and its disk (irreversible, typed-confirm gated, async: a job) or forget
 * the app and leave the CT running on PVE untouched (synchronous, no confirm,
 * reversible via re-adopt). Copy keeps the two blocks visually separate
 * rather than one form with a checkbox, so a misclick can't silently switch
 * outcomes.
 */
export function UninstallDialog({ app, onClose }: { app: AppRow; onClose: () => void }) {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [phrase, setPhrase] = useState(app.name)
  const [detail, setDetail] = useState(
    `Uninstalling ${app.name} destroys CT ${app.ctid} and its disk. This cannot be undone.`)
  const [guardOpen, setGuardOpen] = useState(false)
  const [error, setError] = useState('')
  const [jobId, setJobId] = useState<number | null>(null)

  const remove = useMutation<UninstallResult, unknown, { confirm?: string; keep_ct?: boolean }>({
    mutationFn: (body) => api<UninstallResult>(`/apps/${app.id}`, {
      method: 'DELETE', body: JSON.stringify(body),
    }),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ['apps'] })
      qc.invalidateQueries({ queryKey: ['jobs'] })
    },
  })

  const doDestroy = (typed: string) => {
    setError('')
    remove.mutate({ confirm: typed }, {
      onSuccess: (r) => {
        if ('job' in r) {
          setGuardOpen(false)
          setJobId(r.job.id)
          return
        }
        setGuardOpen(false)
        navigate({ to: '/apps' as never })
        onClose()
      },
      // Defensive: the typed confirm already forces `confirm === phrase`
      // client-side, but the app can be renamed by someone else between
      // opening this dialog and clicking Confirm, so the server's 409 is
      // still handled rather than assumed unreachable. Refresh the phrase
      // from the response and let the operator retype against the real name.
      onError: (e) => {
        const b = errBody(e)
        if (b?.error === 'confirm_required') {
          setGuardOpen(false)
          setPhrase(String(b.confirm_phrase ?? app.name))
          setDetail(String(b.detail ?? detail))
          setError('The app name changed, retype it to confirm.')
          return
        }
        setGuardOpen(false)
        setError('Could not uninstall the app, try again.')
      },
    })
  }

  const doForget = () => {
    setError('')
    remove.mutate({ keep_ct: true }, {
      onSuccess: () => {
        navigate({ to: '/apps' as never })
        onClose()
      },
      onError: () => setError('Could not forget the app, try again.'),
    })
  }

  const closeJob = () => {
    navigate({ to: '/apps' as never })
    onClose()
  }

  return (
    <>
      {/* Wide once the transcript replaces the question, the same 60% the
          install dialog takes and for the same reason: a terminal that wraps
          mid-line hides the part worth reading. max() keeps it from ever being
          NARROWER than the 420 the question is asked at. */}
      <AlertDialog
        width={jobId != null ? 'max(420px, 60vw)' : undefined}
        title={<>Uninstall <span className="font-mono">{app.name}</span></>}
        description={`Destroy CT ${app.ctid} and its disk, or stop tracking it and leave it `
          + 'running. Destroying asks you to type the name first.'}
        onCancel={onClose}
      >

      {jobId != null ? (
        <div className="mt-4">
          <JobLog jobId={jobId} />
          <Button className="mt-3" variant="ghost" onClick={closeJob}>Close</Button>
        </div>
      ) : (
        <>
          <div className="mt-4 space-y-3">
            <div className="rounded-ctl border border-red/30 bg-red-dim p-3">
              <h3 className="text-[13px] font-semibold text-red">Destroy the container</h3>
              <p className="mt-1 text-[12.5px] text-text-2">
                Permanently deletes CT {app.ctid} and its disk from {app.host_name}.
                This cannot be undone. Requires typing the app's name to confirm.
              </p>
              <Button className="mt-2" variant="danger" disabled={remove.isPending}
                      onClick={() => setGuardOpen(true)}>
                Destroy container…
              </Button>
            </div>
            <div className="rounded-ctl border border-line-soft bg-elev p-3">
              <h3 className="text-[13px] font-semibold text-text">Forget only</h3>
              <p className="mt-1 text-[12.5px] text-text-2">
                Stops Proxploy tracking {app.name}. CT {app.ctid} keeps running on{' '}
                {app.host_name}, untouched. Nothing is destroyed, and it can be adopted
                again later. No confirmation needed.
              </p>
              <Button className="mt-2" variant="ghost" disabled={remove.isPending}
                      onClick={doForget}>
                Forget, keep container running
              </Button>
            </div>
            {error && <p className="text-[12.5px] text-red">{error}</p>}
          </div>
          <div className="mt-4 flex justify-end">
            <AlertDialogCancel onClick={onClose}>Cancel</AlertDialogCancel>
          </div>
        </>
      )}
      </AlertDialog>

      {guardOpen && (
        <ConfirmSelfDialog
          title={`Destroy ${app.name}`}
          phrase={phrase}
          detail={detail}
          onConfirm={doDestroy}
          onCancel={() => setGuardOpen(false)}
        />
      )}
    </>
  )
}
