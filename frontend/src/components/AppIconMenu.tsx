import { useState } from 'react'
import * as DropdownMenu from '@radix-ui/react-dropdown-menu'
import { useNavigate } from '@tanstack/react-router'
import { useEntitlements, useMe, type AppRow } from '../api/hooks'
import { canEditFirewall } from '../routes/firewall'
import { useAppActionGates } from '../api/app-gates'
import { ApiError, apiErrorDetail } from '../api/client'
import { useLifecycle } from '../api/jobs'
import { useOpenWebUi } from '../api/open-web-ui'
import { notify } from '../lib/notify'
import { openConsoleWindow, openLogsWindow } from '../lib/console-window'
import { BackupGuestDialog } from './BackupGuestDialog'
import { ConfirmSelfDialog } from './ConfirmSelfDialog'
import { MigrateDialog } from './MigrateDialog'
import { ReconfigureDialog } from './ReconfigureDialog'
import { UninstallDialog } from './UninstallDialog'
import { Icon } from './ui/icon'

const itemCls = 'flex cursor-pointer items-center gap-2 px-3 py-2 text-[13px] text-text-2 '
             + 'outline-none data-[highlighted]:bg-panel-2 data-[highlighted]:text-text '
             + 'data-[disabled]:cursor-not-allowed data-[disabled]:opacity-50'
// The destructive vocabulary HostActionsMenu's Power off item already uses:
// text-red/bg-red-dim tokens, never a literal hex
// (src/tests/no-hardcoded-colors.test.ts). The border-t IS the separator that
// keeps Delete off the end of the ordinary list.
const destructiveItemCls = 'flex cursor-pointer items-center gap-2 border-t border-line-soft '
                         + 'px-3 py-2 text-[13px] text-red outline-none data-[highlighted]:bg-red-dim '
                         + 'data-[disabled]:cursor-not-allowed data-[disabled]:opacity-50'

const NOT_IN_PLAN = 'Not included in your plan'

// Icon names are STRING LITERALS in an `icon:` field, not a computed lookup:
// scripts/icon-names.mjs statically scans src/ to build the Google Fonts
// icon_names parameter, and a name it cannot read out of the source ships a
// font subset without that glyph, so the browser renders the literal word.
const RUNNING_ACTIONS = [
  { action: 'stop', label: 'Stop', icon: 'stop' },
  { action: 'restart', label: 'Restart', icon: 'restart_alt' },
] as const
const STOPPED_ACTIONS = [
  { action: 'start', label: 'Start', icon: 'play_arrow' },
] as const

type Guard = { phrase: string; detail: string; action: string }
type Panel = 'reconfigure' | 'migrate' | 'backup' | 'uninstall' | null

/**
 * One app's actions as a menu, shared by the icon grid's tile menu and the
 * Apps table's three-dots menu. A `lifecycle` switch rather than two
 * components: the surfaces differ only in that the table row already carries
 * Start/Stop, Restart and Open as buttons beside the menu, so the grid tile's
 * menu is the only surface that keeps them.
 *
 * Lifecycle actions route through `useLifecycle` (as LifecycleActions.fire
 * does): a 409 self_target escalates to ConfirmSelfDialog, everything else
 * surfaces a notify.error toast rather than letting the optimistic "pending"
 * patch revert in silence.
 */
export function AppIconMenu({ app, lifecycle = true, children }: {
  app: AppRow
  /** Include Start/Stop, Restart and Open. On by default, which is the icon
   *  grid's tile menu: it is the only way to act on that app. The table row
   *  passes false, since those three are buttons beside the menu there. */
  lifecycle?: boolean
  children: React.ReactNode
}) {
  const gates = useAppActionGates(app.host_id)
  const ent = useEntitlements()
  const run = useLifecycle()
  const openWebUi = useOpenWebUi(app)
  const navigate = useNavigate()
  const me = useMe()
  // Innocent until proven guilty, the rule every gate here follows: an
  // unresolved /auth/me withholds nothing, it only changes the title.
  const canEdit = me.data == null || canEditFirewall(me.data.role, 'guest')
  const [guard, setGuard] = useState<Guard | null>(null)
  const [panel, setPanel] = useState<Panel>(null)
  const pending = app.status === 'pending' || run.isPending
  const actions = !lifecycle || app.status === 'pending' ? []
    : app.status === 'running' ? RUNNING_ACTIONS : STOPPED_ACTIONS

  // Same wait-for-first-fetch rule as api/app-gates.ts's "innocent until
  // proven guilty": has() reads false until /entitlements lands, so gating on
  // it directly would grey these out on every plan for the whole first fetch.
  const planDenied = (flag: string) => ent.data != null && !ent.has(flag)
  const reconfigureDenied = planDenied('apps.reconfigure')
  const migrateDenied = planDenied('migrate.cross_host')
  const backupDenied = planDenied('backups.run')
  const uninstallDenied = planDenied('apps.uninstall')

  const fire = (action: string, confirm?: string) =>
    run.mutate({ target: 'app', id: app.id, action, confirm }, {
      onError: (e) => {
        const body = e instanceof ApiError ? (e.body as Record<string, unknown>) : null
        if (body?.error === 'self_target') {
          setGuard({ phrase: String(body.confirm_phrase ?? app.name),
                     detail: String(body.detail ?? ''), action })
          return
        }
        notify.error(`Could not ${action} ${app.name}.`,
                     { description: apiErrorDetail(e, 'No reason was given, try again.') })
      },
      onSuccess: () => setGuard(null),
    })

  return (
    <>
      <DropdownMenu.Root>
        <DropdownMenu.Trigger asChild>{children}</DropdownMenu.Trigger>
        <DropdownMenu.Portal>
          <DropdownMenu.Content align="start" sideOffset={6}
            className="z-50 w-44 overflow-hidden rounded-card border border-line bg-panel
                       shadow-[0_12px_32px_rgba(0,0,0,.35)]">
            {actions.map((a) => (
              <DropdownMenu.Item key={a.action} className={itemCls}
                disabled={pending || gates.lifecycle.denied}
                title={gates.lifecycle.reason}
                onSelect={() => fire(a.action)}>
                <Icon name={a.icon} size={16} /> {a.label}
              </DropdownMenu.Item>
            ))}
            <DropdownMenu.Item className={itemCls}
              disabled={gates.console.denied} title={gates.console.reason}
              onSelect={() => openConsoleWindow('app', app.id)}>
              <Icon name="terminal" size={16} /> Console
            </DropdownMenu.Item>
            {/* No port at all, on the app row or in the catalog, means nothing
                to point a tab at, so the action is absent rather than offered
                and broken. Same pair the backend's /web-url picks from. */}
            {lifecycle && (app.web_port ?? app.catalog_port) != null && (
              <DropdownMenu.Item className={itemCls}
                disabled={gates.openUi.denied} title={gates.openUi.reason}
                onSelect={() => {
                  // The tab opens HERE, inside the gesture. Opening it inside
                  // the mutation would put window.open after an await and a
                  // popup blocker would drop it.
                  const tab = window.open('', '_blank')
                  if (tab) tab.opener = null
                  openWebUi.mutate(tab)
                }}>
                <Icon name="open_in_new" size={16} /> Open
              </DropdownMenu.Item>
            )}
            <DropdownMenu.Item className={itemCls}
              onSelect={() => openLogsWindow(app.id)}>
              <Icon name="description" size={16} /> Logs
            </DropdownMenu.Item>
            {/* Outside the `lifecycle` switch, so BOTH surfaces carry it: it is
                not one of the three the table row keeps as buttons. Never gated
                to a role because it only navigates; the Firewall page itself
                withholds the edit from anyone below operator. */}
            <DropdownMenu.Item className={itemCls}
              title={canEdit ? `Manage ${app.name}'s firewall`
                             : `View ${app.name}'s firewall`}
              onSelect={() => navigate({ to: `/firewall/guest/app/${app.id}` as never })}>
              <Icon name="shield" size={16} /> Firewall
            </DropdownMenu.Item>
            <DropdownMenu.Item className={itemCls}
              disabled={reconfigureDenied} title={reconfigureDenied ? NOT_IN_PLAN : undefined}
              onSelect={() => setPanel('reconfigure')}>
              <Icon name="tune" size={16} /> Reconfigure
            </DropdownMenu.Item>
            <DropdownMenu.Item className={itemCls}
              disabled={migrateDenied} title={migrateDenied ? NOT_IN_PLAN : undefined}
              onSelect={() => setPanel('migrate')}>
              <Icon name="swap_horiz" size={16} /> Migrate
            </DropdownMenu.Item>
            <DropdownMenu.Item className={itemCls}
              disabled={backupDenied} title={backupDenied ? NOT_IN_PLAN : undefined}
              onSelect={() => setPanel('backup')}>
              <Icon name="backup" size={16} /> Backup
            </DropdownMenu.Item>
            <DropdownMenu.Item className={destructiveItemCls}
              disabled={uninstallDenied} title={uninstallDenied ? NOT_IN_PLAN : undefined}
              onSelect={() => setPanel('uninstall')}>
              <Icon name="delete" size={16} /> Delete
            </DropdownMenu.Item>
          </DropdownMenu.Content>
        </DropdownMenu.Portal>
      </DropdownMenu.Root>
      {guard && (
        <ConfirmSelfDialog
          phrase={guard.phrase}
          detail={guard.detail}
          onCancel={() => setGuard(null)}
          onConfirm={(typed) => fire(guard.action, typed)}
        />
      )}
      {panel === 'reconfigure' && <ReconfigureDialog app={app} onClose={() => setPanel(null)} />}
      {panel === 'migrate' && <MigrateDialog app={app} onClose={() => setPanel(null)} />}
      {panel === 'backup' && (
        <BackupGuestDialog
          guest={{ type: 'app', id: app.id, name: app.name, hostId: app.host_id,
                   hostName: app.host_name, label: `CT ${app.ctid}` }}
          onClose={() => setPanel(null)}
        />
      )}
      {/* UninstallDialog carries its own type-the-name confirmation, which is
          the whole gate: a second confirm in front of it would only train the
          operator to click through both. */}
      {panel === 'uninstall' && <UninstallDialog app={app} onClose={() => setPanel(null)} />}
    </>
  )
}
