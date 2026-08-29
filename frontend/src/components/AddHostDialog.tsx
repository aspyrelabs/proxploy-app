import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import { api } from '../api/client'
import { useEntitlements } from '../api/hooks'
import { Dialog } from './ui/dialog'
import { HostForm, type HostCreated } from './HostForm'
import { Icon } from './ui/icon'
import { LockVeil } from './LockVeil'
import { SkeletonField } from './ui/skeleton'

/**
 * One host is included; a second needs the multi-host plan, and the upsell is
 * shown instead of the form because a 403 at the end of a filled form is the
 * worst place to learn it.
 *
 * The gate is decided HERE, not by the caller. It used to be a `blocked` prop
 * defaulting to false, so a caller that forgot it silently got the form: the
 * Hosts page passed it and Settings > Hosts did not, which is exactly the bug
 * that produced. Both routes render this component, so owning the decision
 * here is what makes the two agree and keeps a third caller correct by
 * default.
 *
 * Both reads are innocent until proven guilty, the rule app-gates.ts states:
 * a pending or failed fetch opens the form and leaves the backend the
 * authority, rather than showing an upsell to someone who may well be
 * entitled.
 */
export function AddHostDialog({ onClose, onCreated }: {
  onClose: () => void
  onCreated: (h: HostCreated) => void
}) {
  const ent = useEntitlements()
  const hosts = useQuery({ queryKey: ['hosts'], queryFn: () => api<{ id: number }[]>('/hosts') })
  // Decided ONCE, on the first render where both reads have landed, and never
  // revisited. Re-deriving it every render is wrong in a way only the e2e
  // spec catches: adding the very first host makes the count 1 mid-flow, so a
  // live gate swaps the capability-token step and the peer panel for an upsell
  // the moment POST /hosts succeeds. The dialog is mounted fresh each time it
  // opens, so latching here is per-opening, not for the session.
  const [decided, setDecided] = useState<boolean | null>(null)
  if (decided === null && ent.data != null && hosts.data != null) {
    setDecided(hosts.data.length >= 1 && !ent.has('hosts.multi'))
  }
  const blocked = decided === true
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
          {/* The skeleton is the host FORM's shape, not a table: this dialog
              is where someone came to fill that form in, and the placeholder
              should be the thing they were reaching for. */}
          <LockVeil locked feature="hosts.multi"
            subtitle={'One host is included, and every node of its cluster with it. '
                      + 'A second host is where the multi-host plan starts.'}
            skeleton={<div aria-hidden className="space-y-3 p-1">
              <SkeletonField label="w-16" />
              <SkeletonField label="w-24" />
              <div className="grid grid-cols-2 gap-3">
                <SkeletonField label="w-20" />
                <SkeletonField label="w-20" />
              </div>
            </div>}>
            <></>
          </LockVeil>
        </div>
      ) : (
        <HostForm onCreated={onCreated} />
      )}
    </Dialog>
  )
}
