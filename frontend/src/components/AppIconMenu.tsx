import { useState } from 'react'
import * as DropdownMenu from '@radix-ui/react-dropdown-menu'
import type { AppRow } from '../api/hooks'
import { useAppActionGates } from '../api/app-gates'
import { ApiError, apiErrorDetail } from '../api/client'
import { useLifecycle } from '../api/jobs'
import { useOpenWebUi } from '../api/open-web-ui'
import { notify } from '../lib/notify'
import { openConsoleWindow } from '../lib/console-window'
import { ConfirmSelfDialog } from './ConfirmSelfDialog'
import { Icon } from './ui/icon'

const itemCls = 'flex cursor-pointer items-center gap-2 px-3 py-2 text-[13px] text-text-2 '
             + 'outline-none data-[highlighted]:bg-panel-2 data-[highlighted]:text-text '
             + 'data-[disabled]:cursor-not-allowed data-[disabled]:opacity-50'

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

/**
 * The icon grid's context menu: Start, Stop, Restart, Console, Open, and
 * nothing else.
 *
 * DELIBERATELY NARROWER than the app detail page's actions. Migrate,
 * Reconfigure and Uninstall are not here: this menu sits on a dense grid an
 * operator scans, and a destructive action one slip away from Restart is not
 * a trade worth making. The app page has all of them.
 *
 * Lifecycle actions route through the same `useLifecycle` mutation
 * LifecycleActions.fire uses, error handling included: a 409 self_target
 * escalates to ConfirmSelfDialog, and everything else surfaces a
 * notify.error toast rather than letting the optimistic "pending" patch
 * revert in silence.
 */
export function AppIconMenu({ app, children }: { app: AppRow; children: React.ReactNode }) {
  const gates = useAppActionGates(app.host_id)
  const run = useLifecycle()
  const openWebUi = useOpenWebUi(app)
  const [guard, setGuard] = useState<Guard | null>(null)
  const pending = app.status === 'pending' || run.isPending
  const actions = app.status === 'pending' ? []
    : app.status === 'running' ? RUNNING_ACTIONS : STOPPED_ACTIONS

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
            {/* No catalog port means nothing to point a tab at, so the action is
                absent rather than offered and broken. Same rule as the detail
                header. */}
            {app.catalog_port != null && (
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
    </>
  )
}
