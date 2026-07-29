import { useState } from 'react'
import { ApiError } from '../api/client'
import { useEntitlements } from '../api/hooks'
import { useLifecycle } from '../api/jobs'
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
export function LifecycleActions({ target, id, name, status, size = 'md' }: {
  target: Target; id: number; name: string; status: string; size?: 'sm' | 'md'
}) {
  const ent = useEntitlements()
  const run = useLifecycle()
  const [guard, setGuard] = useState<Guard | null>(null)
  const flag = target === 'app' ? 'apps.lifecycle' : 'vms.lifecycle'
  const pending = status === 'pending' || run.isPending
  // status === 'pending' is the optimistic patch itself, not a real lifecycle
  // state — RUNNING_ACTIONS/STOPPED_ACTIONS don't cover it, and falling
  // through to STOPPED_ACTIONS renders a disabled Start on a container that
  // is actually still running. Show one honest "Working…" affordance instead
  // of guessing which action set the pre-mutation status implied.
  const actions = status === 'pending' ? null : status === 'running' ? RUNNING_ACTIONS : STOPPED_ACTIONS
  const cls = size === 'sm' ? 'px-2 py-1 text-[11px]' : ''
  // useEntitlements().has() defaults to false until /entitlements resolves —
  // gating `disabled` on it directly would grey out (and swallow clicks on)
  // every action for the entire first fetch, not just for plans that lack
  // the flag. Only withhold access once the entitlements response has
  // actually landed and said no.
  const denied = ent.data != null && !ent.has(flag)

  const fire = (action: string, confirm?: string) =>
    run.mutate({ target, id, action, confirm }, {
      onError: (e) => {
        const body = e instanceof ApiError ? (e.body as Record<string, unknown>) : null
        if (body?.error === 'self_target') {
          setGuard({ phrase: String(body.confirm_phrase ?? name),
                     detail: String(body.detail ?? ''), action })
        }
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
            disabled={pending || denied}
            title={denied ? 'Not included in your plan' : undefined}
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
