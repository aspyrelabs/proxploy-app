import { fmtBps } from '../lib/format'
import { Skeleton, SkeletonLine } from './ui/skeleton'

const CIRC = 326.7

/**
 * The same gauge with nothing measured yet, co-located with Ring so the two
 * cannot drift in size and shift the card between them.
 *
 * The track is drawn for real rather than approximated: Ring's unfilled circle
 * is already `stroke="var(--elev)"`, which is the exact token ui/skeleton.tsx
 * paints its bars with, so this is Ring's own SVG minus the arc and minus the
 * figure, pulsing. A rounded box of the same footprint would have been a solid
 * grey disc standing in for a 10px ring, which is not the same shape at all.
 *
 * The label stays real text. "CPU" is not waiting on anything, and it is what
 * tells the reader which of the three gauges is which while they fill.
 */
export function RingSkeleton({ label }: { label: string }) {
  return (
    <div aria-hidden className="flex flex-col items-center gap-1.5">
      <svg width="96" height="96" viewBox="0 0 120 120"
           className="animate-pulse motion-reduce:animate-none">
        <circle cx="60" cy="60" r="52" fill="none" stroke="var(--elev)" strokeWidth="10" />
      </svg>
      <div className="text-[12px] text-text-2">{label}</div>
      <SkeletonLine className="w-24 text-[11px]" />
    </div>
  )
}

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

/**
 * The two throughput arrows, as inline SVG rather than the Material Symbols
 * font.
 *
 * WHY NOT <Icon>. A ligature font renders one glyph in one colour, and this
 * needs two: the icon sits in the ordinary label colour like everything else
 * in this row, while the ARROW INSIDE IT carries the activity blink. Material
 * Symbols draws both `upload_2` and `download_2` as a single path whose first
 * subpath is the baseline bar and whose remainder is the arrow, so splitting
 * that path in two is what buys the second colour. The `d` strings below are
 * that glyph, verbatim from the Material Symbols 24px source, cut at the bar's
 * closing Z.
 *
 * The cost of owning them here is that they no longer follow the font when it
 * updates. That is the right trade for two glyphs: they are geometry, not
 * content, and the alternative was a single-colour icon that cannot show
 * whether anything is actually moving.
 */
const BAR = 'M160-80v-80h640v80H160Z'
const ARROW = {
  upload: 'M360-240v-280H200l280-360 280 360H600v280H360Zm80-80h80v-280h76L480-750'
        + ' 364-600h76v280Zm40-280Z',
  download: 'M480-240L200-600h160v-280h240v280h160L480-240Zm0-130 116-150h-76v-280h-80'
          + 'v280h-76l116 150Zm0-150Z',
} as const

function NetworkArrow({ dir, live }: { dir: 'upload' | 'download'; live: boolean }) {
  // Colour rides on the ARROW alone. The bar stays text-2 in every state, so
  // the tile reads as one of this row's labels rather than as a status light.
  const arrowCls = !live ? 'fill-text-2'
    : dir === 'upload'
      ? 'fill-red animate-pulse motion-reduce:animate-none'
      : 'fill-green animate-pulse motion-reduce:animate-none'
  return (
    <svg aria-hidden width="26" height="26" viewBox="0 -960 960 960" className="shrink-0">
      <path d={BAR} className="fill-text-2" />
      <path data-part={`${dir}-arrow`} d={ARROW[dir]} className={arrowCls} />
    </svg>
  )
}

/**
 * Throughput, as the fourth tile in the cluster-usage row beside the three
 * rings.
 *
 * NOT a ring, because a rate has no denominator. The other three tiles all
 * divide a used figure by a total; there is no "total" bandwidth to divide by,
 * and drawing an arc against an invented ceiling would be making up a number.
 * The same call AppCard makes about its own network row.
 *
 * The icons sit in the ordinary label colour. Only the ARROW INSIDE each one
 * takes a colour and blinks, and only while traffic is moving in that
 * direction, so the row reads at a glance as "something is happening" without
 * anyone parsing a figure. Idle arrows stay text-2 with the rest of the icon,
 * so a colour here always means movement rather than merely labelling which
 * arrow is which. motion-reduce turns the blink off: it is decoration, and the
 * figures below carry the same information for anyone who does not want it.
 */
export function NetworkStat({ inBps, outBps, unknown }: {
  inBps?: number | null
  outBps?: number | null
  /** True when /cluster/summary failed or reported nothing. The tile then
   *  says so instead of drawing a confident, idle-looking 0. */
  unknown?: boolean
}) {
  const up = !unknown && (outBps ?? 0) > 0
  const down = !unknown && (inBps ?? 0) > 0
  return (
    <div className="flex flex-col items-center gap-1.5">
      {/* One role="img" over the pair, matching how Ring labels its whole
          gauge: the arrows are decoration (Icon is aria-hidden) and a screen
          reader wants the reading, not two unlabelled glyphs. */}
      <div role="img"
           aria-label={unknown ? 'Network unknown'
             : `Network, ${fmtBps(outBps)} up, ${fmtBps(inBps)} down`}
           className="flex h-24 w-24 items-center justify-center gap-1">
        <NetworkArrow dir="upload" live={up} />
        <span className="font-mono text-[18px] text-text-3">/</span>
        <NetworkArrow dir="download" live={down} />
      </div>
      <div className="text-[12px] text-text-2">Network</div>
      <div className="font-mono text-[11px] text-text-3">
        {unknown ? 'unknown' : `${fmtBps(outBps)} / ${fmtBps(inBps)}`}
      </div>
    </div>
  )
}

/** NetworkStat with nothing measured yet. Same 96px box, same label, same
 *  sub line, so the row does not resize when the summary lands. Kept beside
 *  it for the reason RingSkeleton is kept beside Ring. */
export function NetworkStatSkeleton() {
  return (
    <div aria-hidden className="flex flex-col items-center gap-1.5">
      <div className="flex h-24 w-24 items-center justify-center gap-1">
        <Skeleton className="h-[26px] w-[26px] rounded-tile" />
        <span className="font-mono text-[18px] text-text-3">/</span>
        <Skeleton className="h-[26px] w-[26px] rounded-tile" />
      </div>
      <div className="text-[12px] text-text-2">Network</div>
      <SkeletonLine className="w-24 text-[11px]" />
    </div>
  )
}
