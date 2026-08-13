import { useState } from 'react'
import { Link } from '@tanstack/react-router'
import type { CatalogRow } from '../api/catalog'
import type { PopularityBand } from '../lib/store-order'
import { Button } from './ui/button'
import { Icon } from './ui/icon'
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
/**
 * The tag chips, and the reason there are only three of them.
 *
 * Measured over the 556 store-visible ct rows in the dev catalog, upstream's
 * booleans are extremely lopsided, so the naive reading of each flag would put
 * a chip on almost every card and say nothing:
 *
 *   has_arm      true 482 (87%)  false  66  null 7
 *   updateable   true 538 (97%)  false  10  null 7
 *   privileged   true  19 ( 3%)  false 529  null 7
 *
 * A chip that appears on 87% or 97% of the grid is furniture. So two of these
 * are rendered on the RARE side, where the information actually is: nearly
 * everything runs on ARM and updates in place, and it is the handful that
 * cannot which changes what an operator does next. `privileged` is the one
 * that is genuinely informative on `true`, and it is the security-relevant
 * one, so it stays as it is.
 *
 * Every condition below is an explicit === true or === false. Null means
 * upstream has no record for the slug (the 7 unlisted rows) and must render
 * NOTHING: `has_arm: null` is not "x86 only" and `privileged: null` is not
 * "unprivileged". Testing falsiness here would silently label all 9 of them
 * with claims nobody has made.
 */
const CHIP = 'inline-block rounded border border-line bg-panel-2 px-1.5 py-0.5 text-[10px] text-text-2'

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

export function StoreCard({ entry, onInstall, installed, band }: {
  entry: CatalogRow; onInstall: (slug: string) => void; installed: boolean
  /** Resolved by the page from the whole corpus, since a percentile claim can
   *  only be made against a population (lib/store-order.ts). Absent means no
   *  band, which is also what a null popularity produces. */
  band?: PopularityBand | null
}) {
  const name = entry.name ?? entry.slug
  const unlisted = entry.upstream_state === 'delisted' || entry.upstream_state === 'unlisted'
  const detail = { to: '/store/$slug' as const, params: { slug: entry.slug } }
  return (
    /**
     * ONE FIXED HEIGHT FOR EVERY CARD, so a 10-line description next to a
     * 2-line one stops leaving a hole in the grid. The height is spent in
     * this order: everything above the description is intrinsic, the
     * description is capped at exactly three lines, and a flex spacer below
     * "Read more" swallows whatever is left, which is what pins the chip row
     * and the action row to the same baseline on every card in a row.
     *
     * 284px is the sum of the parts plus a little slack for font metrics:
     * 32 padding + 40 icon + 20 name + 16 category + 57 description block +
     * 21 read-more + 27 chips + 60 action row is 273, and the spacer absorbs
     * the remainder rather than letting it show up as ragged bottoms.
     *
     * overflow-hidden is a guard, not a plan. The chip row cannot actually
     * wrap: the three tag chips and the unlisted badge are mutually exclusive
     * by construction, because a row upstream has no record for has null for
     * all three booleans and so renders none of them, and the widest possible
     * real combination (type + Privileged + x86 only + No in-place update)
     * measures ~282px against a ~365px chip lane at the 4-column width. If a
     * future chip breaks that arithmetic, this clips instead of pushing the
     * action row out of alignment across the row.
     */
    <div className="flex h-[284px] flex-col overflow-hidden rounded-card border border-line-soft bg-panel p-4">
      <div className="flex items-start justify-between gap-2">
        <CardIcon name={name} iconUrl={entry.icon_url} />
        {/* The popularity marker sits where the raw install count used to,
            opposite the app tile. The number itself is gone from the card on
            purpose: 126196 against a median of 1001 is a figure nobody can
            place, and it belongs on the detail page. A percentile can be read
            at a glance and cannot be misread as a rating.

            Gold is `text-amber`, the existing token, not a new one: it is
            #F5B544 in the dark theme and #C77E14 in the light one, both
            gold-family and both legible on their own background, which a
            hardcoded gold would not be. Sizes are 1.3x their baselines, per
            the sizing request: the icon from Icon's own default of 18 (23.4,
            rounded to 23) and the label from the 11px the old count used
            (14.3, rounded to 14). */}
        {band === 'top10' && (
          <span
            className="flex shrink-0 items-center gap-1 text-[14px] text-amber"
            title="Among the top 10% of these scripts by install runs recorded in community-scripts telemetry, finished attempts rather than downloads."
          >
            <Icon name="star_shine" size={23} />
            Top 10%
          </span>
        )}
      </div>
      {/* NO NESTED INTERACTIVES. The card is not itself a link: it already
          contains a real Install button, and an <a> wrapping a <button> is
          invalid HTML that breaks keyboard and screen-reader behaviour. The
          title and an explicit "Read more" are the two links instead, so
          every control here is a sibling of the others and each one is
          reachable by Tab in reading order. Truncated to one line with the
          full name in `title`, since a wrapping name would eat into the
          fixed height. */}
      <Link {...detail} title={name}
        className="mt-2 block truncate text-[14px] font-semibold text-text hover:text-amber hover:underline">
        {name}
      </Link>
      <div className="font-mono text-[11px] text-text-3">{entry.category ?? 'Uncategorized'}</div>
      {/* Exactly three lines, always, whether the text needs them or not:
          a fixed box is what makes the rows line up.

          The fade is painted from --panel, the card's own background, to
          transparent, which is also why it needs no "is it actually
          overflowing" condition. Over clipped text it reads as a fade; over
          the empty space of a short or missing description it is the card
          colour drawn on the card colour, i.e. invisible. Using the token
          rather than a literal is what keeps that true in both themes, since
          --panel is #121924 in the dark one and #FFFFFF in the light one. */}
      <div className="relative mt-1 h-[53px] shrink-0 overflow-hidden">
        <p className="line-clamp-3 text-[12px] text-text-2">{entry.description ?? ''}</p>
        <div aria-hidden
          className="pointer-events-none absolute inset-x-0 bottom-0 h-5 bg-[linear-gradient(to_top,var(--panel),transparent)]" />
      </div>
      {/* On every card, including the 7 with no description at all: the user
          asked for it unconditionally, for visual consistency, and it is
          honest even on those rows because the detail page still carries
          their availability, resource defaults and popularity. */}
      <Link {...detail}
        className="mt-1 shrink-0 self-start text-[11.5px] text-amber hover:underline">
        Read more
      </Link>
      {/* Absorbs the leftover height so the two rows below sit at the same
          offset on every card, whatever the description did. */}
      <div className="flex-1" />
      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        <span className="inline-block rounded bg-panel-2 px-1.5 py-0.5 font-mono text-[10px] uppercase text-text-3">
          {TYPE_LABEL[entry.type]}
        </span>
        {unlisted && (
          <span title={UNLISTED_TITLE} className={CHIP}>Not listed upstream</span>
        )}
        {entry.privileged === true && (
          <span className={CHIP}
            title="This script builds a privileged container. That is upstream's own choice for this app, and it means the container has more access to the host than an unprivileged one.">
            Privileged
          </span>
        )}
        {entry.has_arm === false && (
          <span className={CHIP}
            title="Upstream lists no ARM build for this script, so it needs an amd64 node.">
            x86 only
          </span>
        )}
        {entry.updateable === false && (
          <span className={CHIP}
            title="Upstream ships no update path for this script, so a new version means reinstalling rather than updating in place.">
            No in-place update
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
