import type { VmRow } from '../api/hooks'
import { openConsoleWindow } from '../lib/console-window'
import { ConsoleButton, LifecycleActions } from './LifecycleActions'
import { VmActionsMenu } from './VmActionsMenu'
import { Button } from './ui/button'
import { ButtonGroup, ButtonGroupSeparator } from './ui/button-group'
import { Icon } from './ui/icon'

/**
 * One VM's actions, welded into a single control: Start or Stop, Restart and
 * Console as buttons, then everything else behind a three-dots menu.
 *
 * Three buttons, the same count and the same rule as AppActionBar.
 *
 * The Apps row's twin (AppActionBar), and the third slot is where the two
 * differ. On an app that slot is Open, the app's own web interface. A VM has
 * no catalog port and no web interface Proxploy knows how to address, so
 * nothing wants that slot, and Console takes it: it is the ONLY way into a VM
 * at all, which makes it the one action here an operator reaches for
 * repeatedly rather than once. It used to sit in the menu, one click further
 * away than the thing it is the entire point of the row.
 *
 * Start and Stop are never both offered, because a VM is either running or it
 * is not; LifecycleActions already picks the pair from status and this borrows
 * that decision rather than repeating it. Green for Start and red for Stop,
 * the two opposite outcomes, and Restart stays neutral since it lands back
 * where it started.
 *
 * Firewall used to be a fourth button and is now a menu item
 * (VmActionsMenu), which is where a thing you open once per VM belongs. It is
 * still never gated to a role, for the reason it never was: it only
 * navigates, and the Firewall page itself withholds the edit.
 *
 * Every button stops the click from bubbling: the table row around this one
 * expands when clicked, and acting on a VM must not also fold or unfold the
 * row it sits in.
 */
export function VmActionBar({ vm }: { vm: VmRow }) {
  return (
    <ButtonGroup>
      <LifecycleActions target="vm" id={vm.id} name={vm.name}
                        status={vm.status} hostId={vm.host_id} size="sm" grouped />
      <ButtonGroupSeparator />
      {/* Its own window, never a route (lib/console-window.ts). It is drawn at
          the same 'sm' scale as the lifecycle buttons welded beside it, which
          is now the only size it has rather than something this call site
          asked for; the console capability gate stays inside the shared
          component. */}
      <ConsoleButton hostId={vm.host_id}
                     onClick={() => openConsoleWindow('vm', vm.id)} />
      <ButtonGroupSeparator />
      {/* lifecycle={false}: Start, Stop and Restart are the buttons welded to
          the left of this menu, so repeating them inside it would offer the
          same action twice a centimetre apart. The Hosts grid's tile has no
          buttons and takes the default. */}
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
