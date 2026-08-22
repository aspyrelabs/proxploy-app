import type { StorageRow } from '../api/storage'
import { fmtBytes, fmtPct } from '../lib/format'
import { Skeleton, SkeletonLine } from './ui/skeleton'
import { DANGER_GRADIENT, STORAGE_GRADIENT, UsageBar } from './UsageBar'

// doc 06 §a row 43 / §c: violet is storage's reserved accent, red takes over
// past 80%, the one place on this page the palette is a warning and not a
// decoration.
const DANGER_PCT = 80

/**
 * The glyph on the tile: a drive for a local datastore, a networked one for a
 * shared pool.
 *
 * Drawn as a CSS mask rather than an <img>, which is what lets it take the
 * tile's own colour. The two files in public/ are flat black, so an <img>
 * would paint black on violet whatever the theme did; masked, the shape comes
 * from the file and the colour from `bg-current`, which resolves to the
 * tile's existing text colour. No edit to the artwork, and nothing new to
 * keep in sync if it is replaced.
 *
 * It replaces the first two letters of the Proxmox type ("DI", "LV", "NF"),
 * which needed decoding and did not say the one thing worth knowing at a
 * glance. The precise type is still spelled out in full on the line below.
 */
function StorageGlyph({ shared }: { shared: boolean }) {
  const src = shared ? "/network-drive.svg" : "/hard-drive.svg";
  const mask = {
    maskImage: `url(${src})`,
    WebkitMaskImage: `url(${src})`,
    maskSize: "contain",
    WebkitMaskSize: "contain",
    maskRepeat: "no-repeat",
    WebkitMaskRepeat: "no-repeat",
    maskPosition: "center",
    WebkitMaskPosition: "center",
  } as const;
  return (
    <span
      role="img"
      // Says out loud what the shape means, and what the two letters never
      // did: whether this datastore is one machine's or the cluster's.
      aria-label={shared ? "Shared storage" : "Local storage"}
      className="block h-5 w-5 bg-current"
      style={mask}
    />
  );
}

export function StorageCard({ row, onOpen, showNode = true }:
  { row: StorageRow; onOpen: (row: StorageRow) => void
    /** False in the Storage page's shared group, where the node on the row is
     *  whichever one the poller happened to see first and says nothing true
     *  about where the datastore lives (routes/storage-groups.ts). */
    showNode?: boolean }) {
  const hot = row.used_pct > DANGER_PCT
  return (
    <button
      type="button"
      onClick={() => onOpen(row)}
      className="rounded-card border border-line-soft bg-panel p-5 text-left transition hover:bg-panel-2 motion-reduce:transition-none"
    >
      <div className="flex items-center gap-3">
        <div
          className="grid h-9 w-9 shrink-0 place-items-center rounded-tile text-[#1b1230]"
          style={{ background: STORAGE_GRADIENT }}
        >
          <StorageGlyph shared={row.shared} />
        </div>
        <div className="min-w-0">
          <div className="truncate font-mono text-[14px] text-text">{row.storage}</div>
          <div className="truncate font-mono text-[11px] text-text-3">
            {showNode ? `${row.node} · ` : ''}{row.type ?? 'unknown'}
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
