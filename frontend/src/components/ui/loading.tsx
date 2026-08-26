/**
 * The app's one loading indicator, in two modes. Ring vendored from MagicUI's
 * animated-circular-progress-bar, adapted:
 *
 *  - No `cn` helper: this repo has no clsx/tailwind-merge.
 *  - Colours are CSS variables, not literals: a literal would fail
 *    no-hardcoded-colors.test.ts, and var(--amber) keeps the brand colour
 *    across light/dark. var(--line) is the track rule this codebase uses
 *    (rgba white 0.1 is invisible on light backgrounds).
 *  - No self-incrementing setInterval: a percentage that climbs on a timer is
 *    a lie about progress.
 *  - Upstream is determinate only; indeterminate mode (spinning arc, no
 *    number) added here.
 */

const CIRCUMFERENCE = 2 * Math.PI * 45

export function Loading({
  value,
  label = 'Loading',
  size = 40,
  gaugePrimaryColor = 'var(--amber)',
  gaugeSecondaryColor = 'var(--line)',
  className = '',
}: {
  /** 0..100; omit for indeterminate. */
  value?: number
  /** The accessible name, and the visible caption when one is rendered. */
  label?: string
  /** Ring diameter in px. */
  size?: number
  gaugePrimaryColor?: string
  gaugeSecondaryColor?: string
  className?: string
}) {
  const determinate = typeof value === 'number'
  const pct = determinate ? Math.round(Math.max(0, Math.min(100, value))) : 0

  return (
    <div
      className={`relative ${className}`}
      style={{ width: size, height: size }}
      role="status"
      aria-live="polite"
      aria-busy={!determinate}
      aria-label={determinate ? `${label}, ${pct} percent` : label}
    >
      <svg viewBox="0 0 100 100" fill="none" className="size-full">
        <circle
          cx="50" cy="50" r="45" strokeWidth="10" strokeLinecap="round"
          style={{ stroke: gaugeSecondaryColor }}
        />
        <circle
          cx="50" cy="50" r="45" strokeWidth="10" strokeLinecap="round"
          style={{
            stroke: gaugePrimaryColor,
            strokeDasharray: determinate
              ? `${(pct / 100) * CIRCUMFERENCE} ${CIRCUMFERENCE}`
              : `${CIRCUMFERENCE / 4} ${CIRCUMFERENCE}`,
            transform: 'rotate(-90deg)',
            transformOrigin: '50% 50%',
            transition: determinate ? 'stroke-dasharray 600ms ease' : undefined,
          }}
          // motion-reduce drops the spin to a static arc: the element still
          // says aria-busy, so the state is not lost, only the movement.
          className={determinate ? '' : 'origin-center animate-spin motion-reduce:animate-none'}
        />
      </svg>
      {determinate && (
        <span className="absolute inset-0 grid place-items-center font-mono text-[11px] text-text-2">
          {pct}
        </span>
      )}
    </div>
  )
}

/** The block form: a centred ring with its caption, for a whole panel or route
 *  that is waiting. `QueryState` and the boot gate use this. */
export function LoadingBlock({ value, label = 'Loading', note }: {
  value?: number
  label?: string
  note?: string
}) {
  return (
    <div className="grid place-items-center gap-3 py-16">
      <Loading value={value} label={label} size={44} />
      <div className="text-center">
        <p className="text-[12.5px] text-text-2">{label}</p>
        {note && <p className="mt-0.5 text-[11.5px] text-text-3">{note}</p>}
      </div>
    </div>
  )
}
