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

/** Wired to the 202-Accepted job endpoints; optimistic status in useLifecycle;
 *  a 409 self_target escalates to the typed-confirmation dialog. */
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
  // 'pending' is the optimistic patch, not a lifecycle state: falling through
  // to STOPPED_ACTIONS would show a disabled Start on a still-running app.
  // Show "Working…" instead of guessing.
  const actions = status === 'pending' ? null : status === 'running' ? RUNNING_ACTIONS : STOPPED_ACTIONS
  // 'md' is Button's default, so it maps to undefined here.
  const btnSize = size === 'md' ? undefined : size
  // Gate resolution lives in api/app-gates.ts; the VM gate is shared with
  // VmActionsMenu, which needs the identical answer.
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
        // Non-self_target errors must notify: silent revert left an unreachable
        // node indistinguishable from a button that ignored the click.
        notify.error(`Could not ${action} ${name}.`,
                     { description: apiErrorDetail(e, 'No reason was given, try again.') })
      },
      onSuccess: () => setGuard(null),
    })

  // `grouped` renders a fragment with separators so a parent ButtonGroup can
  // weld these to its neighbors without a double border at the seam.
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

/** The "Console" ghost button; the capabilities.console gate lives here once
 *  rather than being copied into each call site. */
export function ConsoleButton({ hostId, onClick }: {
  hostId: number
  onClick: () => void
}) {
  const gates = useAppActionGates(hostId)
  return (
    <Button variant="ghost" size="sm" disabled={gates.console.denied}
      title={gates.console.reason}
      // stopPropagation: this sits in a row that expands on click, and opening
      // a console must not fold or unfold it.
      onClick={(e) => { e.stopPropagation(); onClick() }}>
      Console
    </Button>
  )
}
