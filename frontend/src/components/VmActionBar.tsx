import type { VmRow } from '../api/hooks'
import { openConsoleWindow } from '../lib/console-window'
import { ConsoleButton, LifecycleActions } from './LifecycleActions'
import { VmActionsMenu } from './VmActionsMenu'
import { Button } from './ui/button'
import { ButtonGroup, ButtonGroupSeparator } from './ui/button-group'
import { Icon } from './ui/icon'

/**
 * One VM's actions: Start/Stop, Restart, Console as buttons; the rest behind
 * the three-dots menu.
 *
 * Console holds the third slot because a VM has no web interface — it is the
 * only way into a VM at all. Start and Stop are never both offered
 * (LifecycleActions picks one by status). Firewall is a menu item and never
 * role-gated: it only navigates, and the Firewall page withholds edits.
 *
 * Every button stops click propagation — the row around it expands on click,
 * and acting on a VM must not fold/unfold its row.
 */
export function VmActionBar({ vm }: { vm: VmRow }) {
  return (
    <ButtonGroup>
      <LifecycleActions target="vm" id={vm.id} name={vm.name}
                        status={vm.status} hostId={vm.host_id} size="sm" grouped />
      <ButtonGroupSeparator />
      {/* Its own window, never a route (lib/console-window.ts); 'sm' is now the
          only size the shared component has, and the capability gate stays
          inside it. */}
      <ConsoleButton hostId={vm.host_id}
                     onClick={() => openConsoleWindow('vm', vm.id)} />
      <ButtonGroupSeparator />
      {/* lifecycle={false}: Start/Stop/Restart are already the buttons to the
          left; repeating them here would offer the same action twice. */}
      <VmActionsMenu vm={vm} lifecycle={false}>
        {/* No text, so the name has to be spelled out for anyone who cannot
            see the glyph, and it names the VM: a table of these otherwise
            reads as a column of identical "More actions". */}
        <Button variant="ghost" size="sm" aria-label={`More actions for ${vm.name}`}
          onClick={(e) => e.stopPropagation()}>
          <Icon name="more_vert" size={16} />
        </Button>
      </VmActionsMenu>
    </ButtonGroup>
  )
}
