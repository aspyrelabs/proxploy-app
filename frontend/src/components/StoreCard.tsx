import { useRef } from 'react'
import type { MouseEvent } from 'react'
import type { CatalogRow } from '../api/catalog'
import { IconTile } from './IconTile'
import { Button, amberLinkCls, linkCls } from './ui/button'
import { Icon } from './ui/icon'
import { Skeleton, SkeletonLine } from './ui/skeleton'

// Everything the Store renders is entry_type "ct" (the API call is pinned to
// it), so this is really a label. Kept as a lookup rather than a literal so a
// card stays honest if that ever changes.
const TYPE_LABEL: Record<CatalogRow['type'], string> = {
  ct: 'LXC', vm: 'VM', pve: 'Host', addon: 'Add-on', turnkey: 'Turnkey',
}

// "delisted" (upstream soft-deleted it, so its metadata still arrives) and
// "unlisted" (upstream dropped it, so the card is bare) are two facts about
// upstream's data and one fact to the reader: community-scripts does not list
// this app any more. So they share one badge.
//
// The badge does not say deprecated, abandoned, broken or unsafe. The install
// script is still in the repo and still runs, which is why it is neutral
// chrome and does not gate Install.
/**
 * The tag chips, and why there are only three.
 *
 * has_arm and updateable are true on 87% and 97% of the 556 store-visible ct
 * rows, so a chip on the common side would be furniture. Those two render on
 * the RARE side, where the information is. `privileged` is informative on
 * `true` and is the security-relevant one.
 *
 * Every condition is an explicit === true or === false. Null means upstream
 * has no record for the slug and must render NOTHING: `has_arm: null` is not
 * "x86 only" and `privileged: null` is not "unprivileged".
 */
const CHIP = 'inline-block rounded border border-line bg-panel-2 px-1.5 py-0.5 text-[10px] text-text-2'

const UNLISTED_TITLE =
  'community-scripts no longer lists this app. Its install script is still in '
  + 'the repository and still installs. This is about the upstream catalog, '
  + 'not a judgement about the app itself.'

/**
 * The install count, shown as the number it actually is. No banding, no
 * percentile, no rounding to "126k": an invented tier is a judgement the
 * telemetry never made. Gold `text-amber`, 23px glyph, 14px text.
 *
 * Grouping is pinned to en-US, not the reader's locale: a bare
 * toLocaleString() renders this figure as 1,26,196 on an en-IN machine.
 * routes/store-detail.tsx pins the identical call, so a card and the page it
 * links to cannot disagree.
 *
 * Null renders NOTHING: no icon, no zero. Upstream has no measurement for this
 * slug, and a zero would claim nobody installed it. Same rule the tag chips
 * follow.
 */
// The month is a WORD on purpose. "8/13/2026" and "13/8/2026" are the same
// characters rearranged and a reader cannot tell which locale produced them,
// and this date carries the staleness caveat for a figure that can sit a day
// behind upstream. Pinned to en-US identically in routes/store-detail.tsx.
// Only the FORMAT is pinned: the time zone stays the reader's own.
const AS_OF_FMT: Intl.DateTimeFormatOptions = { year: 'numeric', month: 'short', day: 'numeric' }

function InstallCount({ count, syncedAt }: { count: number; syncedAt: string | null }) {
  const shown = count.toLocaleString('en-US')
  const asOf = syncedAt
    ? `, as of ${new Date(syncedAt).toLocaleDateString('en-US', AS_OF_FMT)}`
    : ''
  const caveat =
    `${shown} install runs recorded by community-scripts' opt-in telemetry${asOf}. `
    + 'That counts finished install attempts, failures included, not downloads, '
    + 'and it is not a rating.'
  return (
    // No role="img" here, deliberately. The figure IS text, so it reads
    // correctly on its own; the sr-only prefix supplies the one missing thing,
    // what the number counts, since Icon renders its glyph aria-hidden.
    // role="img" would also collide with the app logo <img> on this card.
    <span title={caveat}
      className="flex shrink-0 items-center gap-1 font-mono text-[14px] text-amber">
      <Icon name="star_shine" size={23} />
      <span className="sr-only">Install runs recorded: </span>
      <span>{shown}</span>
    </span>
  )
}

export function StoreCard({ entry, onInstall, onOpenDetail, installCount }: {
  entry: CatalogRow; onInstall: (slug: string) => void
  /** How many apps are already installed from this catalog entry. A COUNT and
   *  not a flag: installing a second copy is ordinary, so "installed" has to
   *  be something the card SAYS rather than something it does by removing the
   *  Install button. */
  installCount: number
  /** Opens the detail popup. The card navigates nowhere: the same content is
   *  also a route (/store/$slug) for palette results and pasted links, but
   *  from here it opens in a Dialog. */
  onOpenDetail: (slug: string) => void
}) {
  // Where the pointer went down, so a DRAG can be told from a CLICK. Without
  // this, selecting the description text and releasing opens the popup.
  const pressAt = useRef<{ x: number; y: number } | null>(null)

  /**
   * Clicking the card body opens the detail popup, the same as Read more.
   *
   * The container deliberately gets no `role="button"` and no `tabIndex`: that
   * would add a tab stop whose accessible name is the whole card read out as
   * one control, and would nest the Install button inside an interactive
   * element. The title and Read more are already real buttons. Please do not
   * add a tabIndex.
   *
   * Every genuine control inside stops propagation, so exactly one thing
   * happens per click.
   */
  const openFromCardBody = (e: MouseEvent<HTMLDivElement>): void => {
    const from = pressAt.current
    pressAt.current = null
    // A pointer that travelled is a text selection, not a click. 4px of slop
    // covers the hand tremor in an ordinary click.
    if (from && Math.hypot(e.clientX - from.x, e.clientY - from.y) > 4) return
    // Modifier and middle clicks need nothing: `click` never fires for the
    // middle button (that is `auxclick`), and a ctrl/cmd click gets the same
    // popup. There is no URL behind this, so there is no new tab to offer.
    onOpenDetail(entry.slug)
  }

  const name = entry.name ?? entry.slug
  const unlisted = entry.upstream_state === 'delisted' || entry.upstream_state === 'unlisted'
  const reason = entry.unsupported_reason
  return (
    /**
     * ONE FIXED HEIGHT FOR EVERY CARD, so a 10-line description next to a
     * 2-line one stops leaving a hole in the grid. Everything above the
     * description is intrinsic, the description is capped at exactly three
     * lines, and a flex spacer below "Read more" swallows the rest, which
     * pins the chip row and the action row to one baseline across a row.
     *
     * 240px, derived from the built stylesheet (--spacing .25rem, body
     * line-height the unitless 1.45):
     *
     *   32.00  p-4, top and bottom
     *   40.00  header row: max(h-10 icon tile 40, install count 23)
     *   28.30  name: mt-2 8 + 14px * 1.45 line box
     *   15.95  category: 11px * 1.45
     *   57.00  description: mt-1 4 + the fixed h-[53px] box
     *   29.05  action row: mt-1 4 + xs Button (py-1.5 12 + 9px * 1.45)
     *   28.50  chip row: mt-2 8 + bordered chip (border 2 + py-0.5 4 + 14.5)
     *   ------
     *   230.80 worst case, the Install/Installed state
     *
     * Every child above the spacer is shrink-0, so exceeding the budget clips
     * at the card edge instead of drawing text over text. overflow-hidden is
     * that guard, not a plan: the chip row cannot actually wrap, since the
     * widest real combination (type + Privileged + x86 only + No in-place
     * update) is ~282px against a ~365px chip lane at four columns.
     */
    <div
      onPointerDown={(e) => { pressAt.current = { x: e.clientX, y: e.clientY } }}
      onClick={openFromCardBody}
      className="flex h-[240px] cursor-pointer flex-col overflow-hidden rounded-card border border-line-soft bg-panel p-4">
      <div className="flex shrink-0 items-start justify-between gap-2">
        <IconTile name={name} iconUrl={entry.icon_url} size={40} />
        {entry.popularity != null && (
          <InstallCount count={entry.popularity} syncedAt={entry.popularity_synced_at} />
        )}
      </div>
      {/* NO NESTED INTERACTIVES. A control wrapping another control is
          invalid HTML that breaks keyboard and screen-reader behaviour, so the
          title and "Read more" are sibling buttons, each reachable by Tab.
          Truncated to one line with the full name in `title`, since a wrapping
          name would eat into the fixed height. */}
      <button type="button" title={name}
        onClick={(e) => { e.stopPropagation(); onOpenDetail(entry.slug) }}
        className={`mt-2 block shrink-0 cursor-pointer truncate text-left text-[14px] font-semibold hover:underline ${linkCls}`}>
        {name}
      </button>
      <div className="shrink-0 font-mono text-[11px] text-text-3">{entry.category ?? 'Uncategorized'}</div>
      {/* Exactly three lines, always, whether the text needs them or not: a
          fixed box is what makes the rows line up.

          The fade is painted from --panel, the card's own background, so it
          needs no "is it overflowing" condition: over clipped text it reads as
          a fade, over empty space it is the card colour on the card colour,
          and the token keeps that true in both themes. */}
      <div className="relative mt-1 h-[53px] shrink-0 overflow-hidden">
        <p className="line-clamp-3 text-[12px] text-text-2">{entry.description ?? ''}</p>
        <div aria-hidden
          className="pointer-events-none absolute inset-x-0 bottom-0 h-5 bg-[linear-gradient(to_top,var(--panel),transparent)]" />
      </div>
      {/* On every card, including the 7 with no description: the detail page
          still carries their availability, resource defaults and
          popularity. */}
      {/* Read more and the action share ONE row, which is where the height
          came from: it deletes a whole row plus its margin.

          It does NOT go on the chip row, and that was measured. The widest
          real chip combination plus an xs Install is ~342px, which fits at
          four and three columns but WRAPS against the ~295px lane of a
          single-column phone card, and a wrapped chip row is the one thing a
          fixed height cannot absorb.

          The not-installable reason is the hard state: those strings are long,
          so it truncates with the FULL text in `title` and the popup carries
          it complete. The upstream link stays, it is the only outward
          affordance a non-installable app has. */}
      <div className="mt-1 flex shrink-0 items-center gap-2">
        <button type="button"
          onClick={(e) => { e.stopPropagation(); onOpenDetail(entry.slug) }}
          className={`shrink-0 cursor-pointer text-[11.5px] ${amberLinkCls}`}>
          Read more
        </button>
        {entry.installable === false ? (
          <>
            <span className="min-w-0 truncate text-[11.5px] text-text-3"
              title={reason ? `Not installable, ${reason}` : 'Not installable'}>
              Not installable, {entry.unsupported_reason}
            </span>
            {entry.website && (
              <a href={entry.website} target="_blank" rel="noopener noreferrer"
                onClick={(e) => e.stopPropagation()}
                className={`ml-auto shrink-0 text-[11.5px] ${amberLinkCls}`}>upstream</a>
            )}
          </>
        ) : (
          /* size="xs" is the small size in ui/button.tsx, roughly 25px tall
             against md's ~35px, by request. That is well under the ~44px
             normally recommended for a touch target, so it is a deliberately
             small control on a touch screen. */
          <>
            {/* Status, not a control: it reports what exists and never takes
                the action away. The count is the useful half once two copies
                are the point. */}
            {installCount > 0 && (
              <span className="ml-auto shrink-0 rounded-full border border-line-soft
                               px-2 py-0.5 text-[10.5px] text-text-3">
                {installCount === 1 ? 'Installed' : `Installed ×${installCount}`}
              </span>
            )}
            {/* The label stays exactly "Install" in every state; automated
                flows match that exact name. */}
            <Button className={installCount > 0 ? '' : 'ml-auto'} variant="primary" size="xs"
              onClick={(e) => { e.stopPropagation(); onInstall(entry.slug) }}>Install</Button>
          </>
        )}
      </div>
      <div className="mt-2 flex shrink-0 flex-wrap items-center gap-1.5">
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
      {/* Whatever is left over. It is the drift absorber that keeps all three
          action states at one height: the not-installable arm is text (~17px)
          where the other two are a ~25px control. */}
      <div className="flex-1" />
    </div>
  )
}

/**
 * StoreCard's placeholder.
 *
 * `h-[240px]`, the same as the real card, so the Store grid does not resize
 * when the catalog lands; that equality is checked in real Chromium rather
 * than asserted from a class name.
 *
 * The internal rhythm is the card's own budget block for block, down to the
 * fixed 53px description box and the same `flex-1` spacer.
 */
export function StoreCardSkeleton() {
  return (
    <div className="flex h-[240px] flex-col overflow-hidden rounded-card border border-line-soft bg-panel p-4">
      <div className="flex shrink-0 items-start justify-between gap-2">
        <Skeleton className="h-10 w-10 rounded-tile" />
        {/* The install count: a 23px glyph beside a 14px figure. */}
        <Skeleton className="h-[23px] w-16" />
      </div>
      <SkeletonLine className="mt-2 w-1/2 shrink-0 text-[14px]" />
      <SkeletonLine className="w-24 shrink-0 text-[11px]" />
      <div className="mt-1 h-[53px] shrink-0 overflow-hidden text-[12px]">
        <SkeletonLine />
        <SkeletonLine />
        <SkeletonLine className="w-2/3" />
      </div>
      <div className="mt-1 flex shrink-0 items-center gap-2">
        <SkeletonLine className="w-16 text-[11.5px]" />
        {/* size="xs" Button: py-1.5 around a 9px line box, ~25px tall. */}
        <Skeleton className="ml-auto h-[25px] w-14 rounded-ctl" />
      </div>
      <div className="mt-2 flex shrink-0 flex-wrap items-center gap-1.5">
        <Skeleton className="h-[18.5px] w-10" />
        <Skeleton className="h-[20.5px] w-24" />
      </div>
      <div className="flex-1" />
    </div>
  )
}
