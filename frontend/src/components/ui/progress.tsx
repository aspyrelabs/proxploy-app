import { createContext, useContext, useId } from 'react'
import type { ReactNode } from 'react'

/**
 * Linear counterpart to ui/loading.tsx's ring.
 *
 * Determinate only where a real completion signal drives `value`; pass
 * null/undefined while merely waiting (the bar sweeps, announces busy, and
 * shows no figure). No self-incrementing timer: a percentage that climbs on
 * its own is a lie about progress (see JobContext.progress,
 * backend/proxploy/jobs/backend.py).
 *
 * ProgressLabel supplies the bar's accessible name via aria-labelledby, so a
 * Progress without one is an unnamed progressbar.
 */

type ProgressCtx = {
  /** 0..100, or null for indeterminate. Already clamped and rounded. */
  pct: number | null
  labelId: string
}

const Ctx = createContext<ProgressCtx>({ pct: null, labelId: '' })

export function Progress({ value, className = '', children }: {
  /** 0..100; null/undefined = indeterminate. */
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
            // A fixed-width sliver sweeping the track: motion without a figure.
            // motion-reduce parks it at the left; aria-busy above still carries
            // the state, so only the movement is lost.
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

/** The figure, when there is one. Renders nothing while indeterminate. */
export function ProgressValue({ className = '' }: { className?: string }) {
  const { pct } = useContext(Ctx)
  if (pct == null) return null
  return <span className={`font-mono text-[11px] text-text-3 ${className}`}>{pct}%</span>
}
