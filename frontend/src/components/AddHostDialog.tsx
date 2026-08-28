import { Dialog } from './ui/dialog'
import { HostForm, type HostCreated } from './HostForm'
import { Icon } from './ui/icon'

export function AddHostDialog({ blocked = false, onClose, onCreated }: {
  /** One host is included; a second needs the multi-host plan. Shown instead
   *  of the form, because a 403 at the end of a filled form is the worst
   *  place to learn it. */
  blocked?: boolean
  onClose: () => void
  onCreated: (h: HostCreated) => void
}) {
  return (
    <Dialog width={672} scrollBody onClose={onClose}
      title={
        <span className="flex min-w-0 items-center gap-2.5">
          <span className="grid size-8 shrink-0 place-items-center rounded-tile
                           border border-line bg-panel-2 text-amber">
            <Icon name="dns" size={18} />
          </span>
          <span className="flex min-w-0 flex-col leading-tight">
            <span className="truncate">Add a host</span>
            <span className="truncate font-mono text-[11px] font-normal text-text-3">
              proxmox ve · api token
            </span>
          </span>
        </span>}>
      {blocked ? (
        <div className="mt-4">
          <p className="text-[13px] text-text-2">
            Managing more than one host needs the multi-host plan.
          </p>
          <p className="mt-1 text-[12px] text-text-3">
            One host is included. Every node of that host&rsquo;s cluster is already
            managed here, at no extra tier.
          </p>
        </div>
      ) : (
        <HostForm onCreated={onCreated} />
      )}
    </Dialog>
  )
}
