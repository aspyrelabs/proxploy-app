import { fmtByteRate, UNKNOWN } from '../lib/format'
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
 * Throughput, as the fourth tile in the cluster-usage row beside the three
 * rings.
 *
 * NOT a ring, because a rate has no denominator. The other three tiles all
 * divide a used figure by a total; link speed is not reliably knowable from the
 * PVE API, and real traffic sits so far below line rate that an arc against it
 * would read "fine" at every hour of every day. That is a decoration, not a
 * reading. The same call AppCard makes about its own network row.
 *
 * WHAT CHANGED, and why the two big arrows went. This tile used to be two 26px
 * two-tone arrow glyphs that blinked while traffic moved, with the actual
 * figures as a small grey caption underneath. The arrows were the largest
 * object in a cell whose entire job is to report two numbers, so beside three
 * gauges that each put their figure in the middle at 20px it did not read as a
 * peer: you saw a pair of icons and had to go looking for the reading. Now the
 * figures are the object, in the display font at 19px with tabular-nums so the
 * digits do not jitter as they swap, and the arrow is a 12px glyph that only
 * says which direction each line is. The blink went with them: a 12px marker
 * flashing beside the number it labels is noise, and the spark below now shows
 * movement over a window rather than merely that movement exists.
 *
 * WHERE THE NUMBERS COME FROM, and why no delta is computed here.
 * The rate is already a rate by the time it reaches the browser, twice over:
 *
 *   - /cluster/summary's net.in_bps / net.out_bps come from each node's
 *     rrddata, which PVE serves as an already-averaged bytes/sec bucket, and
 *     api/cluster.py sums them over nodes DEDUPED by (cluster, node) so a
 *     cluster with two enrolled hosts is counted once rather than twice.
 *   - the guest counters that really are cumulative (netin/netout off
 *     /cluster/resources) are diffed server-side in pollers/__init__.py::
 *     _update_net_rates, which also drops the sample when the delta goes
 *     negative, because a reboot zeroes the counter and the absolute value of
 *     that delta is a fabricated traffic spike at exactly the moment an
 *     operator is most likely to be watching.
 *
 * Differencing again here would be differencing a rate, which is an
 * acceleration, and would read as roughly zero forever. What this file DOES own
 * is the render boundary: a sample that arrives null (the poller could not
 * measure) or negative (a reset the server maths let through) is skipped rather
 * than plotted. See `plotSamples`.
 */

/** Both directions on one grid, so a spike in one is visibly bigger than a
 *  trickle in the other. 34px tall on purpose: this is a shape indicator, not a
 *  chart, and nobody reads a value off it. */
const SPARK_W = 168
const SPARK_H = 34

/** `fmtByteRate` output split at its last space, so the figure can take the
 *  display font and the unit can stay small and mono.
 *
 *  BYTES here, not the bits every other network surface in the app reports.
 *  That is a deliberate one-tile exception and lib/format.ts::fmtByteRate
 *  carries the reasoning; the short version is that this tile sits beside three
 *  gauges captioned in GiB and TiB, so bytes let a reader weigh throughput
 *  against the disk it is filling without converting in their head. Swapping
 *  this back to `fmtBps` to match the Network page needs asking first. */
export function splitRate(bytesPerSec?: number | null): [string, string] {
  const s = fmtByteRate(bytesPerSec)
  const i = s.lastIndexOf(' ')
  return i < 0 ? [s, ''] : [s.slice(0, i), s.slice(i + 1)]
}

/**
 * The samples worth drawing, each kept with its slot on the x axis.
 *
 * Two kinds are dropped rather than drawn. A null is a gap the backend recorded
 * on purpose (a degraded poll, or a node missing from the sum: the
 * `sample_net_in` gate in pollers/__init__.py), and plotting it as 0 would
 * claim the traffic stopped. A negative value is a counter reset that got
 * through, and there is no honest way to draw one.
 *
 * The x slot travels with the value so a gap stays a gap in position. Dropping
 * the slot too would slide every later sample left and change the shape of
 * history rather than admit a hole in it.
 */
export function plotSamples(
  values: readonly (number | null | undefined)[],
): [number, number][] {
  const out: [number, number][] = []
  values.forEach((v, i) => {
    if (v != null && Number.isFinite(v) && v >= 0) out.push([i, v])
  })
  return out
}

/** Timestamps → the window they actually span. Derived from the series rather
 *  than passed in, so the footer cannot claim a window the data does not cover.
 *  Seconds in, because that is what services/metrics.py::query_series emits. */
export function windowLabel(ts?: readonly number[]): string {
  if (!ts || ts.length < 2) return 'no history yet'
  const mins = Math.round((ts[ts.length - 1] - ts[0]) / 60)
  if (mins < 1) return 'last minute'
  if (mins < 90) return `last ${mins} min`
  return `last ${Math.round(mins / 60)} h`
}

function sparkPath(pts: [number, number][], slots: number, max: number) {
  if (pts.length < 2 || max <= 0 || slots < 2) return { line: '', area: '' }
  const x = (i: number) => (i / (slots - 1)) * SPARK_W
  // Half a pixel inset top and bottom, so a full-height stroke is not clipped
  // in half against the viewBox edge.
  const y = (v: number) => SPARK_H - 0.5 - (v / max) * (SPARK_H - 1)
  const line = pts
    .map(([i, v], k) => `${k ? 'L' : 'M'}${x(i).toFixed(1)} ${y(v).toFixed(1)}`)
    .join(' ')
  const area = `${line} L${x(pts[pts.length - 1][0]).toFixed(1)} ${SPARK_H}`
    + ` L${x(pts[0][0]).toFixed(1)} ${SPARK_H} Z`
  return { line, area }
}

function Spark({ inValues, outValues }: {
  inValues: readonly (number | null | undefined)[]
  outValues: readonly (number | null | undefined)[]
}) {
  const slots = Math.max(inValues.length, outValues.length)
  const din = plotSamples(inValues)
  const dout = plotSamples(outValues)
  // One scale for both directions, or the quiet one is stretched to full height
  // and a trickle looks like as much traffic as a flood.
  const max = Math.max(0, ...din.map(([, v]) => v), ...dout.map(([, v]) => v))
  const a = sparkPath(din, slots, max)
  const b = sparkPath(dout, slots, max)
  return (
    <svg aria-hidden width={SPARK_W} height={SPARK_H} data-part="spark"
         viewBox={`0 0 ${SPARK_W} ${SPARK_H}`} className="shrink-0">
      {/* Drawn in every state, no history included: it holds the 34px and gives
          the empty case something to be empty against, instead of collapsing
          the tile and shifting the three rings beside it. */}
      <line x1="0" y1={SPARK_H - 0.5} x2={SPARK_W} y2={SPARK_H - 0.5}
            stroke="var(--line-soft)" strokeWidth="1" />
      {a.area && <path d={a.area} fill="var(--cyan)" fillOpacity="0.16" />}
      {b.area && <path d={b.area} fill="var(--amber)" fillOpacity="0.16" />}
      {a.line && (
        <path data-part="spark-in" d={a.line} fill="none" stroke="var(--cyan)"
              strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round"
              className="transition-[d] duration-500 motion-reduce:transition-none" />
      )}
      {b.line && (
        <path data-part="spark-out" d={b.line} fill="none" stroke="var(--amber)"
              strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round"
              className="transition-[d] duration-500 motion-reduce:transition-none" />
      )}
    </svg>
  )
}

/** One direction: the glyph that says which way, then the figure, then its
 *  unit. Sized in that order of importance, which is the whole point of the
 *  rewrite. */
function Rate({ dir, bps, unknown }: {
  dir: 'in' | 'out'; bps?: number | null; unknown?: boolean
}) {
  // "?" rather than the word, because Ring already spells an unmeasured gauge
  // that way: the figure position takes the mark and the sub line underneath
  // carries the word. Two 19px "unknown"s stacked here shouted louder than any
  // real reading the tile ever shows.
  const [n, unit] = unknown ? ['?', ''] : splitRate(bps)
  return (
    <div className="flex items-baseline gap-1">
      <span aria-hidden data-part={`${dir}-arrow`}
            className={`font-mono text-[12px] leading-none ${
              dir === 'in' ? 'text-cyan' : 'text-amber'}`}>
        {dir === 'in' ? '↓' : '↑'}
      </span>
      <span className="font-display text-[19px] font-semibold leading-none tabular-nums">
        {n}
      </span>
      <span className="font-mono text-[10px] leading-none text-text-3">{unit}</span>
    </div>
  )
}

export function NetworkStat({
  inBps, outBps, ts, inValues = [], outValues = [], scope, unknown,
}: {
  /** Current rates, from /cluster/summary. Already deduped across hosts
   *  server-side; never sum /network/throughput's per-host rows to get these,
   *  that counts one cluster's traffic once per enrolled host. */
  inBps?: number | null
  outBps?: number | null
  /** History for the spark, from /network/throughput. Absent is a normal
   *  state, not an error: the tile still renders both figures. */
  ts?: readonly number[]
  inValues?: readonly (number | null | undefined)[]
  outValues?: readonly (number | null | undefined)[]
  /**
   * What the figures cover, named only when that is NOT the obvious thing.
   *
   * Absent means the combined cluster-wide reading, and the footer then says
   * the window and nothing else. It used to append "all hosts" there, which was
   * furniture: the whole row is already a combined view, the three gauges
   * beside this one sum every host without announcing it, and captioning one
   * tile with what all four of them do told the reader nothing they had not
   * already worked out from the heading.
   *
   * Set it when the tile is a departure from what the row otherwise means, ie.
   * a per-node view passing that node's name, which DOES need saying because
   * nothing else on screen would give it away. Never pass "all hosts" back in
   * by hand; the empty case is the combined case.
   */
  scope?: string
  /** True when /cluster/summary failed or reported nothing. The tile then
   *  says so instead of drawing a confident, idle-looking 0. */
  unknown?: boolean
}) {
  return (
    <div className="flex flex-col items-center gap-1.5">
      {/* One role="img" over the readings, matching how Ring labels its whole
          gauge: the arrows and the spark are decoration, and a screen reader
          wants the reading rather than two unlabelled glyphs. */}
      <div role="img"
           aria-label={unknown ? 'Network unknown'
             : `Network, ${fmtByteRate(inBps)} in, ${fmtByteRate(outBps)} out`
               + (scope ? `, ${scope}` : '')}
           className="flex h-24 w-[168px] flex-col justify-center gap-1">
        <Rate dir="in" bps={inBps} unknown={unknown} />
        <Rate dir="out" bps={outBps} unknown={unknown} />
        <Spark inValues={unknown ? [] : inValues} outValues={unknown ? [] : outValues} />
      </div>
      <div className="text-[12px] text-text-2">Network</div>
      {/* The window always, because a rate measured over an unnamed stretch of
          time is meaningless on a second look. The scope only when it is not
          the combined cluster reading the rest of the row already implies. */}
      <div className="font-mono text-[11px] text-text-3">
        {unknown ? UNKNOWN : windowLabel(ts) + (scope ? ` · ${scope}` : '')}
      </div>
    </div>
  )
}

/** NetworkStat with nothing measured yet. Same 96px box, same 168px width,
 *  same label, same sub line, so the row does not resize when the summary
 *  lands. Kept beside it for the reason RingSkeleton is kept beside Ring. */
export function NetworkStatSkeleton() {
  return (
    <div aria-hidden className="flex flex-col items-center gap-1.5">
      <div className="flex h-24 w-[168px] flex-col justify-center gap-1">
        <SkeletonLine className="w-24 text-[19px]" />
        <SkeletonLine className="w-20 text-[19px]" />
        <Skeleton className="h-[34px] w-[168px] rounded-tile" />
      </div>
      <div className="text-[12px] text-text-2">Network</div>
      <SkeletonLine className="w-28 text-[11px]" />
    </div>
  )
}
