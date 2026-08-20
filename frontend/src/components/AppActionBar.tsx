import type { AppRow } from '../api/hooks'
import { useAppActionGates } from '../api/app-gates'
import { useOpenWebUi } from '../api/open-web-ui'
import { openConsoleWindow } from '../lib/console-window'
import { LifecycleActions } from './LifecycleActions'
import { Button } from './ui/button'
import { ButtonGroup, ButtonGroupSeparator } from './ui/button-group'

/**
 * One app's four actions, welded into a single control: Start or Stop,
 * Restart, Web UI, Console.
 *
 * Start and Stop are never both offered, because an app is either running or
 * it is not; LifecycleActions already picks the pair from status and this
 * borrows that decision rather than repeating it. Green for Start and red for
 * Stop, the two opposite outcomes, and Restart stays neutral since it lands
 * back where it started.
 *
 * Web UI is ABSENT, not disabled, when the app has no catalog port: there is
 * nothing to point a tab at, and a dead button invites a click that cannot go
 * anywhere. Same rule the app detail header and the icon menu both follow.
 */
export function AppActionBar({ app }: { app: AppRow }) {
  const gates = useAppActionGates(app.host_id)
  const openWebUi = useOpenWebUi(app)
  const btn = 'px-2 py-1 text-[11px]'
  return (
    <ButtonGroup>
      <LifecycleActions target="app" id={app.id} name={app.name}
                        status={app.status} hostId={app.host_id} size="sm" grouped />
      {app.catalog_port != null && (
        <>
          <ButtonGroupSeparator />
          <Button variant="ghost" className={btn}
            disabled={gates.openUi.denied || openWebUi.isPending}
            title={gates.openUi.reason}
            onClick={(e) => {
              e.stopPropagation()
              // The tab opens HERE, inside the gesture. Opening it inside the
              // mutation would put window.open after an await, outside the
              // user gesture, and a popup blocker would drop it.
              const tab = window.open('', '_blank')
              if (tab) tab.opener = null
              openWebUi.mutate(tab)
            }}>
            Web UI
          </Button>
        </>
      )}
      <ButtonGroupSeparator />
      <Button variant="ghost" className={btn}
        disabled={gates.console.denied} title={gates.console.reason}
        onClick={(e) => { e.stopPropagation(); openConsoleWindow('app', app.id) }}>
        Console
      </Button>
    </ButtonGroup>
  )
}
