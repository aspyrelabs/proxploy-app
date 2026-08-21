import { useNavigate } from '@tanstack/react-router'
import type { VmRow } from '../api/hooks'
import { useMe } from '../api/hooks'
import { canEditFirewall } from '../routes/firewall'
import { openConsoleWindow } from '../lib/console-window'
import { ConsoleButton, LifecycleActions } from './LifecycleActions'
import { VmActionsMenu } from './VmActionsMenu'
import { Button } from './ui/button'
import { ButtonGroup, ButtonGroupSeparator } from './ui/button-group'
import { Icon } from './ui/icon'

/**
 * One VM's actions, welded into a single control: Start or Stop, Restart,
 * Console and Firewall as buttons, then everything else behind a three-dots
 * menu.
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
 * Firewall is always offered, never gated to a role: it only navigates to the
 * guest's Firewall page, and reading a firewall is a viewer permission. The
 * page it opens is what actually withholds an edit from anyone below
 * operator, so this button never needs to.
 *
 * Every button stops the click from bubbling: the table row around this one
 * expands when clicked, and acting on a VM must not also fold or unfold the
 * row it sits in.
 */
export function VmActionBar({ vm }: { vm: VmRow }) {
  const navigate = useNavigate()
  const me = useMe()
  // Innocent until proven guilty, the same rule every gate on this bar
  // follows: an unresolved /auth/me withholds nothing, it only changes the
  // button's title once the role is known.
  const canEdit = me.data == null || canEditFirewall(me.data.role, 'guest')
  return (
    <ButtonGroup>
      <LifecycleActions target="vm" id={vm.id} name={vm.name}
                        status={vm.status} hostId={vm.host_id} size="sm" grouped />
      <ButtonGroupSeparator />
      {/* Its own window, never a route (lib/console-window.ts). `grouped` is
          what puts it on Button's own size table, the same scale the
          lifecycle buttons welded beside it are drawn at; the console
          capability gate stays inside the shared component. */}
      <ConsoleButton hostId={vm.host_id} grouped
                     onClick={() => openConsoleWindow('vm', vm.id)} />
      <ButtonGroupSeparator />
      <Button variant="ghost" size="sm"
        title={canEdit ? `Manage ${vm.name}'s firewall` : `View ${vm.name}'s firewall`}
        onClick={(e) => {
          e.stopPropagation()
          navigate({ to: `/firewall/guest/vm/${vm.id}` as never })
        }}>
        Firewall
      </Button>
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
