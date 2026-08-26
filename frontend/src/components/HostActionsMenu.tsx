import { useState } from 'react'
import * as DropdownMenu from '@radix-ui/react-dropdown-menu'
import { notify } from '../lib/notify'
import { Button } from './ui/button'
import { HostEditDialog, type HostSummary } from './HostEditDialog'
import { HostPowerDialog } from './HostPowerDialog'
import { Icon } from './ui/icon'

const itemCls = 'flex cursor-pointer items-center gap-2 px-3 py-2 text-[13px] text-text-2 '
             + 'outline-none data-[highlighted]:bg-panel-2 data-[highlighted]:text-text'
// text-red / bg-red-dim tokens, not a literal hex (a test enforces no
// hardcoded colors: src/tests/no-hardcoded-colors.test.ts).
const destructiveItemCls = 'flex cursor-pointer items-center gap-2 border-t border-line-soft '
                          + 'px-3 py-2 text-[13px] text-red outline-none data-[highlighted]:bg-red-dim'

type Panel = 'edit' | 'reboot' | 'poweroff' | null

/**
 * The host page's actions menu: Edit, Reboot, Power off behind an
 * EllipsisVertical-style trigger.
 *
 * Reboot and Power off open HostPowerDialog (the typed-confirmation gate)
 * rather than act directly. `nodePowerMissing` is informational, not a
 * disable switch — a greyed control reads as broken — so when true, selecting
 * either item explains the missing privilege instead of opening a dialog that
 * would 403. `false`/unknown still opens the dialog; proxmox.py::node_power's
 * 403 message is the backstop.
 */
export function HostActionsMenu({ hostId, node, host, nodePowerMissing }: {
  hostId: number
  node: string
  host: HostSummary
  nodePowerMissing?: boolean | null
}) {
  const [open, setOpen] = useState(false)
  const [panel, setPanel] = useState<Panel>(null)

  const openPower = (which: 'reboot' | 'poweroff') => {
    if (nodePowerMissing === true) {
      notify.error('Proxploy cannot power this node yet.', {
        description: 'The API token is missing Sys.PowerMgmt on this node. '
                   + 'See docs.proxploy.com/getting-started/proxmox-token for '
                   + 'how to grant it, then try again.',
      })
      return
    }
    setPanel(which)
  }

  return (
    <>
      <DropdownMenu.Root open={open} onOpenChange={setOpen}>
        <DropdownMenu.Trigger asChild>
          <Button variant="ghost" size="icon-xs" aria-label={`Actions for ${node}`}>
            <Icon name="more_vert" />
          </Button>
        </DropdownMenu.Trigger>

        <DropdownMenu.Portal>
          <DropdownMenu.Content
            align="end"
            sideOffset={8}
            className="z-50 w-48 overflow-hidden rounded-card border border-line bg-panel
                       shadow-[0_12px_32px_rgba(0,0,0,.35)]"
          >
            <DropdownMenu.Group>
              <DropdownMenu.Item onSelect={() => setPanel('edit')} className={itemCls}>
                <Icon name="edit" size={16} /> Edit
              </DropdownMenu.Item>
              <DropdownMenu.Item onSelect={() => openPower('reboot')} className={itemCls}>
                <Icon name="restart_alt" size={16} /> Reboot
              </DropdownMenu.Item>
              <DropdownMenu.Item onSelect={() => openPower('poweroff')} className={destructiveItemCls}>
                <Icon name="power_settings_new" size={16} /> Power off
              </DropdownMenu.Item>
            </DropdownMenu.Group>
          </DropdownMenu.Content>
        </DropdownMenu.Portal>
      </DropdownMenu.Root>

      {panel === 'edit' && (
        <HostEditDialog hostId={hostId} host={host} onClose={() => setPanel(null)} />
      )}
      {panel === 'reboot' && (
        <HostPowerDialog hostId={hostId} node={node} command="reboot" onClose={() => setPanel(null)} />
      )}
      {panel === 'poweroff' && (
        <HostPowerDialog hostId={hostId} node={node} command="shutdown" onClose={() => setPanel(null)} />
      )}
    </>
  )
}
