import { useState } from 'react'
import * as DropdownMenu from '@radix-ui/react-dropdown-menu'
import { useNavigate } from '@tanstack/react-router'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useAppActionGates, useVmLifecycleGate } from '../api/app-gates'
import { api, ApiError, apiErrorDetail } from '../api/client'
import { useEntitlements, useMe, type VmRow } from '../api/hooks'
import type { JobRow } from '../api/jobs'
import { useLifecycle } from '../api/jobs'
import { useSnapshotAction } from '../api/snapshots'
import { openConsoleWindow } from '../lib/console-window'
import { notify } from '../lib/notify'
import { BackupGuestDialog } from './BackupGuestDialog'
import { CloneDialog } from './CloneDialog'
import { ConfirmSelfDialog } from './ConfirmSelfDialog'
import { JobLog } from './JobLog'
import { TakeSnapshotDialog } from './TakeSnapshotDialog'
import { VmCdromDialog } from './VmCdromDialog'
import { VmOptionsDialog } from './VmOptionsDialog'
import { Button } from './ui/button'
import { Dialog } from './ui/dialog'
import { canEditFirewall } from '../routes/firewall'
import { Icon } from './ui/icon'
import type { FeatureKey } from '../api/feature-keys'
const itemCls = 'flex cursor-pointer items-center gap-2 px-3 py-2 text-[13px] text-text-2 '
             + 'outline-none data-[highlighted]:bg-panel-2 data-[highlighted]:text-text '
             + 'data-[disabled]:cursor-not-allowed data-[disabled]:opacity-50'
// The destructive vocabulary AppIconMenu and HostActionsMenu already use:
// text-red/bg-red-dim tokens, never a literal hex. The border-t IS the
// separator that keeps Delete off the end of the ordinary list.
const destructiveItemCls = 'flex cursor-pointer items-center gap-2 border-t border-line-soft '
                         + 'px-3 py-2 text-[13px] text-red outline-none data-[highlighted]:bg-red-dim '
                         + 'data-[disabled]:cursor-not-allowed data-[disabled]:opacity-50'

const NOT_IN_PLAN = 'Not included in your plan'

// Icon names are STRING LITERALS in an `icon:` field, not a computed lookup:
// scripts/icon-names.mjs statically scans src/ to build the Google Fonts
// icon_names parameter, and a name it cannot read out of the source ships a
// font subset without that glyph, so the browser renders the literal word.
//
// Same two tables as AppIconMenu, in the same order.
const RUNNING_ACTIONS = [
  { action: 'stop', label: 'Stop', icon: 'stop' },
  { action: 'restart', label: 'Restart', icon: 'restart_alt' },
] as const
const STOPPED_ACTIONS = [
  { action: 'start', label: 'Start', icon: 'play_arrow' },
] as const

type Guard = { phrase: string; detail: string; action: string }
type Panel = 'clone' | 'backup' | 'destroy' | 'options' | 'cdrom' | 'snapshot' | null

/**
 * One VM's actions as a menu, the three-dots half of VmActionBar.
 *
 * Shutdown, Pause and Resume are here because services/lifecycle.py's
 * VM_ACTIONS accepts all three (`pause` is Proxmox's `suspend`, mapped there
 * and nowhere else) and the row's buttons carry only Start, Stop and Restart.
 * There is no Open and no Logs: a VM has no catalog port and Proxploy reads no
 * journal inside a QEMU guest.
 *
 * `lifecycle` means "this menu is the only affordance", not strictly "power
 * actions": the icon grid takes the default and so gets Console, the ONLY way
 * into a VM at all, while the table row passes false because the bar's buttons
 * sit a centimetre away.
 *
 * EVERY item that acts on a running guest is offered only while it is running,
 * Shutdown included: the backend answers a shutdown on a stopped VM with
 * "already stopped; nothing to do" rather than failing, so the click costs a
 * job row and changes nothing. "paused" and "running" are the exact strings the
 * row carries, from PVE's status field via the poller and from RESULT_STATUS.
 */
export function VmActionsMenu({ vm, lifecycle = true, children }: {
  vm: VmRow
  /** Include Start, or Stop and Restart. On by default, the icon grid's tile
   *  menu, since it is the only way to act on that VM. VmActionBar passes
   *  false: those are buttons beside the menu there. */
  lifecycle?: boolean
  children: React.ReactNode
}) {
  const lifecycleGate = useVmLifecycleGate(vm.host_id)
  const navigate = useNavigate()
  const me = useMe()
  // Innocent until proven guilty, the rule every gate here follows: an
  // unresolved /auth/me withholds nothing, it only changes the title.
  const canEdit = me.data == null || canEditFirewall(me.data.role, 'guest')
  // The console gate is host-shaped, not guest-shaped: it reads the host's
  // console token and no entitlement flag, which is why ConsoleButton reads the
  // same hook. Sharing it keeps the item and the button from disagreeing.
  const consoleGate = useAppActionGates(vm.host_id).console
  const ent = useEntitlements()
  const run = useLifecycle()
  const [guard, setGuard] = useState<Guard | null>(null)
  const [panel, setPanel] = useState<Panel>(null)
  const pending = vm.status === 'pending' || run.isPending

  // Same "innocent until proven guilty" rule: has() reads false until
  // /entitlements lands, so gating on it directly would grey these out on every
  // plan for the whole first fetch.
  const planDenied = (flag: FeatureKey) => ent.data != null && !ent.has(flag)
  const cloneDenied = planDenied('vms.clone')
  const backupDenied = planDenied('backups.run')
  const snapshotDenied = planDenied('vms.snapshots')
  // Destroying a VM is gated on the same flag that creates one: the plan that
  // may not make VMs may not unmake them either.
  const destroyDenied = planDenied('vms.create')
  const running = vm.status === 'running'
  // 'pending' is the optimistic patch useLifecycle writes between the click and
  // the job resolving, not a state PVE reports, so falling through to
  // STOPPED_ACTIONS would draw Start on a VM that is still running. 'paused' is
  // not 'stopped' either: the guest is suspended, not off, so PVE refuses a
  // start and Resume below is the way back.
  const actions = !lifecycle || vm.status === 'pending' || vm.status === 'paused' ? []
    : running ? RUNNING_ACTIONS : STOPPED_ACTIONS

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
            {actions.map((a) => (
              <DropdownMenu.Item key={a.action} className={itemCls}
                disabled={pending || lifecycleGate.denied} title={lifecycleGate.reason}
                onSelect={() => fire(a.action)}>
                <Icon name={a.icon} size={16} /> {a.label}
              </DropdownMenu.Item>
            ))}
            {/* Shutdown, not another Stop: Stop is the hard kill, this is the
                graceful one PVE distinguishes it from. Running only. */}
            {running && (
              <DropdownMenu.Item className={itemCls}
                disabled={pending || lifecycleGate.denied} title={lifecycleGate.reason}
                onSelect={() => fire('shutdown')}>
                <Icon name="power_settings_new" size={16} /> Shutdown
              </DropdownMenu.Item>
            )}
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
            {/* After every power item and before the rest, AppIconMenu's
                order. Only when this menu stands alone: VmActionBar has a
                Console button beside it. */}
            {lifecycle && (
              <DropdownMenu.Item className={itemCls}
                disabled={consoleGate.denied} title={consoleGate.reason}
                onSelect={() => openConsoleWindow('vm', vm.id)}>
                <Icon name="terminal" size={16} /> Console
              </DropdownMenu.Item>
            )}
            {/* No plan gate: reading and editing a VM's own settings is not a
                metered capability, unlike cloning or backing one up. */}
            {/* Outside the `lifecycle` switch, so both surfaces carry it.
                Never gated to a role: it only navigates, and the Firewall page
                itself withholds the edit. */}
            <DropdownMenu.Item className={itemCls}
              title={canEdit ? `Manage ${vm.name}'s firewall`
                             : `View ${vm.name}'s firewall`}
              onSelect={() => navigate({ to: `/firewall/guest/vm/${vm.id}` as never })}>
              <Icon name="shield" size={16} /> Firewall
            </DropdownMenu.Item>
            <DropdownMenu.Item className={itemCls}
              onSelect={() => setPanel('options')}>
              <Icon name="tune" size={16} /> Options
            </DropdownMenu.Item>
            <DropdownMenu.Item className={itemCls}
              onSelect={() => setPanel('cdrom')}>
              <Icon name="album" size={16} /> Mount ISO
            </DropdownMenu.Item>
            <DropdownMenu.Item className={itemCls}
              disabled={snapshotDenied} title={snapshotDenied ? NOT_IN_PLAN : undefined}
              onSelect={() => setPanel('snapshot')}>
              <Icon name="photo_camera" size={16} /> Take snapshot
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
                thing to do first. The backend refuses it too. */}
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
      {panel === 'cdrom' && <VmCdromDialog vm={vm} onClose={() => setPanel(null)} />}
      {panel === 'snapshot' && <TakeSnapshot vm={vm} onClose={() => setPanel(null)} />}
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
 * Take snapshot's own dialog, opened from the menu. Reuses TakeSnapshotDialog
 * for the form and useSnapshotAction for the mutation, the same hook
 * SnapshotPanel uses for rollback and delete.
 */
function TakeSnapshot({ vm, onClose }: { vm: VmRow; onClose: () => void }) {
  const run = useSnapshotAction()

  const submit = (v: { name: string; description: string; vmstate: boolean }) =>
    run.mutate(
      { vmId: vm.id, op: 'create', name: v.name, description: v.description, vmstate: v.vmstate },
      {
        onSuccess: () => {
          notify.success('Snapshot create queued')
          onClose()
        },
        onError: () => notify.error(`Could not create snapshot "${v.name}"`),
      },
    )

  return (
    <TakeSnapshotDialog vmName={vm.name} pending={run.isPending}
      onClose={onClose} onSubmit={submit} />
  )
}

/**
 * DELETE /vms/{id}. The single most destructive route in the product.
 *
 * It opens with a typed confirmation of the VM name (ConfirmSelfDialog) and
 * destroys nothing until that name is typed. A second confirm in front of it
 * would only train the operator to click through both.
 *
 * A running guest is refused up front, with the reason on the disabled menu
 * item, and the backend's own 409 detail is what shows if that state changed
 * underneath us anyway.
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
      qc.invalidateQueries({ queryKey: ['vms'] })
    },
  })

  const submit = (typed: string) => {
    destroy.mutate(typed, {
      onSuccess: (r) => setJobId(r.job.id),
      onError: (e) => {
        const body = e instanceof ApiError ? (e.body as Record<string, unknown>) : null
        // guest_running/confirm_required races (the VM's state changed
        // between opening the dialog and confirming) get the backend's own
        // sentence verbatim; self_target is restated plainly rather than
        // assuming its wording.
        const msg = body?.error === 'self_target'
          ? 'Proxploy will not destroy the guest it is running inside.'
          : apiErrorDetail(e, 'Could not destroy that VM, try again.')
        notify.error(msg)
      },
    })
  }

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
