import { Dialog } from './ui/dialog'
import { HostCapabilityList } from './HostCapabilityList'

/** The four capability tokens for one host. Settings is where the docs tell
 *  operators to add them, and until now it had no control for them at all.
 *  Separate from HostRotateDialog on purpose: that one is monitoring + the
 *  SSH key, and merging the two would put two different rotate paths for the
 *  same token in one card. */
export function HostTokensDialog({ hostId, hostName, onClose }: {
  hostId: number; hostName: string; onClose: () => void
}) {
  return (
    <Dialog title={<>Capability tokens, {hostName}</>} width={440} scrollBody onClose={onClose}>
      <div className="mt-4">
        <HostCapabilityList hostId={hostId} />
      </div>
    </Dialog>
  )
}
