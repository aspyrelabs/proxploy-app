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
  return (v) => (v == null ? UNKNOWN : `${Math.round(v)}%`)
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

export type BuildOptionsArgs = {
  width: number
  height: number
  unit: ChartUnit
  label: string
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
      // A percentage axis is pinned: auto-ranging 2.9%..3.1% draws a dramatic
      // mountain range out of an idle box, which is its own kind of lying.
      y: a.unit === 'percent'
        ? { range: [0, 100] as [number, number] }
        : { range: (_u: uPlot, _min: number, max: number) =>
              [0, max > 0 ? max * 1.05 : 1] as [number, number] },
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
  const hasData = ts.length > 0 && values.some((v) => v != null)

  useEffect(() => {
    const host = hostRef.current
    if (!host || !hasData || width <= 0 || !canDrawCanvas()) return
    const accentColor = getComputedStyle(host).color || NO_STYLESHEET.accent
    const opts = buildOptions({
      width, height, unit, label,
      accent: accentColor,
      axis: readVar('--text-3', NO_STYLESHEET.axis),
      grid: readVar('--line-soft', NO_STYLESHEET.grid),
      span: (ts[ts.length - 1] ?? 0) - (ts[0] ?? 0),
    })
    let made: uPlot | null = null
    try {
      made = new uPlot(opts, [ts, values] as unknown as uPlot.AlignedData, host)
    } catch {
      // jsdom has no canvas context. A chart that cannot draw must not take
      // the page down with it.
      made = null
    }
    plot.current = made
    return () => { made?.destroy(); plot.current = null }
  }, [ts, values, unit, label, width, height, themeTick, hasData])

  return (
    <div ref={boxRef} className="w-full overflow-hidden">
      {hasData ? (
        <div ref={hostRef} data-testid="timechart-plot" data-width={width}
          className={`${ACCENT_CLASS[accent]} w-full`} style={{ minHeight: height }} />
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
