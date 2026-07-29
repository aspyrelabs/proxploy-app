import { useEffect, useRef } from 'react'
import uPlot from 'uplot'
import 'uplot/dist/uPlot.min.css'

/** Prototype spark look (doc 06 §b): 2px line, gradient fill 35%→0 alpha. */
export function Sparkline({ ts, values, color, width = 300, height = 52 }: {
  ts: number[]
  values: (number | null)[]
  color: string
  width?: number
  height?: number
}) {
  const ref = useRef<HTMLDivElement>(null)
  const plot = useRef<uPlot | null>(null)
  useEffect(() => {
    if (!ref.current || ts.length === 0) return
    const opts: uPlot.Options = {
      width, height,
      legend: { show: false },
      cursor: { show: false },
      axes: [{ show: false }, { show: false }],
      scales: { x: { time: true } },
      series: [{}, {
        stroke: color,
        width: 2,
        fill: (u) => {
          const g = u.ctx.createLinearGradient(0, 0, 0, u.bbox.height)
          g.addColorStop(0, color + '59') // 35% alpha
          g.addColorStop(1, color + '00')
          return g
        },
      }],
    }
    // ponytail: destroy+recreate on data change; setData() upgrade if it flickers
    plot.current = new uPlot(opts, [ts, values], ref.current)
    return () => { plot.current?.destroy(); plot.current = null }
  }, [ts, values, color, width, height])
  if (ts.length === 0) return <div style={{ height }} className="w-full" />
  return <div ref={ref} />
}
