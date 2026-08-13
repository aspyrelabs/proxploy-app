import { createContext, useContext, useId } from 'react'
import type { ReactNode } from 'react'

/**
 * The linear counterpart to ui/loading.tsx's ring, in the same two modes and
 * for the same reason.
 *
 *  - Pass `value` only where a real completion signal drives it.
 *  - Pass null/undefined while we are only waiting. The bar then sweeps,
 *    announces itself busy, and shows no figure at all.
 *
 * There is deliberately no self-incrementing timer and no "nearly there"
 * easing toward 100: a percentage that climbs on its own is a lie about
 * progress. The backend says the same thing from the other end, where
 * JobContext.progress documents why a job must never sit on a phase's high
 * water mark instead of showing honest progress
 * (backend/proxploy/jobs/backend.py).
 *
 * Compound rather than a pile of props, so a call site composes only the
 * parts it wants:
 *
 *   <Progress value={56} className="w-full max-w-sm">
 *     <ProgressLabel>Upload progress</ProgressLabel>
 *     <ProgressValue />
 *   </Progress>
 *
 * Both children are optional and either can be omitted. `ProgressLabel` also
 * supplies the bar's accessible name through aria-labelledby, so a Progress
 * rendered without one is an unnamed progressbar: give it a label unless the
 * surrounding copy already says what is happening.
 */

type ProgressCtx = {
  /** 0..100, or null for indeterminate. Already clamped and rounded. */
  pct: number | null
  labelId: string
}

const Ctx = createContext<ProgressCtx>({ pct: null, labelId: '' })

export function Progress({ value, className = '', children }: {
  /** 0..100. null/undefined means indeterminate: there is no honest number yet. */
  value?: number | null
  className?: string
  children?: ReactNode
}) {
  const labelId = useId()
  const determinate = typeof value === 'number' && Number.isFinite(value)
  const pct = determinate ? Math.round(Math.max(0, Math.min(100, value))) : null

  return (
    <Ctx.Provider value={{ pct, labelId }}>
      <div
        className={className}
        role="progressbar"
        aria-labelledby={labelId}
        aria-busy={pct == null}
        aria-valuemin={0}
        aria-valuemax={100}
        // Omitted, not zeroed, while indeterminate: aria-valuenow={0} would
        // announce "0 percent", which is a claim we cannot make yet.
        aria-valuenow={pct ?? undefined}
        aria-valuetext={pct == null ? undefined : `${pct}%`}
      >
        {children != null && (
          <div className="flex items-baseline justify-between gap-2">{children}</div>
        )}
        <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-elev">
          {pct == null ? (
            // A fixed-width sliver sweeping the track, the bar-shaped version
            // of Loading's spinning quarter arc: motion without a figure.
            // motion-reduce parks it at the left; aria-busy above still
            // carries the state, so only the movement is lost.
            <div className="pp-progress-sweep h-full w-1/3 rounded-full bg-amber" />
          ) : (
            <div
              className="h-full rounded-full bg-amber transition-[width] duration-500 ease-out motion-reduce:transition-none"
              style={{ width: `${pct}%` }}
            />
          )}
        </div>
      </div>
    </Ctx.Provider>
  )
}

/** The caption, and the bar's accessible name. */
export function ProgressLabel({ className = '', children }: {
  className?: string
  children: ReactNode
}) {
  const { labelId } = useContext(Ctx)
  return (
    <span id={labelId} className={`text-[11.5px] text-text-2 ${className}`}>{children}</span>
  )
}

/** The figure, when there is one. Renders nothing at all while the bar is
 *  indeterminate rather than a placeholder that could be read as a value. */
export function ProgressValue({ className = '' }: { className?: string }) {
  const { pct } = useContext(Ctx)
  if (pct == null) return null
  return <span className={`font-mono text-[11px] text-text-3 ${className}`}>{pct}%</span>
}
