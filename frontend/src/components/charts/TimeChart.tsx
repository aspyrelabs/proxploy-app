import { useEffect, useRef, useState } from 'react'
import uPlot from 'uplot'
import 'uplot/dist/uPlot.min.css'
import { UNKNOWN, fmtBps, fmtBytes } from '../../lib/format'

/** A real chart: labelled axes, a y scale that knows its unit, a hover
 *  readout, and a width taken from the container instead of a prop.
 *
 *  Deliberately NOT an upgrade of `Sparkline`. A spark is defined by having no
 *  axes and no cursor (doc 06 §b) and several places still want exactly that;
 *  what went wrong was using one at 480x120 as the CPU/memory/storage chart on
 *  the host page, where the reader has no way to tell 3% from 100%, no idea
 *  what "2161287168" was, and a hard-coded 480px canvas that spilled out of a
 *  card narrower than that.
 */

/** What the y values MEAN. Nothing else in here decides that; a chart handed
 *  raw byte counts and told `percent` will happily draw nonsense, which is the
 *  bug this type exists to make impossible to write by accident. */
export type ChartUnit = 'percent' | 'bytes' | 'bps'

export function unitFormatter(unit: ChartUnit): (v: number | null | undefined) => string {
  if (unit === 'bytes') return fmtBytes
  if (unit === 'bps') return fmtBps
  // Precision follows magnitude. A whole-number percent is right at 42% and
  // catastrophic at 0.14%, where it prints "0%" and tells the reader their
  // working chart is dead. The live node this was built against idles at
  // cpu_pct 0.14 and disk_pct 0.30, so this is the normal case, not the edge.
  return (v) => {
    if (v == null) return UNKNOWN
    if (v === 0) return '0%'
    if (Math.abs(v) < 1) return `${v.toFixed(2)}%`
    if (Math.abs(v) < 10) return `${v.toFixed(1)}%`
    return `${Math.round(v)}%`
  }
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/** Tick labels sized to the range on screen. A 24h chart wants clock time; a
 *  30-day one wants dates, because twenty identical "00:00"s is not an axis. */
export function timeTickFormatter(spanSeconds: number): (t: number) => string {
  const twoDays = 2 * 86400
  return (t: number) => {
    const d = new Date(t * 1000)
    if (spanSeconds > twoDays) return `${d.getDate()} ${MONTHS[d.getMonth()]}`
    const hh = String(d.getHours()).padStart(2, '0')
    const mm = String(d.getMinutes()).padStart(2, '0')
    return `${hh}:${mm}`
  }
}

/** rgb(...) -> rgba(..., a). The accent arrives as a computed colour (so it
 *  comes from the theme token, never a literal here), and computed colours are
 *  rgb strings, which cannot take the `+ '59'` hex-alpha trick. */
function withAlpha(color: string, alpha: number): string {
  const m = color.match(/^rgba?\(([^)]+)\)/)
  if (!m) return color
  const [r, g, b] = m[1].split(/[,/\s]+/).filter(Boolean)
  return `rgba(${r}, ${g}, ${b}, ${alpha})`
}

/** Percent axes snap to one of these tops rather than to the data.
 *
 *  A real idle node runs at cpu_pct 0.14 and disk_pct 0.30. On a hard 0..100
 *  axis both are a flat line welded to the floor, indistinguishable from a
 *  broken chart; auto-scaled to their own range they become a dramatic
 *  mountain built out of rounding noise, which is the worse lie. Snapping to a
 *  band keeps the baseline at zero always — so height stays proportional to
 *  the real number — while giving a quiet series enough room to show shape,
 *  and the axis label states which band is in force. */
export const PERCENT_BANDS = [5, 10, 25, 50, 100]

/** Top of the y scale. Zero-anchored in every case: a chart whose baseline
 *  floats is a chart that can make 6.3% look like 6300%. */
export function yTop(unit: ChartUnit, max: number): number {
  if (unit === 'percent') {
    const want = Math.max(0, max) * 1.25
    return PERCENT_BANDS.find((b) => b >= want) ?? 100
  }
  return max > 0 ? max * 1.05 : 1
}

export type BuildOptionsArgs = {
  width: number
  height: number
  unit: ChartUnit
  label: string
  /** Largest value in the series, which sets the top of the y scale. */
  max: number
  /** Resolved colours, already read off the theme by the caller. */
  accent: string
  axis: string
  grid: string
  /** Seconds covered by the data, which decides the x tick style. */
  span: number
}

/** Pure: given a size, a unit and three resolved colours, the uPlot options.
 *  Split out because a canvas is untestable under jsdom but every decision
 *  that governs what the canvas MEANS is testable right here. */
export function buildOptions(a: BuildOptionsArgs): uPlot.Options {
  const fmt = unitFormatter(a.unit)
  const font = '11px ui-monospace, monospace'
  const axisBase = {
    stroke: a.axis,
    font,
    grid: { stroke: a.grid, width: 1 },
    ticks: { stroke: a.grid, width: 1, size: 4 },
  }
  return {
    width: a.width,
    height: a.height,
    padding: [8, 8, 0, 0],
    legend: { show: true, live: true },
    cursor: { show: true, points: { show: true }, x: true, y: true },
    scales: {
      x: { time: true },
      y: { range: [0, yTop(a.unit, a.max)] as [number, number] },
    },
    axes: [
      { ...axisBase,
        values: (_u: uPlot, splits: number[]) => splits.map(timeTickFormatter(a.span)) },
      { ...axisBase, size: 62,
        values: (_u: uPlot, splits: number[]) => splits.map((v) => fmt(v)) },
    ],
    series: [
      { label: 'time' },
      {
        label: a.label,
        stroke: a.accent,
        width: 2,
        value: (_u: uPlot, v: number | null) => fmt(v),
        fill: (u: uPlot) => {
          const ctx = u.ctx
          if (!ctx?.createLinearGradient) return withAlpha(a.accent, 0.2)
          const g = ctx.createLinearGradient(0, 0, 0, u.bbox.height)
          g.addColorStop(0, withAlpha(a.accent, 0.32))
          g.addColorStop(1, withAlpha(a.accent, 0))
          return g
        },
      },
    ],
  }
}

const ACCENT_CLASS = {
  amber: 'text-amber', cyan: 'text-cyan', violet: 'text-violet',
  blue: 'text-blue', green: 'text-green',
} as const

export type ChartAccent = keyof typeof ACCENT_CLASS

// Only ever reached when no stylesheet is loaded at all (jsdom). Kept as
// neutral greys rather than brand literals so it can never quietly become the
// real palette; the real colours come from the tokens, resolved below.
const NO_STYLESHEET = { accent: 'rgb(128,128,128)', axis: 'rgb(128,128,128)',
                        grid: 'rgba(128,128,128,0.2)' }

let canvasOk: boolean | null = null
/** uPlot draws on a 2d context and schedules that draw in a microtask, so a
 *  missing context (jsdom, and any exotic embedded browser) explodes somewhere
 *  no try/catch of ours can reach. Ask first instead. */
function canDrawCanvas(): boolean {
  if (canvasOk !== null) return canvasOk
  try {
    canvasOk = document.createElement('canvas').getContext('2d') != null
  } catch {
    canvasOk = false
  }
  return canvasOk
}

function readVar(name: string, fallback: string): string {
  if (typeof document === 'undefined') return fallback
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return v || fallback
}

export function TimeChart({
  ts, values, unit, label, accent = 'amber', height = 168,
  emptyNote = 'Samples appear as the poller records them.',
}: {
  ts: number[]
  values: (number | null)[]
  unit: ChartUnit
  label: string
  accent?: ChartAccent
  height?: number
  emptyNote?: string
}) {
  const boxRef = useRef<HTMLDivElement>(null)
  const hostRef = useRef<HTMLDivElement>(null)
  const plot = useRef<uPlot | null>(null)
  const [width, setWidth] = useState(0)
  // Bumped when <html data-theme> flips, so the canvas (which cannot inherit
  // CSS) re-reads its colours instead of staying dark on a light page.
  const [themeTick, setThemeTick] = useState(0)
  // Why the plot did not draw, shown on the page. Silence here is what made
  // "nothing on the charts" impossible to diagnose without the browser.
  const [drawError, setDrawError] = useState<string | null>(null)

  useEffect(() => {
    const el = boxRef.current
    if (!el) return
    const measure = () => setWidth(Math.max(0, Math.floor(el.getBoundingClientRect().width)))
    measure()
    if (typeof ResizeObserver === 'undefined') {
      window.addEventListener('resize', measure)
      return () => window.removeEventListener('resize', measure)
    }
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  useEffect(() => {
    if (typeof MutationObserver === 'undefined' || typeof document === 'undefined') return
    const mo = new MutationObserver(() => setThemeTick((n) => n + 1))
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
    return () => mo.disconnect()
  }, [])

  // "Has a series" is not "has samples": disk_pct only started recording on
  // this install recently, and guests never record it at all, so a run of
  // nulls is the common case and has to say so rather than draw a flat floor.
  //
  // A series of real ZEROES is emphatically not that case. An idle node
  // genuinely reports 0.0%, and calling that "no data yet" would hide working
  // data behind the very message this component exists to stop showing.
  const real = values.filter((v): v is number => v != null)
  const hasData = ts.length > 0 && real.length > 0
  const latest = real.length > 0 ? real[real.length - 1] : null
  const peak = real.length > 0 ? Math.max(...real) : 0
  const fmt = unitFormatter(unit)

  useEffect(() => {
    const host = hostRef.current
    if (!host || !hasData || width <= 0 || !canDrawCanvas()) return
    const accentColor = getComputedStyle(host).color || NO_STYLESHEET.accent
    const opts = buildOptions({
      width, height, unit, label, max: peak,
      accent: accentColor,
      axis: readVar('--text-3', NO_STYLESHEET.axis),
      grid: readVar('--line-soft', NO_STYLESHEET.grid),
      span: (ts[ts.length - 1] ?? 0) - (ts[0] ?? 0),
    })
    let made: uPlot | null = null
    try {
      made = new uPlot(opts, [ts, values] as unknown as uPlot.AlignedData, host)
      setDrawError(null)
    } catch (e) {
      // A chart that cannot draw must not take the page down with it. But it
      // must not go quietly either: this catch previously swallowed the
      // reason, so a chart with 67 points of good data and a bad option
      // rendered as a blank rectangle with nothing logged anywhere, which is
      // undiagnosable from the outside and cost three rounds of "still
      // nothing on the charts".
      made = null
      const why = e instanceof Error ? `${e.name}: ${e.message}` : String(e)
      setDrawError(why)
      console.error(`[TimeChart] ${label} failed to draw:`, e, { opts })
    }
    plot.current = made
    return () => { made?.destroy(); plot.current = null }
  }, [ts, values, unit, label, width, height, themeTick, hasData, peak])

  return (
    <div ref={boxRef} className="w-full overflow-hidden">
      {hasData ? (
        <>
          {/* The number in words, above the plot. On a real idle node cpu_pct
              peaks at 0.14%, which on any honest zero-anchored axis is a flat
              line on the floor; without this readout that is indistinguishable
              from a chart that failed to draw. */}
          <div className="mb-2 flex items-baseline justify-between gap-2">
            <span className="font-mono text-[14px] text-text">
              {fmt(latest)}
              <span className="ml-1.5 text-[10.5px] uppercase tracking-wide text-text-3">now</span>
            </span>
            <span className="font-mono text-[11px] text-text-3">
              peak {fmt(peak)} · axis to {fmt(yTop(unit, peak))}
            </span>
          </div>
          <div ref={hostRef} data-testid="timechart-plot" data-width={width}
            className={`${ACCENT_CLASS[accent]} w-full`} style={{ minHeight: height }} />
          {drawError && (
            <p className="mt-1 font-mono text-[11px] text-red">
              chart failed to draw, {drawError}
            </p>
          )}
        </>
      ) : (
        <div style={{ minHeight: height }}
          className="flex flex-col items-center justify-center gap-1 rounded-tile
                     border border-dashed border-line-soft px-3 text-center">
          <span className="text-[12px] text-text-2">No data yet</span>
          <span className="text-[11px] text-text-3">{emptyNote}</span>
        </div>
      )}
    </div>
  )
}
