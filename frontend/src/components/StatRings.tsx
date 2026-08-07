const CIRC = 326.7

export function Ring({ label, pct, sub, stops, unknown }: {
  label: string
  pct: number
  sub: string
  stops: [string, string]
  // True when the query behind `pct` failed. `pct` still defaults to 0 from
  // `?? 0` at the call site (harmless, since the arc is not drawn), but the
  // gauge must not read as "0% used"; that is a different, false claim.
  unknown?: boolean
}) {
  const id = `ring-${label.toLowerCase().replace(/\W/g, '')}`
  return (
    <div className="flex flex-col items-center gap-1.5">
      <svg width="96" height="96" viewBox="0 0 120 120" role="img"
           aria-label={unknown ? `${label} unknown` : `${label} ${Math.round(pct)}%`}>
        <defs>
          <linearGradient id={id} x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor={stops[0]} />
            <stop offset="100%" stopColor={stops[1]} />
          </linearGradient>
        </defs>
        <circle cx="60" cy="60" r="52" fill="none" stroke="var(--elev)" strokeWidth="10" />
        {!unknown && (
          <circle
            cx="60" cy="60" r="52" fill="none" stroke={`url(#${id})`} strokeWidth="10"
            strokeLinecap="round" strokeDasharray={CIRC}
            strokeDashoffset={CIRC * (1 - Math.min(100, pct) / 100)}
            transform="rotate(-90 60 60)"
            className="transition-[stroke-dashoffset] duration-700 motion-reduce:transition-none"
          />
        )}
        <text x="60" y="66" textAnchor="middle" fontSize="20" className="fill-text font-mono">
          {unknown ? '?' : `${Math.round(pct)}%`}
        </text>
      </svg>
      <div className="text-[12px] text-text-2">{label}</div>
      <div className="font-mono text-[11px] text-text-3">{sub}</div>
    </div>
  )
}
