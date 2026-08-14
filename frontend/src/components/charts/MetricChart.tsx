import { useState } from 'react'
import { useMetrics } from '../../api/hooks'
import { Skeleton, SkeletonGroup, SkeletonLine } from '../ui/skeleton'
import { TimeChart, type ChartAccent, type ChartUnit } from './TimeChart'

/** TimeChart's own `height` default. Repeated here rather than exported from
 *  there, because the placeholder has to reserve the plot's height before
 *  TimeChart is rendered at all, and a placeholder of a different height is
 *  the layout jump this whole file is trying to avoid. */
const DEFAULT_HEIGHT = 168

/** A chart that owns its own time range.
 *
 *  The range lives here rather than on the page because each chart answers a
 *  different question: "is the CPU spiking right now" wants 30m, "did storage
 *  creep all week" wants 24h, and forcing one range on all three makes at
 *  least one of them useless.
 *
 *  Ranges start at 30m deliberately. The poller samples every 30s
 *  (PROXPLOY_POLL_INTERVAL_S), so anything shorter is two or three points
 *  pretending to be a trend.
 */
export const RANGES = [
  { label: '30m', hours: 0.5 },
  { label: '1h', hours: 1 },
  { label: '12h', hours: 12 },
  { label: '24h', hours: 24 },
] as const

export type RangeLabel = typeof RANGES[number]['label']

export function MetricChart({
  target, metric, unit, label, accent, defaultRange = '1h', height,
}: {
  target: string | null
  metric: string
  unit: ChartUnit
  label: string
  accent?: ChartAccent
  defaultRange?: RangeLabel
  height?: number
}) {
  const [range, setRange] = useState<RangeLabel>(defaultRange)
  const hours = RANGES.find((r) => r.label === range)?.hours ?? 1
  const q = useMetrics(target, metric, hours)

  return (
    <div>
      <div className="mb-1.5 flex items-center justify-between gap-3">
        <h3 className="text-[11px] uppercase tracking-wide text-text-3">{label}</h3>
        <div role="group" aria-label={`${label} time range`} className="flex gap-1">
          {RANGES.map((r) => (
            <button
              key={r.label}
              type="button"
              aria-pressed={r.label === range}
              onClick={() => setRange(r.label)}
              className={`cursor-pointer rounded-ctl px-1.5 py-0.5 font-mono text-[10.5px]
                transition ${r.label === range
                  ? 'bg-amber-dim text-amber'
                  : 'text-text-3 hover:text-text-2'}`}
            >
              {r.label}
            </button>
          ))}
        </div>
      </div>
      {/* `target != null` as well as isPending: useMetrics is `enabled:
          !!target`, and a disabled query sits at pending forever, so keying on
          isPending alone would pulse an empty chart on a page that has no
          target to chart at all.

          Why this branch exists: TimeChart draws its dashed "No data yet" box
          whenever `ts` is empty, and `ts` is empty for the whole of the first
          fetch. So a chart that had samples said it had none, which is a
          different and wrong answer, and it said it again on every range
          button, since each range is a fresh query key with nothing cached.
          The range group above stays live throughout, this is only the plot. */}
      {q.isPending && target != null ? (
        <SkeletonGroup label={`Loading ${label}`}>
          {/* TimeChart's own figure line ("47% · peak 61% · axis to 80%"). */}
          <SkeletonLine className="w-40 text-[11px]" />
          <div style={{ height: height ?? DEFAULT_HEIGHT }}>
            <Skeleton className="h-full w-full rounded-tile" />
          </div>
        </SkeletonGroup>
      ) : (
      <TimeChart
        ts={q.data?.ts ?? []}
        values={q.data?.value ?? []}
        unit={unit}
        label={label}
        accent={accent}
        height={height}
        // A short window on a young install genuinely has nothing in it; say
        // that rather than showing an empty frame the reader has to interpret.
        emptyNote={`No samples in the last ${range}.`}
      />
      )}
    </div>
  )
}
