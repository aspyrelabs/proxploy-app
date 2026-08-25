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
  // Every size goes through Button's own size table, grouped or not. The
  // ungrouped 'sm' callers (AppCard, the guest list, the VM rows) used to be
  // handed `px-2 py-1 text-[11px]` as a className instead, on the belief that
  // their layouts were pinned to those exact numbers. They never were: those
  // classes collide with the component's own size classes and LOSE in the
  // emitted CSS (`.px-3\.5` is written after `.px-2`), so every one of those
  // call sites has been rendering at full 'md' size all along. 'md' is
  // Button's default and needs no entry here.
  const btnSize = size === 'md' ? undefined : size
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
    <Button variant="ghost" size={btnSize} disabled>
      Working…
    </Button>
  ) : actions.map((a, i) => (
    <Fragment key={a}>
      {grouped && i > 0 && <ButtonGroupSeparator />}
      <Button
        variant={a === 'stop' ? 'danger' : a === 'start' ? 'success' : 'ghost'}
        size={btnSize}
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
export function ConsoleButton({ hostId, onClick }: {
  hostId: number
  onClick: () => void
}) {
  // Why an unresolved fetch withholds nothing: api/app-gates.ts.
  const gates = useAppActionGates(hostId)
  // One size, welded or spaced. There used to be a `grouped` prop choosing
  // between Button's 'sm' and a hand-rolled `px-2 py-1 text-[11px]`, but both
  // branches were asking for the same small control and the className one
  // never took effect, so the prop only ever decided whether this button came
  // out small or full-size by accident.
  return (
    <Button variant="ghost" size="sm" disabled={gates.console.denied}
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
