import { useState } from 'react'
import * as DropdownMenu from '@radix-ui/react-dropdown-menu'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useVmLifecycleGate } from '../api/app-gates'
import { api, ApiError, apiErrorDetail } from '../api/client'
import { useEntitlements, type VmRow } from '../api/hooks'
import type { JobRow } from '../api/jobs'
import { useLifecycle } from '../api/jobs'
import { notify } from '../lib/notify'
import { BackupGuestDialog } from './BackupGuestDialog'
import { CloneDialog } from './CloneDialog'
import { ConfirmSelfDialog } from './ConfirmSelfDialog'
import { JobLog } from './JobLog'
import { VmOptionsDialog } from './VmOptionsDialog'
import { Button } from './ui/button'
import { Dialog } from './ui/dialog'
import { Icon } from './ui/icon'

const itemCls = 'flex cursor-pointer items-center gap-2 px-3 py-2 text-[13px] text-text-2 '
             + 'outline-none data-[highlighted]:bg-panel-2 data-[highlighted]:text-text '
             + 'data-[disabled]:cursor-not-allowed data-[disabled]:opacity-50'
// The destructive vocabulary AppIconMenu and HostActionsMenu already use:
// text-red/bg-red-dim tokens, never a literal hex
// (src/tests/no-hardcoded-colors.test.ts). The border-t IS the separator that
// keeps Delete off the end of the ordinary list.
const destructiveItemCls = 'flex cursor-pointer items-center gap-2 border-t border-line-soft '
                         + 'px-3 py-2 text-[13px] text-red outline-none data-[highlighted]:bg-red-dim '
                         + 'data-[disabled]:cursor-not-allowed data-[disabled]:opacity-50'

const NOT_IN_PLAN = 'Not included in your plan'

type Guard = { phrase: string; detail: string; action: string }
type Panel = 'clone' | 'backup' | 'destroy' | 'options' | null

/**
 * One VM's actions as a menu, the three-dots half of VmActionBar.
 *
 * AppIconMenu's opposite number, and the differences are all things the two
 * kinds of guest genuinely do not share:
 *
 *  - No Open and no Logs. A VM has no catalog port to point a tab at, and
 *    Proxploy reads no journal from inside a QEMU guest.
 *  - No Console either, and that one is not a gap. It is the only way into a
 *    VM at all, so it took the row's third button slot, the one an app spends
 *    on Open (VmActionBar). Repeating it here would offer the same action
 *    twice, one click apart.
 *  - Shutdown, Pause and Resume are here. services/lifecycle.py's VM_ACTIONS
 *    already accepts all three (`pause` is Proxmox's `suspend`, mapped there
 *    and nowhere else), and the row's buttons only carry Start, Stop and
 *    Restart, so without these there was no way to reach them at all.
 *  - Clone replaces Reconfigure and Migrate, which are app-shaped operations.
 *
 * Pause is offered only while the VM is running and Resume only while it is
 * paused, rather than both being present and one of them failing: "paused" is
 * the exact string the row carries in that state, written by the poller from
 * PVE's own status field and by services/lifecycle.py's RESULT_STATUS when a
 * pause finishes.
 *
 * Lifecycle actions route through the same `useLifecycle` mutation
 * LifecycleActions.fire uses, error handling included: a 409 self_target
 * escalates to ConfirmSelfDialog, and everything else surfaces a notify.error
 * toast rather than letting the optimistic "pending" patch revert in silence.
 */
export function VmActionsMenu({ vm, children }: {
  vm: VmRow
  children: React.ReactNode
}) {
  const lifecycleGate = useVmLifecycleGate(vm.host_id)
  const ent = useEntitlements()
  const run = useLifecycle()
  const [guard, setGuard] = useState<Guard | null>(null)
  const [panel, setPanel] = useState<Panel>(null)
  const pending = vm.status === 'pending' || run.isPending

  // Same wait-for-first-fetch rule as api/app-gates.ts's "innocent until
  // proven guilty": has() reads false until /entitlements lands, so gating on
  // it directly would grey these out on every plan for the whole first fetch.
  const planDenied = (flag: string) => ent.data != null && !ent.has(flag)
  const cloneDenied = planDenied('vms.clone')
  const backupDenied = planDenied('backups.run')
  // Destroying a VM is gated on the same flag that creates one: the plan that
  // may not make VMs may not unmake them either. This is what the detail
  // page's Destroy button read before it was folded in here.
  const destroyDenied = planDenied('vms.create')
  const running = vm.status === 'running'

  const fire = (action: string, confirm?: string) =>
    run.mutate({ target: 'vm', id: vm.id, action, confirm }, {
      onError: (e) => {
        const body = e instanceof ApiError ? (e.body as Record<string, unknown>) : null
        if (body?.error === 'self_target') {
          setGuard({ phrase: String(body.confirm_phrase ?? vm.name),
                     detail: String(body.detail ?? ''), action })
          return
        }
        notify.error(`Could not ${action} ${vm.name}.`,
                     { description: apiErrorDetail(e, 'No reason was given, try again.') })
      },
      onSuccess: () => setGuard(null),
    })

  return (
    <>
      <DropdownMenu.Root>
        <DropdownMenu.Trigger asChild>{children}</DropdownMenu.Trigger>
        <DropdownMenu.Portal>
          <DropdownMenu.Content align="start" sideOffset={6}
            className="z-50 w-44 overflow-hidden rounded-card border border-line bg-panel
                       shadow-[0_12px_32px_rgba(0,0,0,.35)]">
            {/* Shutdown, not another Stop: the row's Stop button is the hard
                kill, this is the graceful one PVE distinguishes it from
                (services/lifecycle.py). Icon names are STRING LITERALS here:
                scripts/icon-names.mjs statically scans src/ to build the
                Google Fonts icon_names parameter, and a name it cannot read
                out of the source ships a font subset without that glyph, so
                the browser renders the literal word. */}
            <DropdownMenu.Item className={itemCls}
              disabled={pending || lifecycleGate.denied} title={lifecycleGate.reason}
              onSelect={() => fire('shutdown')}>
              <Icon name="power_settings_new" size={16} /> Shutdown
            </DropdownMenu.Item>
            {running && (
              <DropdownMenu.Item className={itemCls}
                disabled={pending || lifecycleGate.denied} title={lifecycleGate.reason}
                onSelect={() => fire('pause')}>
                <Icon name="pause" size={16} /> Pause
              </DropdownMenu.Item>
            )}
            {vm.status === 'paused' && (
              <DropdownMenu.Item className={itemCls}
                disabled={pending || lifecycleGate.denied} title={lifecycleGate.reason}
                onSelect={() => fire('resume')}>
                <Icon name="play_arrow" size={16} /> Resume
              </DropdownMenu.Item>
            )}
            {/* No plan gate: reading and editing a VM's own settings is not a
                metered capability, unlike cloning or backing one up. */}
            <DropdownMenu.Item className={itemCls}
              onSelect={() => setPanel('options')}>
              <Icon name="tune" size={16} /> Options
            </DropdownMenu.Item>
            <DropdownMenu.Item className={itemCls}
              disabled={cloneDenied} title={cloneDenied ? NOT_IN_PLAN : undefined}
              onSelect={() => setPanel('clone')}>
              <Icon name="content_copy" size={16} /> Clone
            </DropdownMenu.Item>
            <DropdownMenu.Item className={itemCls}
              disabled={backupDenied} title={backupDenied ? NOT_IN_PLAN : undefined}
              onSelect={() => setPanel('backup')}>
              <Icon name="backup" size={16} /> Backup
            </DropdownMenu.Item>
            {/* A running VM cannot be destroyed, and the reason says which
                thing to do first rather than leaving a dead item to guess at.
                The backend refuses it too; this is the near half of that. */}
            <DropdownMenu.Item className={destructiveItemCls}
              disabled={running || destroyDenied}
              title={running ? `Stop ${vm.name} before destroying it`
                     : destroyDenied ? NOT_IN_PLAN : undefined}
              onSelect={() => setPanel('destroy')}>
              <Icon name="delete" size={16} /> Delete
            </DropdownMenu.Item>
          </DropdownMenu.Content>
        </DropdownMenu.Portal>
      </DropdownMenu.Root>
      {guard && (
        <ConfirmSelfDialog
          phrase={guard.phrase}
          detail={guard.detail}
          onCancel={() => setGuard(null)}
          onConfirm={(typed) => fire(guard.action, typed)}
        />
      )}
      {panel === 'options' && <VmOptionsDialog vm={vm} onClose={() => setPanel(null)} />}
      {panel === 'clone' && <CloneDialog vm={vm} onClose={() => setPanel(null)} />}
      {panel === 'backup' && (
        <BackupGuestDialog
          guest={{ type: 'vm', id: vm.id, name: vm.name, hostId: vm.host_id,
                   hostName: vm.host_name, label: `VM ${vm.vmid}` }}
          onClose={() => setPanel(null)}
        />
      )}
      {panel === 'destroy' && <DestroyVm vm={vm} onClose={() => setPanel(null)} />}
    </>
  )
}

/**
 * DELETE /vms/{id}. The single most destructive route in the product.
 *
 * It used to be a button on the VM's own detail page, on the reasoning that a
 * list row was too easy a place to slip. That page is gone, and the slip is
 * covered where it matters: this opens with a typed confirmation of the VM
 * name (ConfirmSelfDialog) and destroys nothing until that name is typed, so
 * a mis-click lands on a dialog rather than on a deleted disk. A second
 * confirm in front of it would only train the operator to click through both.
 *
 * A running guest is refused up front (the menu item is disabled with the
 * reason visible) and the backend's own 409 detail is what shows if that state
 * changed underneath us anyway, never a generic failure toast.
 */
function DestroyVm({ vm, onClose }: { vm: VmRow; onClose: () => void }) {
  const qc = useQueryClient()
  const [jobId, setJobId] = useState<number | null>(null)

  const destroy = useMutation<{ job: JobRow }, ApiError, string>({
    mutationFn: (confirm) => api<{ job: JobRow }>(`/vms/${vm.id}`, {
      method: 'DELETE',
      body: JSON.stringify({ confirm }),
    }),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ['jobs'] })
      qc.invalidateQueries({ queryKey: ['cluster', 'activity'] })
      qc.invalidateQueries({ queryKey: ['vms'] })
    },
  })

  const submit = (typed: string) => {
    destroy.mutate(typed, {
      onSuccess: (r) => setJobId(r.job.id),
      onError: (e) => {
        const body = e instanceof ApiError ? (e.body as Record<string, unknown>) : null
        // guest_running/confirm_required races (the VM's state changed between
        // opening the dialog and confirming) get the backend's own sentence
        // verbatim; self_target is restated plainly rather than assuming its
        // wording, is_self() is always false today so the real string is
        // untested here.
        const msg = body?.error === 'self_target'
          ? 'Proxploy will not destroy the guest it is running inside.'
          : apiErrorDetail(e, 'Could not destroy that VM, try again.')
        notify.error(msg)
      },
    })
  }

  // Closing the job log needs no navigation any more: the table this was
  // opened from is already the page, and the invalidation above is what drops
  // the destroyed row out of it.
  if (jobId != null) {
    return (
      <Dialog title={<>Destroying <span className="font-mono">{vm.name}</span></>}
              width={480} onClose={onClose}>
        <div className="mt-4"><JobLog jobId={jobId} /></div>
        <Button className="mt-3" variant="ghost" onClick={onClose}>Close</Button>
      </Dialog>
    )
  }
  return (
    <ConfirmSelfDialog
      title="Destroy this VM"
      phrase={vm.name}
      detail={`Destroying ${vm.name} deletes the VM and every disk attached to it. ` +
              'There is no undo and no automatic backup. Type the VM name to confirm.'}
      onCancel={onClose}
      onConfirm={submit}
    />
  )
}
