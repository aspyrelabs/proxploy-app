import type { AppRow } from '../api/hooks'
import { useAppActionGates } from '../api/app-gates'
import { useOpenWebUi } from '../api/open-web-ui'
import { openConsoleWindow } from '../lib/console-window'
import { LifecycleActions } from './LifecycleActions'
import { Button } from './ui/button'
import { ButtonGroup, ButtonGroupSeparator } from './ui/button-group'

/**
 * One app's four actions, welded into a single control: Start or Stop,
 * Restart, Open, Console.
 *
 * Start and Stop are never both offered, because an app is either running or
 * it is not; LifecycleActions already picks the pair from status and this
 * borrows that decision rather than repeating it. Green for Start and red for
 * Stop, the two opposite outcomes, and Restart stays neutral since it lands
 * back where it started.
 *
 * Open is ABSENT, not disabled, when the app has no catalog port: there is
 * nothing to point a tab at, and a dead button invites a click that cannot go
 * anywhere. Same rule the app detail header and the icon menu both follow.
 */
export function AppActionBar({ app }: { app: AppRow }) {
  const gates = useAppActionGates(app.host_id)
  const openWebUi = useOpenWebUi(app)
  return (
    <ButtonGroup>
      <LifecycleActions target="app" id={app.id} name={app.name}
                        status={app.status} hostId={app.host_id} size="xs" grouped />
      {app.catalog_port != null && (
        <>
          <ButtonGroupSeparator />
          <Button variant="ghost" size="xs"
            disabled={gates.openUi.denied || openWebUi.isPending}
            // "Open" rather than "Web UI": it is what the icon view's menu
            // already calls this action, and next to Console the pair reads as
            // two ways in rather than as a noun beside a verb. The title says
            // what opens, since the word alone does not.
            title={gates.openUi.reason ?? `Open ${app.name}'s web interface`}
            onClick={(e) => {
              e.stopPropagation()
              // The tab opens HERE, inside the gesture. Opening it inside the
              // mutation would put window.open after an await, outside the
              // user gesture, and a popup blocker would drop it.
              const tab = window.open('', '_blank')
              if (tab) tab.opener = null
              openWebUi.mutate(tab)
            }}>
            Open
          </Button>
        </>
      )}
      <ButtonGroupSeparator />
      <Button variant="ghost" size="xs"
        disabled={gates.console.denied} title={gates.console.reason}
        onClick={(e) => { e.stopPropagation(); openConsoleWindow('app', app.id) }}>
        Console
      </Button>
    </ButtonGroup>
  )
}
