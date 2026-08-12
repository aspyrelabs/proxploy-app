import { useState } from 'react'
import * as DropdownMenu from '@radix-ui/react-dropdown-menu'
import { notify } from '../lib/notify'
import { Button } from './ui/button'
import { HostEditDialog, type HostSummary } from './HostEditDialog'
import { HostPowerDialog } from './HostPowerDialog'
import { Icon } from './ui/icon'

const itemCls = 'flex cursor-pointer items-center gap-2 px-3 py-2 text-[13px] text-text-2 '
             + 'outline-none data-[highlighted]:bg-panel-2 data-[highlighted]:text-text'
// The same destructive vocabulary Button's `danger` variant and AccountMenu's
// Sign out item already use -- text-red/bg-red-dim tokens, never a literal
// hex (src/tests/no-hardcoded-colors.test.ts).
const destructiveItemCls = 'flex cursor-pointer items-center gap-2 border-t border-line-soft '
                          + 'px-3 py-2 text-[13px] text-red outline-none data-[highlighted]:bg-red-dim'

type Panel = 'edit' | 'reboot' | 'poweroff' | null

/**
 * The individual host page's actions menu: Edit, Reboot, Power off, behind
 * one EllipsisVertical-style trigger. Translated from a shadcn+lucide
 * reference into what this codebase already has -- Radix's dropdown-menu
 * (see AccountMenu.tsx), the hand-rolled Button (`ghost`/`icon-xs`), and
 * Material Symbols via Icon -- rather than the reference's own primitives,
 * none of which exist here (no DropdownMenuShortcut, no `variant=
 * "destructive"` item, no `render={}` trigger prop).
 *
 * Reboot and Power off do not act directly: each opens HostPowerDialog,
 * which is the actual typed-confirmation gate (doc 02 §9, doc 08 §1/§9 row
 * 14). This menu is just the entry point.
 *
 * `nodePowerMissing` (GET /hosts/{id}'s own field, doc 08 §2/§9) is
 * informational, not a disable switch: Reboot/Power off never grey out,
 * matching NodeShellButton's own precedent in routes/hosts.tsx for the exact
 * same shape of problem (a greyed control reads as broken, not as "ask
 * first"). When it is confirmed True, selecting either item explains which
 * privilege is missing and how to grant it instead of opening a dialog that
 * would only fail with Proxmox's own 403. `false` or unknown (the host has
 * not been probed since this existed) still opens the dialog as normal; the
 * improved 403 message (services/proxmox.py::node_power) is the backstop if
 * it turns out to be missing after all.
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
