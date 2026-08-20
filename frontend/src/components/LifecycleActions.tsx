import { Fragment, useState } from 'react'
import { useAppActionGates, useVmLifecycleGate } from '../api/app-gates'
import { ApiError, apiErrorDetail } from '../api/client'
import { useLifecycle } from '../api/jobs'
import { notify } from '../lib/notify'
import { ConfirmSelfDialog } from './ConfirmSelfDialog'
import { Button } from './ui/button'
import { ButtonGroupSeparator } from './ui/button-group'

type Target = 'app' | 'vm'

const RUNNING_ACTIONS = ['stop', 'restart'] as const
const STOPPED_ACTIONS = ['start'] as const

const LABEL: Record<string, string> = {
  start: 'Start', stop: 'Stop', restart: 'Restart',
  shutdown: 'Shutdown', pause: 'Pause', resume: 'Resume',
}

type Guard = { phrase: string; detail: string; action: string }

/**
 * The prototype's app-card action row and detail header buttons, wired to the
 * real 202-Accepted job endpoints. Optimistic status patch happens in
 * useLifecycle; a 409 self_target escalates to the typed-confirmation dialog.
 */
export function LifecycleActions({ target, id, name, status, hostId, size = 'md',
                                  grouped = false }: {
  target: Target; id: number; name: string; status: string; hostId: number
  size?: 'xs' | 'sm' | 'md'
  /** Render as bare buttons with separators between them, for a parent
   *  ButtonGroup, instead of this component's own spaced flex row. */
  grouped?: boolean
}) {
  const gates = useAppActionGates(hostId)
  const vmGate = useVmLifecycleGate(hostId)
  const run = useLifecycle()
  const [guard, setGuard] = useState<Guard | null>(null)
  const pending = status === 'pending' || run.isPending
  // status === 'pending' is the optimistic patch itself, not a real lifecycle
  // state, RUNNING_ACTIONS/STOPPED_ACTIONS don't cover it, and falling
  // through to STOPPED_ACTIONS renders a disabled Start on a container that
  // is actually still running. Show one honest "Working…" affordance instead
  // of guessing which action set the pre-mutation status implied.
  const actions = status === 'pending' ? null : status === 'running' ? RUNNING_ACTIONS : STOPPED_ACTIONS
  // 'sm' keeps its hand-rolled numbers: existing call sites (AppCard, the
  // guest list, the VM rows) are pinned to them. 'xs' goes through Button's
  // own size table instead, so a grouped bar shares one scale with the
  // buttons welded beside it rather than drifting a pixel out.
  // Grouped bars go through Button's own size table, so every control welded
  // into one group shares a scale exactly. Ungrouped callers (the app card,
  // the guest list, the VM rows) keep the hand-rolled 'sm' string their
  // layouts are pinned to, so nothing moves for them.
  const cls = !grouped && size === 'sm' ? 'px-2 py-1 text-[11px]' : ''
  const btnSize = size === 'xs' ? 'xs' : grouped && size === 'sm' ? 'sm' : undefined
  // Why an unresolved fetch withholds nothing: api/app-gates.ts. Both gates
  // come from that file now, the VM one because VmActionsMenu offers these
  // same actions as menu items and needs the identical answer.
  const gate = target === 'app' ? gates.lifecycle : vmGate
  const denied = gate.denied
  const reason = gate.reason

  const fire = (action: string, confirm?: string) =>
    run.mutate({ target, id, action, confirm }, {
      onError: (e) => {
        const body = e instanceof ApiError ? (e.body as Record<string, unknown>) : null
        if (body?.error === 'self_target') {
          setGuard({ phrase: String(body.confirm_phrase ?? name),
                     detail: String(body.detail ?? ''), action })
          return
        }
        // Everything that is not self_target used to fall out of here in
        // silence: the optimistic "Working…" reverted on invalidation and
        // nothing said the action had been refused, so an unreachable node
        // looked identical to a button that did not register the click.
        notify.error(`Could not ${action} ${name}.`,
                     { description: apiErrorDetail(e, 'No reason was given, try again.') })
      },
      onSuccess: () => setGuard(null),
    })

  // Start is green and Stop is red, the two opposite outcomes; Restart is
  // neutral because it lands back where it started. `grouped` swaps the flex
  // row for a fragment with separators, which is what lets a ButtonGroup weld
  // these to the actions beside them without a double border down the seam.
  const buttons = actions === null ? (
    <Button variant="ghost" size={btnSize} className={cls} disabled>
      Working…
    </Button>
  ) : actions.map((a, i) => (
    <Fragment key={a}>
      {grouped && i > 0 && <ButtonGroupSeparator />}
      <Button
        variant={a === 'stop' ? 'danger' : a === 'start' ? 'success' : 'ghost'}
        size={btnSize}
        className={cls}
        disabled={pending || denied}
        title={reason}
        onClick={(e) => { e.stopPropagation(); fire(a) }}
      >
        {LABEL[a]}
      </Button>
    </Fragment>
  ))

  return (
    <>
      {grouped ? buttons : <div className="flex items-center gap-2">{buttons}</div>}
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

/**
 * The "Console" ghost button that sits beside LifecycleActions everywhere it
 * renders (AppCard, GuestList, the VM row's action bar): same host, same
 * capability shape, so the capabilities.console gate lives here once instead
 * of being copied into each call site.
 */
export function ConsoleButton({ hostId, onClick, grouped = false }: {
  hostId: number
  onClick: () => void
  /** Render at Button's own `sm` scale, for a parent ButtonGroup, instead of
   *  the hand-rolled string the spaced call sites are pinned to. Same switch
   *  and same reason as LifecycleActions' `grouped`: welded controls have to
   *  share one size table or the seam between them is a pixel off. */
  grouped?: boolean
}) {
  // Why an unresolved fetch withholds nothing: api/app-gates.ts.
  const gates = useAppActionGates(hostId)
  return (
    <Button variant="ghost" size={grouped ? 'sm' : undefined}
      className={grouped ? '' : 'px-2 py-1 text-[11px]'} disabled={gates.console.denied}
      title={gates.console.reason}
      // Stopped here, not left to the caller: this now renders inside a table
      // row that expands when clicked, and opening a console must not also
      // fold or unfold the row it was opened from. Nothing that renders this
      // button wants the click to carry on past it.
      onClick={(e) => { e.stopPropagation(); onClick() }}>
      Console
    </Button>
  )
}
