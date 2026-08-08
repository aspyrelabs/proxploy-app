import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { api, ApiError } from '../api/client'
import { ConfirmSelfDialog } from './ConfirmSelfDialog'
import { Button } from './ui/button'

type RemoveResult = { removed: true; forgot_apps: number; was_own_host: boolean }
type ConflictApp = { id: number; name: string; ctid: number }

const detailOf = (e: unknown) =>
  e instanceof ApiError && typeof (e.body as any)?.detail === 'string'
    ? (e.body as any).detail : 'Could not remove that host, try again.'

/**
 * DELETE /hosts/{id} refuses (409 host_has_apps) when apps still reference
 * the host and forget_apps was not set. Rather than silently retrying with
 * forget_apps: true, this shows the apps that stand in the way and makes the
 * user opt in to a second, explicit submit.
 */
export function HostRemoveDialog({ hostId, hostName, onClose, onRemoved }: {
  hostId: number; hostName: string; onClose: () => void; onRemoved: () => void
}) {
  const qc = useQueryClient()
  const [typed, setTyped] = useState<string | null>(null)
  const [conflictApps, setConflictApps] = useState<ConflictApp[] | null>(null)

  const remove = useMutation({
    mutationFn: (vars: { confirm: string; forgetApps: boolean }) =>
      api<RemoveResult>(`/hosts/${hostId}`, {
        method: 'DELETE',
        body: JSON.stringify({ confirm: vars.confirm, forget_apps: vars.forgetApps }),
      }),
    onSuccess: (r) => {
      toast.success(r.forgot_apps
        ? `${hostName} removed, ${r.forgot_apps} app record(s) forgotten (containers left running).`
        : `${hostName} removed.`)
      qc.invalidateQueries({ queryKey: ['hosts'] })
      qc.invalidateQueries({ queryKey: ['apps'] })
      onRemoved()
    },
    onError: (e, vars) => {
      if (e instanceof ApiError && e.status === 409 && (e.body as any)?.error === 'host_has_apps') {
        setConflictApps((e.body as any).apps ?? [])
        setTyped(vars.confirm)
        return
      }
      toast.error(detailOf(e))
      onClose()
    },
  })

  if (conflictApps) {
    return (
      <div role="dialog" aria-label={`${hostName} still has apps`}
           className="fixed inset-0 z-30 grid place-items-center bg-scrim backdrop-blur-[3px]">
        <div className="w-[420px] max-w-[92vw] rounded-card border border-line bg-panel p-5">
          <h2 className="font-display text-[16px] font-semibold text-amber">{hostName} still has apps</h2>
          <p className="mt-2 text-[13px] text-text-2">
            Uninstall them first, or forget Proxploy's records for them and leave the
            containers running.
          </p>
          <ul className="mt-3 max-h-40 space-y-1 overflow-auto font-mono text-[12px] text-text-2">
            {conflictApps.map((a) => <li key={a.id}>{a.name} (CT {a.ctid})</li>)}
          </ul>
          <div className="mt-4 flex justify-end gap-2">
            <Button variant="ghost" onClick={onClose}>Cancel</Button>
            <Button variant="danger" disabled={remove.isPending}
              onClick={() => remove.mutate({ confirm: typed as string, forgetApps: true })}>
              {remove.isPending ? 'Removing…' : 'Forget apps and remove'}
            </Button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <ConfirmSelfDialog
      title={`Remove ${hostName}?`}
      phrase={hostName}
      detail={`Removing ${hostName} deletes its stored API token and SSH key and everything ` +
        'Proxploy has cached about it. The node itself is not touched.'}
      onCancel={onClose}
      onConfirm={(t) => remove.mutate({ confirm: t, forgetApps: false })}
    />
  )
}
