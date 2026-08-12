/**
 * The app's one loading indicator, in two modes.
 *
 * The ring is vendored from MagicUI's `animated-circular-progress-bar`
 * (https://magicui.design/r/animated-circular-progress-bar.json). Adapted:
 *
 *  - No `cn` helper: this repo has no clsx/tailwind-merge.
 *  - Colours default to CSS variables rather than the literals asked for.
 *    `var(--amber)` IS #F5B544 on the dark theme, and #C77E14 on the light one,
 *    so the token keeps the brand colour while letting the light theme work.
 *    A literal would also fail `no-hardcoded-colors.test.ts`. Same reasoning
 *    for the track: rgba(255,255,255,0.1) is invisible on a light background,
 *    where `var(--line)` is the faint rule this codebase already uses.
 *  - The demo's self-incrementing setInterval is not here. It is a preview
 *    device. A percentage that climbs on a timer is a lie about progress.
 *  - Upstream is determinate only: it has no looping mode. So an indeterminate
 *    wait gets a spinning arc with NO number rather than a fake one.
 *
 * Which mode to use is not a style choice:
 *  - Pass `value` only where a real completion signal drives it.
 *  - Omit `value` when we are simply waiting. The ring then spins, announces
 *    itself as busy, and shows no figure at all.
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
  /** 0..100. Omit for indeterminate: there is no honest number to show. */
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
            // Determinate: the arc IS the percentage. Indeterminate: a fixed
            // quarter arc that spins, which reads as motion without claiming a
            // figure.
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
