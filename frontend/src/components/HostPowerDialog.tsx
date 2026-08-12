import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { api, ApiError } from '../api/client'
import { ConfirmSelfDialog } from './ConfirmSelfDialog'

type PowerResult = { upid: string; is_self: boolean }

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
 */
export function HostPowerDialog({ hostId, node, command, onClose }: {
  hostId: number
  node: string
  command: 'reboot' | 'shutdown'
  onClose: () => void
}) {
  const qc = useQueryClient()
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
    onSuccess: () => {
      toast.success(`${verb === 'Reboot' ? 'Reboot' : 'Power off'} sent to ${node}.`)
      qc.invalidateQueries({ queryKey: ['cluster', 'nodes'] })
      onClose()
    },
    onError: (e) => { toast.error(detailOf(e)); onClose() },
  })

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
