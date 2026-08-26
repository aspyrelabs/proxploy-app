import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, apiErrorDetail } from '../api/client'
import { notify } from '../lib/notify'
import { ConfirmSelfDialog } from './ConfirmSelfDialog'
import { JobLog } from './JobLog'
import { Button } from './ui/button'
import { Dialog } from './ui/dialog'
import { SkeletonGroup, SkeletonLine } from './ui/skeleton'

type PowerResult = { job: { id: number; kind: string; status: string }; is_self: boolean }

/**
 * Reboot or power off ONE Proxmox node via typed confirmation.
 *
 * Runs as a job — once confirmed, this holds the returned job id and mounts
 * JobLog. There is no progress ring: a reboot has no honest percentage
 * (services/guestjobs.py::run_host_power never calls ctx.progress). The job's
 * SSE event (LiveProvider) raises the notification card; this dialog does not
 * also toast on success.
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
    onError: (e) => {
      notify.error('Could not send that action.',
        { description: apiErrorDetail(e, 'Could not reach that node, try again.') })
      onClose()
    },
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

  // Held until /status answers: `isSelf` falls back to false while the query
  // is in flight, so showing the ordinary warning here would let an operator
  // confirm a destructive action against a warning that was still loading.
  // Deliberately NOT defaulting isSelf to true — flashing the scariest warning
  // on every reboot and then taking it away trains people to ignore it.
  if (statusQuery.isPending) {
    return (
      <Dialog title={`${verb} ${node}?`} onClose={onClose}>
        <SkeletonGroup label="Checking whether this is the node Proxploy runs on"
                       className="mt-4 space-y-2">
          <SkeletonLine className="w-full text-[13px]" />
          <SkeletonLine className="w-4/5 text-[13px]" />
        </SkeletonGroup>
        <Button className="mt-3" variant="ghost" onClick={onClose}>Cancel</Button>
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
