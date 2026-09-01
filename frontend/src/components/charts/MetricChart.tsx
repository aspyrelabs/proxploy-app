import { useState } from 'react'
import { useMetrics } from '../../api/hooks'
import { Skeleton, SkeletonGroup, SkeletonLine } from '../ui/skeleton'
import { TimeChart, type ChartAccent, type ChartUnit } from './TimeChart'
import { segment } from '../ui/button'

/** TimeChart height default. Repeated here (not imported) so the skeleton
 *  placeholder reserves the plot's height before TimeChart renders. */
const DEFAULT_HEIGHT = 168

/** Chart that owns its own time range (per-chart, not page-level). Ranges
 *  start at 30m: the poller samples every 30s (PROXPLOY_POLL_INTERVAL_S),
 *  so anything shorter is 2–3 points pretending to be a trend. */
export const RANGES = [
  { label: '30m', hours: 0.5 },
  { label: '1h', hours: 1 },
  { label: '12h', hours: 12 },
  { label: '24h', hours: 24 },
] as const

export type RangeLabel = typeof RANGES[number]['label']

export function MetricChart({
  target, metric, unit, label, accent, defaultRange = '1h', height,
  idleNote,
}: {
  target: string | null
  metric: string
  unit: ChartUnit
  label: string
  accent?: ChartAccent
  defaultRange?: RangeLabel
  height?: number
  /** Set while the subject cannot produce a reading, e.g. a stopped guest.
   *  The series is not drawn at all: samples recorded before it stopped are
   *  real, but a line running through a period the guest was not running
   *  reads as a live measurement of nothing. */
  idleNote?: string
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
                ${segment(r.label === range)}`}
            >
              {r.label}
            </button>
          ))}
        </div>
      </div>
      {/* Guard on `target != null` as well as isPending: useMetrics is
          `enabled: !!target`, so a disabled query sits at pending forever.
          Keying on isPending alone would pulse an empty chart on a page with
          no target. TimeChart draws "No data yet" when `ts` is empty, which
          is a wrong answer while the first fetch is in flight (and on every
          range change, since each range is a fresh query key). */}
      {idleNote ? (
        <TimeChart ts={[]} values={[]} unit={unit} label={label} accent={accent}
          height={height} emptyNote={idleNote} />
      ) : q.isPending && target != null ? (
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
