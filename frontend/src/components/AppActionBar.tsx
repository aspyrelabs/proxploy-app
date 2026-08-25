import { useState } from 'react'

import type { AppRow } from '../api/hooks'
import { useAppActionGates } from '../api/app-gates'
import { useOpenWebUi } from '../api/open-web-ui'
import { AppIconMenu } from './AppIconMenu'
import { AppSetupDialog } from './AppSetupDialog'
import { LifecycleActions } from './LifecycleActions'
import { Button } from './ui/button'
import { ButtonGroup, ButtonGroupSeparator } from './ui/button-group'
import { Icon } from './ui/icon'

/**
 * One app's actions, welded into a single control: Start or Stop, Restart and
 * Open as buttons, then everything else behind a three-dots menu.
 *
 * Three buttons, not nine. These are what an operator reaches for repeatedly on
 * a list of running apps; Console, Logs, Reconfigure, Migrate, Backup and
 * Delete are things you do to one app, once, and a row that showed them all
 * would be a wall of words per app. AppIconMenu carries them, the same
 * component the icon grid's tile menu uses, told to leave the lifecycle items
 * out so this row does not offer Restart twice.
 *
 * Start and Stop are never both offered, because an app is either running or
 * it is not; LifecycleActions already picks the pair from status and this
 * borrows that decision rather than repeating it. Green for Start and red for
 * Stop, the two opposite outcomes, and Restart stays neutral since it lands
 * back where it started.
 *
 * Open is ABSENT, not disabled, when the app has no known port: there is
 * nothing to point a tab at, and a dead button invites a click that cannot go
 * anywhere. Same rule the icon menu follows.
 *
 * Firewall used to be a fourth button and is now a menu item (AppIconMenu),
 * which is where a thing you open once per app belongs; three is the number
 * this row keeps. It is still never gated to a role, for the reason it never
 * was: it only navigates, and the Firewall page itself withholds the edit.
 *
 * Every button stops the click from bubbling: the table row around this one
 * expands when clicked, and acting on an app must not also fold or unfold the
 * row it sits in.
 */
export function AppActionBar({ app }: { app: AppRow }) {
  const gates = useAppActionGates(app.host_id)
  const openWebUi = useOpenWebUi(app)
  const [settingUp, setSettingUp] = useState(false)
  return (
    <ButtonGroup>
      <LifecycleActions target="app" id={app.id} name={app.name}
                        status={app.status} hostId={app.host_id} size="sm" grouped />
      {/* Same port the backend's /web-url will use, app row first and catalog
          second, so the button is offered exactly when there is one. Reading
          only the catalog's hid the button on an app whose port the operator
          had set by hand. */}
      {/* No port known at all: the row used to show NOTHING here, so an adopted
          app was a row with a gap where the useful button goes and no hint
          that anything was missing or fixable. The fix lived inside
          Reconfigure, which is not where anyone notices. Set up asks for the
          port and the tile, and afterwards this slot is the ordinary Open. */}
      {(app.web_port ?? app.catalog_port) == null && (
        <>
          <ButtonGroupSeparator />
          <Button variant="ghost" size="sm"
            title={`${app.name} was adopted, so Proxploy does not know its port`}
            onClick={(e) => { e.stopPropagation(); setSettingUp(true) }}>
            Set up
          </Button>
        </>
      )}
      {(app.web_port ?? app.catalog_port) != null && (
        <>
          <ButtonGroupSeparator />
          <Button variant="ghost" size="sm"
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
      <AppIconMenu app={app} lifecycle={false}>
        {/* No text, so the name has to be spelled out for anyone who cannot
            see the glyph, and it names the app: a table of these otherwise
            reads as a column of identical "More actions". */}
        <Button variant="ghost" size="sm" aria-label={`More actions for ${app.name}`}
          onClick={(e) => e.stopPropagation()}>
          <Icon name="more_vert" size={16} />
        </Button>
      </AppIconMenu>
      {settingUp && <AppSetupDialog app={app} onClose={() => setSettingUp(false)} />}
    </ButtonGroup>
  )
}
