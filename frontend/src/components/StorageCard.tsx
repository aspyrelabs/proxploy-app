import type { StorageRow } from '../api/storage'
import { fmtBytes, fmtPct } from '../lib/format'
import { Skeleton, SkeletonLine } from './ui/skeleton'
import { DANGER_GRADIENT, STORAGE_GRADIENT, UsageBar } from './UsageBar'

// doc 06 §a row 43 / §c: violet is storage's reserved accent, red takes over
// past 80%, the one place on this page the palette is a warning and not a
// decoration.
const DANGER_PCT = 80

export function StorageCard({ row, onOpen }:
  { row: StorageRow; onOpen: (row: StorageRow) => void }) {
  const hot = row.used_pct > DANGER_PCT
  return (
    <button
      type="button"
      onClick={() => onOpen(row)}
      className="rounded-card border border-line-soft bg-panel p-5 text-left transition hover:bg-panel-2 motion-reduce:transition-none"
    >
      <div className="flex items-center gap-3">
        <div
          className="grid h-9 w-9 shrink-0 place-items-center rounded-tile font-mono text-[11px] font-semibold text-[#1b1230]"
          style={{ background: STORAGE_GRADIENT }}
        >
          {(row.type ?? '??').slice(0, 2).toUpperCase()}
        </div>
        <div className="min-w-0">
          <div className="truncate font-mono text-[14px] text-text">{row.storage}</div>
          <div className="truncate font-mono text-[11px] text-text-3">
            {row.node} · {row.type ?? 'unknown'}
          </div>
        </div>
        <span className={`ml-auto shrink-0 rounded-full px-2 py-0.5 font-mono text-[10.5px] ${
          hot ? 'bg-red-dim text-red' : 'bg-panel-2 text-text-2'}`}>
          {fmtPct(row.used_pct)}
        </span>
      </div>
      <div className="mt-3">
        <UsageBar pct={row.used_pct} gradient={hot ? DANGER_GRADIENT : STORAGE_GRADIENT} />
        <div className="mt-1.5 font-mono text-[11px] text-text-3">
          {fmtBytes(row.used_bytes)} / {fmtBytes(row.total_bytes)}
        </div>
      </div>
    </button>
  )
}

/**
 * StorageCard's placeholder, classes copied from the card above so the two
 * measure the same. The type tile is `h-9 w-9 rounded-tile`; the used-percent
 * pill is `px-2 py-0.5` around a 10.5px line box.
 */
export function StorageCardSkeleton() {
  return (
    <div className="rounded-card border border-line-soft bg-panel p-5">
      <div className="flex items-center gap-3">
        <Skeleton className="h-9 w-9 shrink-0 rounded-tile" />
        <div className="min-w-0 flex-1">
          <SkeletonLine className="w-28 text-[14px]" />
          <SkeletonLine className="w-36 text-[11px]" />
        </div>
        <Skeleton className="ml-auto h-[19px] w-12 shrink-0 rounded-full" />
      </div>
      <div className="mt-3">
        <Skeleton className="h-1.5 w-full rounded-full" />
        <SkeletonLine className="mt-1.5 w-32 text-[11px]" />
      </div>
    </div>
  )
}
