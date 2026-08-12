import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, ApiError } from '../api/client'
import { notify } from '../lib/notify'
import { ConfirmSelfDialog } from './ConfirmSelfDialog'
import { JobLog } from './JobLog'
import { Button } from './ui/button'
import { Dialog } from './ui/dialog'

type PowerResult = { job: { id: number; kind: string; status: string }; is_self: boolean }

const detailOf = (e: unknown) =>
  e instanceof ApiError && typeof (e.body as any)?.detail === 'string'
    ? (e.body as any).detail : 'Could not reach that node, try again.'

/**
 * Reboot / power off ONE Proxmox node (backend/proxploy/api/hosts.py
 * `power_node`), doc 02 §9 and doc 08 §1/§9 row 14.
 *
 * Always the typed-confirmation gate, self or not -- a plain "are you sure"
 * is not enough for an action that can take a whole node, and every guest on
 * it, down. `is_self` comes off the SAME `.../status` query the identity rail
 * already fetches, so this reads it from cache (or fetches it once, if the
 * rail has not yet) rather than adding a second round trip, and the warning
 * it produces is visible BEFORE Confirm is even reachable -- never only
 * discovered after a rejected call.
 *
 * Reboot/power off run as a job now, not a synchronous call (doc 05 §Jobs):
 * once confirmed, this holds the returned job id and mounts JobLog, the same
 * shape InstallDialog/UninstallDialog use, rather than closing on a bare
 * success toast. There is deliberately no progress ring here: a reboot has
 * no honest percentage (services/guestjobs.py::run_host_power never calls
 * ctx.progress), so the log is the whole story and the job's own SSE event
 * (LiveProvider) is what raises the notification card, this dialog does not
 * also toast on success, that would double it.
 */
export function HostPowerDialog({ hostId, node, command, onClose }: {
  hostId: number
  node: string
  command: 'reboot' | 'shutdown'
  onClose: () => void
}) {
  const qc = useQueryClient()
  const [jobId, setJobId] = useState<number | null>(null)
  const statusQuery = useQuery({
    queryKey: ['hosts', hostId, 'node', node, 'status'],
    queryFn: () => api<{ is_self: boolean }>(`/hosts/${hostId}/nodes/${node}/status`),
    retry: false,
  })
  const isSelf = statusQuery.data?.is_self ?? false
  const verb = command === 'reboot' ? 'Reboot' : 'Power off'

  const power = useMutation({
    mutationFn: (confirm: string) =>
      api<PowerResult>(`/hosts/${hostId}/nodes/${node}/power`, {
        method: 'POST',
        body: JSON.stringify({ command, confirm }),
      }),
    onSuccess: (r) => {
      setJobId(r.job.id)
      qc.invalidateQueries({ queryKey: ['cluster', 'nodes'] })
      qc.invalidateQueries({ queryKey: ['jobs'] })
    },
    onError: (e) => { notify.error('Could not send that action.', { description: detailOf(e) }); onClose() },
  })

  if (jobId != null) {
    return (
      <Dialog title={`${verb} ${node}`} onClose={onClose}>
        <div className="mt-4">
          <JobLog jobId={jobId} />
          <Button className="mt-3" variant="ghost" onClick={onClose}>Close</Button>
        </div>
      </Dialog>
    )
  }

  let detail = `${command === 'reboot' ? 'Rebooting' : 'Powering off'} ${node} `
             + 'cannot be undone once it starts.'
  if (isSelf) {
    detail += ` ${node} is the node Proxploy itself runs on: this can end `
            + 'Proxploy with no in-band way back, recovery would need '
            + 'physical or IPMI access to the machine.'
  }

  return (
    <ConfirmSelfDialog
      title={`${verb} ${node}?`}
      phrase={node}
      detail={detail}
      onCancel={onClose}
      onConfirm={(typed) => power.mutate(typed)}
    />
  )
}
