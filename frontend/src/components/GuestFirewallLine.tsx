import { Link } from '@tanstack/react-router'
import { Icon } from './ui/icon'
import { useOptions, useRules } from '../api/firewall'
import { quietCls } from './ui/button'

/** One line in a guest's detail panel: is Proxmox filtering this guest, and
 *  how much is configured. It exists because a guest whose traffic is being
 *  filtered by something invisible is the failure this whole feature was built
 *  to end, and the panel is where an operator looks first when an app is
 *  unreachable. */
export function GuestFirewallLine({ guestType, guestId }: {
  guestType: 'app' | 'vm'; guestId: number
}) {
  const scope = { kind: 'guest', guestType, guestId } as const
  const opts = useOptions(scope)
  const rules = useRules(scope)
  const on = Number(opts.data?.options.enable ?? 0) !== 0
  const count = rules.data?.rules.length ?? 0
  const state = on
    ? `on, ${count} rule${count === 1 ? '' : 's'}`
    : 'off'
  return (
    <Link to={`/firewall/guest/${guestType}/${guestId}` as never}
      aria-label="Firewall"
      className={`flex items-center gap-1.5 text-[12.5px] ${quietCls}`}>
      <Icon name="shield" size={16} />
      <span>Firewall {state}</span>
    </Link>
  )
}
