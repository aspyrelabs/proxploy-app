import { useState } from 'react'
import type { CatalogRow } from '../api/catalog'
import { Button } from './ui/button'
import { STORE_GRADIENT } from './UsageBar'

// Every entry the Store ever renders is entry_type "ct" (the API call is
// pinned to entry_type=ct), so this is really just a label; kept as a lookup
// rather than a literal string so a card is still honest if that ever
// changes.
const TYPE_LABEL: Record<CatalogRow['type'], string> = {
  ct: 'LXC', vm: 'VM', pve: 'Host', addon: 'Add-on', turnkey: 'Turnkey',
}

// "delisted" (upstream soft-deleted it, so its metadata still arrives and the
// card is fully populated) and "unlisted" (upstream dropped it outright, so
// the card is bare) are two different facts about upstream's data and exactly
// one fact to whoever is reading the card: community-scripts does not list
// this app any more. So they share one badge here while staying distinct in
// the row itself.
//
// What the badge is careful NOT to say: that the app is deprecated, abandoned,
// broken or unsafe. We know one thing, that upstream stopped listing it. Its
// install script is still in the repo and still runs, which is why this is
// neutral chrome next to the type badge rather than a warning colour, and why
// it does not gate the Install button. Two of these are genuinely
// discontinued projects (readarr, overseerr) and the rest are not, and the
// card has no way to tell them apart, so it does not try.
const UNLISTED_TITLE =
  'community-scripts no longer lists this app. Its install script is still in '
  + 'the repository and still installs. This is about the upstream catalog, '
  + 'not a judgement about the app itself.'

// A card must render cleanly with just name, type and an initial tile when
// upstream metadata has no record for this slug (37 of the 584 ct rows have
// none, and that is normal, never an error), or the sync hasn't run yet, or
// the <img> itself fails to load: scripts are the source of truth, upstream
// metadata is presentation-only decoration (catalog expansion plan, decision
// 1). Icons are rendered straight from upstream's CDN with no local binary
// cache, so a URL that 404s or is blocked is an expected case, not a bug.
// Never let a broken image or a missing icon_url break the card.
function CardIcon({ name, iconUrl }: { name: string; iconUrl: string | null }) {
  const [broken, setBroken] = useState(false)
  if (iconUrl && !broken) {
    return (
      <img
        src={iconUrl} alt={name} loading="lazy" width={40} height={40}
        className="h-10 w-10 rounded-tile object-contain"
        onError={() => setBroken(true)}
      />
    )
  }
  return (
    <div
      className="flex h-10 w-10 items-center justify-center rounded-tile font-display text-[14px] font-semibold text-white"
      style={{ background: STORE_GRADIENT }}
    >
      {name.slice(0, 2).toUpperCase()}
    </div>
  )
}

export function StoreCard({ entry, onInstall, installed }: {
  entry: CatalogRow; onInstall: (slug: string) => void; installed: boolean
}) {
  const name = entry.name ?? entry.slug
  const unlisted = entry.upstream_state === 'delisted' || entry.upstream_state === 'unlisted'
  return (
    <div className="rounded-card border border-line-soft bg-panel p-4">
      <div className="flex items-start justify-between">
        <CardIcon name={name} iconUrl={entry.icon_url} />
        {entry.popularity != null && (
          <span className="font-mono text-[11px] text-text-3">★ {entry.popularity}</span>
        )}
      </div>
      <div className="mt-2 text-[14px] font-semibold text-text">{name}</div>
      <div className="font-mono text-[11px] text-text-3">{entry.category ?? 'Uncategorized'}</div>
      <div className="mt-1 min-h-[34px] text-[12px] text-text-2">
        {entry.description ?? ''}
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        <span className="inline-block rounded bg-panel-2 px-1.5 py-0.5 font-mono text-[10px] uppercase text-text-3">
          {TYPE_LABEL[entry.type]}
        </span>
        {unlisted && (
          <span title={UNLISTED_TITLE}
            className="inline-block rounded border border-line bg-panel-2 px-1.5 py-0.5 text-[10px] text-text-2">
            Not listed upstream
          </span>
        )}
      </div>
      <div className="mt-3 border-t border-line-soft pt-3">
        {entry.installable === false ? (
          <div className="text-[12px] text-text-3">
            Not installable, {entry.unsupported_reason}
            {entry.website && (
              <>
                {' '}
                <a href={entry.website} target="_blank" rel="noreferrer"
                  className="text-amber hover:underline">upstream</a>
              </>
            )}
          </div>
        ) : installed ? (
          <Button variant="ghost" disabled>Installed</Button>
        ) : (
          <Button variant="primary" onClick={() => onInstall(entry.slug)}>Install</Button>
        )}
      </div>
    </div>
  )
}
