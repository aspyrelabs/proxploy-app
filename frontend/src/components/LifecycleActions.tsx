import { useState } from 'react'
import { useAppActionGates } from '../api/app-gates'
import { ApiError, apiErrorDetail } from '../api/client'
import { useEntitlements } from '../api/hooks'
import { useHostCapabilities } from '../api/hosts'
import { useLifecycle } from '../api/jobs'
import { notify } from '../lib/notify'
import { ConfirmSelfDialog } from './ConfirmSelfDialog'
import { Button } from './ui/button'

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
export function LifecycleActions({ target, id, name, status, hostId, size = 'md' }: {
  target: Target; id: number; name: string; status: string; hostId: number; size?: 'sm' | 'md'
}) {
  const gates = useAppActionGates(hostId)
  const ent = useEntitlements()
  const hostCaps = useHostCapabilities(hostId)
  const run = useLifecycle()
  const [guard, setGuard] = useState<Guard | null>(null)
  const pending = status === 'pending' || run.isPending
  // status === 'pending' is the optimistic patch itself, not a real lifecycle
  // state, RUNNING_ACTIONS/STOPPED_ACTIONS don't cover it, and falling
  // through to STOPPED_ACTIONS renders a disabled Start on a container that
  // is actually still running. Show one honest "Working…" affordance instead
  // of guessing which action set the pre-mutation status implied.
  const actions = status === 'pending' ? null : status === 'running' ? RUNNING_ACTIONS : STOPPED_ACTIONS
  const cls = size === 'sm' ? 'px-2 py-1 text-[11px]' : ''
  // Why an unresolved fetch withholds nothing: api/app-gates.ts.
  // App gates come from that shared hook; the VM path keeps its own
  // derivation (vms.lifecycle isn't covered there, that's out of scope here).
  const denied = target === 'app' ? gates.lifecycle.denied : ent.data != null && !ent.has('vms.lifecycle')
  const noLifecycle = target === 'vm' && hostCaps.loaded && hostCaps.capabilities?.lifecycle === false
  const reason = target === 'app'
    ? gates.lifecycle.reason
    : noLifecycle
      ? 'This host has no lifecycle API token configured. Add one in Settings → Hosts.'
      : denied ? 'Not included in your plan' : undefined

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

  return (
    <>
      <div className="flex items-center gap-2">
        {actions === null ? (
          <Button variant="ghost" className={cls} disabled>
            Working…
          </Button>
        ) : actions.map((a) => (
          <Button
            key={a}
            variant={a === 'stop' ? 'danger' : a === 'start' ? 'primary' : 'ghost'}
            className={cls}
            disabled={pending || denied || noLifecycle}
            title={reason}
            onClick={(e) => { e.stopPropagation(); fire(a) }}
          >
            {LABEL[a]}
          </Button>
        ))}
      </div>
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
 * renders (AppCard, GuestList, vms.tsx's list row): same host, same
 * capability shape, so the capabilities.console gate lives here once instead
 * of being copied into each call site.
 */
export function ConsoleButton({ hostId, onClick }: { hostId: number; onClick: () => void }) {
  // Why an unresolved fetch withholds nothing: api/app-gates.ts.
  const gates = useAppActionGates(hostId)
  return (
    <Button variant="ghost" className="px-2 py-1 text-[11px]" disabled={gates.console.denied}
      title={gates.console.reason}
      onClick={onClick}>
      Console
    </Button>
  )
}
