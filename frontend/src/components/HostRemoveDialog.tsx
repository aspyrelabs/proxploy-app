import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api, ApiError, apiErrorDetail } from '../api/client'
import { notify } from '../lib/notify'
import { ConfirmSelfDialog } from './ConfirmSelfDialog'
import { AlertDialog, AlertDialogAction, AlertDialogCancel } from './ui/alert-dialog'

type RemoveResult = { removed: true; forgot_apps: number; was_own_host: boolean }
type ConflictApp = { id: number; name: string; ctid: number }

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
      if (r.forgot_apps) {
        notify.success(`${hostName} removed.`,
          { description: `${r.forgot_apps} app record(s) forgotten (containers left running).` })
      } else {
        notify.success(`${hostName} removed.`)
      }
      qc.invalidateQueries({ queryKey: ['hosts'] })
      qc.invalidateQueries({ queryKey: ['apps'] })
      qc.invalidateQueries({ queryKey: ['vms'] })
      // The ['cluster'] prefix, not ['cluster','nodes'] alone: removing a host
      // takes its nodes, its summary counts and its activity with it. The
      // footer that counts nodes is mounted on every page including this one,
      // so leaving it stale meant the sidebar kept counting a host that is
      // gone, and could keep calling it unreachable, for up to 30s.
      qc.invalidateQueries({ queryKey: ['cluster'] })
      onRemoved()
    },
    onError: (e, vars) => {
      if (e instanceof ApiError && e.status === 409 && (e.body as any)?.error === 'host_has_apps') {
        setConflictApps((e.body as any).apps ?? [])
        setTyped(vars.confirm)
        return
      }
      notify.error(apiErrorDetail(e, 'Could not remove that host, try again.'))
      onClose()
    },
  })

  if (conflictApps) {
    return (
      <AlertDialog
        title={`${hostName} still has apps`}
        description={"Uninstall them first, or forget Proxploy's records for them and leave the "
          + 'containers running.'}
        onCancel={onClose}
      >
        <ul className="mt-3 max-h-40 space-y-1 overflow-auto font-mono text-[12px] text-text-2">
          {conflictApps.map((a) => <li key={a.id}>{a.name} (CT {a.ctid})</li>)}
        </ul>
        <div className="mt-4 flex justify-end gap-2">
          <AlertDialogCancel onClick={onClose}>Cancel</AlertDialogCancel>
          <AlertDialogAction disabled={remove.isPending}
            onClick={() => remove.mutate({ confirm: typed as string, forgetApps: true })}>
            {remove.isPending ? 'Removing…' : 'Forget apps and remove'}
          </AlertDialogAction>
        </div>
      </AlertDialog>
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
