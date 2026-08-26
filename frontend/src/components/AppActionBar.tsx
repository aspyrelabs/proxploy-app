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
 * Start/Stop, Restart, Open as buttons; everything else behind the menu.
 *
 * Open is absent — replaced by "Set up" — when the app has no known port.
 * Every button stops click propagation: the table row expands on click, and
 * acting on an app must not fold or unfold its row.
 */
export function AppActionBar({ app }: { app: AppRow }) {
  const gates = useAppActionGates(app.host_id)
  const openWebUi = useOpenWebUi(app)
  const [settingUp, setSettingUp] = useState(false)
  return (
    <ButtonGroup>
      <LifecycleActions target="app" id={app.id} name={app.name}
                        status={app.status} hostId={app.host_id} size="sm" grouped />
      {/* Same precedence /web-url uses (app port first, catalog second); reading
          only the catalog hid apps whose port was set by hand. */}
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
            title={gates.openUi.reason ?? `Open ${app.name}'s web interface`}
            onClick={(e) => {
              e.stopPropagation()
              // window.open here, inside the user gesture: after an await in the
              // mutation it would be outside the gesture and a popup blocker drops it.
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
        {/* aria-label needed: the glyph alone reads as identical "More actions" per row. */}
        <Button variant="ghost" size="sm" aria-label={`More actions for ${app.name}`}
          onClick={(e) => e.stopPropagation()}>
          <Icon name="more_vert" size={16} />
        </Button>
      </AppIconMenu>
      {settingUp && <AppSetupDialog app={app} onClose={() => setSettingUp(false)} />}
    </ButtonGroup>
  )
}
