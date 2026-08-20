import { useEntitlements } from './hooks'
import { useHostCapabilities } from './hosts'

export type AppGate = { denied: boolean; reason: string | undefined }

const NO_GATE: AppGate = { denied: false, reason: undefined }
const NOT_IN_PLAN = 'Not included in your plan'
const noToken = (what: string) =>
  `This host has no ${what} API token configured. Add one in Settings → Hosts.`

/**
 * Whether each app action is available on one host, and why not when it is
 * not.
 *
 * ONE hook rather than the checks living inside the components, because the
 * icon grid offers the same actions as MENU ITEMS, which are not buttons and
 * so cannot reuse LifecycleActions or ConsoleButton. Two copies of these rules
 * is how a menu ends up offering Start on a host that cannot perform it.
 *
 * BOTH SOURCES ARE "INNOCENT UNTIL PROVEN GUILTY". useEntitlements().has()
 * returns false until /entitlements resolves, and capabilities read undefined
 * until GET /hosts does. Withholding on either of those would grey out (and
 * swallow clicks on) every action for the entire first fetch, on every plan
 * and every host, not just the ones that actually lack the flag. So only an
 * answer that has arrived, and says no, withholds anything.
 */
export function useAppActionGates(hostId: number) {
  const ent = useEntitlements()
  const hostCaps = useHostCapabilities(hostId)
  const landed = ent.data != null
  const capsLanded = hostCaps.loaded

  const plan = (flag: string): boolean => landed && !ent.has(flag)
  const capability = (name: 'lifecycle' | 'console'): boolean =>
    capsLanded && hostCaps.capabilities?.[name] === false

  const gate = (missingToken: string | null, flag: string): AppGate => {
    if (missingToken) return { denied: true, reason: noToken(missingToken) }
    if (plan(flag)) return { denied: true, reason: NOT_IN_PLAN }
    return NO_GATE
  }

  return {
    lifecycle: gate(capability('lifecycle') ? 'lifecycle' : null, 'apps.lifecycle'),
    // NO entitlement flag. ConsoleButton gates on the host capability and
    // nothing else today, so adding one here would newly withhold Console
    // from a plan that has it. This hook must change what no existing control
    // does; it only moves where the rules live.
    console: capability('console')
      ? { denied: true, reason: noToken('console') }
      : NO_GATE,
    // Open reads an address and opens a tab. It needs no PVE token at all, so
    // no capability gates it, only the plan.
    openUi: gate(null, 'apps.open_ui'),
  }
}

/**
 * Whether a VM's lifecycle actions are available on one host, and why not.
 *
 * A separate hook rather than another key on the object above, because the
 * plan flag differs: a VM answers to `vms.lifecycle`, an app to
 * `apps.lifecycle`, and a single `lifecycle` gate that quietly meant one of
 * them would be wrong wherever it was reused. The host capability is the same
 * one either way, since it is the token the host was given, not the kind of
 * guest it acts on.
 *
 * The missing token comes first: a plan that includes the action still cannot
 * perform it without a lifecycle token, and "Not included in your plan" would
 * send the operator to the wrong page to fix it.
 *
 * Both LifecycleActions (the row's Start/Stop buttons) and VmActionsMenu (the
 * same actions as menu items) read this. Two copies of the rule is how a menu
 * ends up offering Shutdown on a host that cannot perform it.
 */
export function useVmLifecycleGate(hostId: number): AppGate {
  const ent = useEntitlements()
  const hostCaps = useHostCapabilities(hostId)
  if (hostCaps.loaded && hostCaps.capabilities?.lifecycle === false) {
    return { denied: true, reason: noToken('lifecycle') }
  }
  // Innocent until proven guilty, exactly as above: has() reads false until
  // /entitlements lands.
  if (ent.data != null && !ent.has('vms.lifecycle')) {
    return { denied: true, reason: NOT_IN_PLAN }
  }
  return NO_GATE
}
