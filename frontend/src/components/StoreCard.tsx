import { useRef } from 'react'
import type { MouseEvent } from 'react'
import type { CatalogRow } from '../api/catalog'
import { IconTile } from './IconTile'
import { Button } from './ui/button'
import { Icon } from './ui/icon'
import { Skeleton, SkeletonLine } from './ui/skeleton'

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
 * "unprivileged". Testing falsiness here would silently label all 7 of them
 * with claims nobody has made.
 */
const CHIP = 'inline-block rounded border border-line bg-panel-2 px-1.5 py-0.5 text-[10px] text-text-2'

const UNLISTED_TITLE =
  'community-scripts no longer lists this app. Its install script is still in '
  + 'the repository and still installs. This is about the upstream catalog, '
  + 'not a judgement about the app itself.'

/**
 * The install count, shown as the number it actually is.
 *
 * This slot briefly carried invented tiers ("Top 10%", then "Popular" /
 * "Common"). Those were labels WE made up on top of the data: a reader cannot
 * check them, cannot say what separates Popular from Common, and the words
 * imply a judgement the telemetry never made. The underlying number is the
 * quantifiable thing, so the number is what shows. No banding, no percentile,
 * no rounding to "126k" either, since an abbreviation is just a coarser band
 * wearing a number's clothes.
 *
 * Gold `text-amber` at 23px glyph and 14px text, which is the sizing that was
 * asked for and has not changed.
 *
 * Grouping is pinned to en-US rather than the reader's own locale, by
 * decision. A bare toLocaleString() follows the runtime locale, which on an
 * en-IN machine renders this same figure as 1,26,196 (lakh grouping). Both
 * forms are correct; one form everywhere is the choice, and routes/
 * store-detail.tsx pins the identical call for the same figure so the card
 * and the page it links to can never disagree.
 *
 * Null renders NOTHING at all: no icon, no zero. Absence means upstream has no
 * measurement for this slug, and a zero would be a claim that nobody installed
 * it. That rule is the same one the tag chips follow for their own nulls.
 *
 * Every caveat lives in the tooltip rather than inline on the card: what the
 * number counts is a real footnote, but it is a footnote, and the card has
 * 284px to spend.
 */
// Pinned to en-US, identically in routes/store-detail.tsx, for the same reason
// the install count above is pinned: one rendering for every reader rather
// than one per locale, and the two files must agree because a card links
// straight to that page.
//
// The month is a WORD on purpose. "8/13/2026" and "13/8/2026" are the same
// nine characters rearranged, and a reader cannot tell which locale produced
// them; this date carries the staleness caveat for a figure that can sit a
// day behind upstream, so being misread by half the world is not cosmetic.
// Only the FORMAT is pinned, never the instant: the time zone stays the
// reader's own, as it is everywhere else in the app.
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
    // correctly on its own; the only thing missing for a screen reader is what
    // the number counts, since Icon renders its glyph aria-hidden. An sr-only
    // prefix supplies that. role="img" would also have collided with the app
    // logo <img> on the same card, making getByRole('img') ambiguous for
    // anything querying the logo.
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
   *  not a flag: installing a second copy is ordinary (a test one beside a
   *  prod one, or somebody's own naming scheme), so "installed" has to be
   *  something the card SAYS rather than something it does by removing the
   *  Install button. */
  installCount: number
  /** Opens the detail popup. The card navigates nowhere: the same content is
   *  also a route (/store/$slug) for palette results and pasted links, but
   *  from here it opens in a Dialog. */
  onOpenDetail: (slug: string) => void
}) {
  // Where the pointer went down, so a DRAG can be told from a CLICK. Without
  // this, selecting the description text and releasing opens the popup, which
  // is a small thing that is very irritating when it happens.
  const pressAt = useRef<{ x: number; y: number } | null>(null)

  /**
   * Clicking the card body opens the detail popup, the same as Read more.
   *
   * This is mouse convenience on the container and real semantics on the
   * children, DELIBERATELY split that way. The container gets no
   * `role="button"` and no `tabIndex`: that would add a redundant tab stop
   * whose accessible name is the entire card read out as one control, and it
   * would nest the Install button inside an interactive element in the
   * accessibility tree even though the DOM stays valid. The keyboard path
   * already exists and is better, because the title and Read more are real
   * buttons. Please do not "fix" this by adding a tabIndex.
   *
   * Every genuine control inside stops propagation, so exactly one thing
   * happens per click: Install installs without also opening the popup behind
   * its own dialog, and the upstream link leaves for upstream without opening
   * anything here.
   */
  const openFromCardBody = (e: MouseEvent<HTMLDivElement>): void => {
    const from = pressAt.current
    pressAt.current = null
    // A pointer that travelled is a text selection, not a click. 4px of slop
    // covers the hand tremor in an ordinary click.
    if (from && Math.hypot(e.clientX - from.x, e.clientY - from.y) > 4) return
    // Modifier and middle clicks: `click` does not fire for the middle button
    // at all (that is `auxclick`), and a ctrl/cmd click gets the same popup as
    // a plain one. There is no URL behind this, so there is no new tab to
    // offer and nothing surprising to suppress.
    onOpenDetail(entry.slug)
  }

  const name = entry.name ?? entry.slug
  const unlisted = entry.upstream_state === 'delisted' || entry.upstream_state === 'unlisted'
  const reason = entry.unsupported_reason
  return (
    /**
     * ONE FIXED HEIGHT FOR EVERY CARD, so a 10-line description next to a
     * 2-line one stops leaving a hole in the grid. The height is spent in
     * this order: everything above the description is intrinsic, the
     * description is capped at exactly three lines, and a flex spacer below
     * "Read more" swallows whatever is left, which is what pins the chip row
     * and the action row to the same baseline on every card in a row.
     *
     * 240px, down from 284px originally, via a wrong 224px that shipped an
     * overlap. The saving is real (Install moved onto the "Read more" row,
     * deleting a whole row and its margin) but the first budget for it was
     * arithmetic, not measurement, and it was WRONG: it counted the name as
     * 20px and forgot the `mt-2` above it entirely, then rounded the category
     * and chip rows down. That left 3px of nominal slack against a true
     * requirement of ~231px, so five compressible children shrank to fit and
     * squeezed their line boxes into each other. `overflow-hidden` then hid
     * the evidence at the card edge instead of showing it.
     *
     * Re-derived from the built stylesheet rather than from memory
     * (--spacing is .25rem, body line-height is the unitless 1.45):
     *
     *   32.00  p-4, top and bottom
     *   40.00  header row: max(h-10 icon tile 40, install count 23)
     *   28.30  name: mt-2 8 + 14px * 1.45 line box   <- the 8 that was missed
     *   15.95  category: 11px * 1.45
     *   57.00  description: mt-1 4 + the fixed h-[53px] box
     *   29.05  action row: mt-1 4 + xs Button (py-1.5 12 + 9px * 1.45)
     *   28.50  chip row: mt-2 8 + bordered chip (border 2 + py-0.5 4 + 14.5)
     *   ------
     *   230.80 worst case, which is the Install/Installed state
     *
     * These are CSS-determined, not glyph-determined: a unitless line-height
     * times a px font size is exact, and the icon carries an explicit 23px
     * box, so the figures are firm to the sub-pixel rather than estimates.
     * The one I would least defend is the chip row, since a future chip with
     * different padding moves it. The not-installable state is SHORTER
     * (~20.7px action row, being text rather than a control), which the
     * spacer below absorbs.
     *
     * 240 leaves ~9px of genuine headroom. Every child above the spacer is
     * now shrink-0, so if a future change does exceed the budget the result
     * is honest clipping at the card edge, never text drawn over text.
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
      {/* NO NESTED INTERACTIVES. The card is not itself a control: it already
          contains a real Install button, and a control wrapping another
          control is invalid HTML that breaks keyboard and screen-reader
          behaviour. The title and "Read more" are two sibling buttons
          instead, so every control here is a sibling of the others and each
          is reachable by Tab in reading order.
          Both open the detail popup rather than navigating: buttons, not
          links, because they no longer go anywhere. Truncated to one line
          with the full name in `title`, since a wrapping name would eat into
          the fixed height. */}
      <button type="button" title={name}
        onClick={(e) => { e.stopPropagation(); onOpenDetail(entry.slug) }}
        className="mt-2 block shrink-0 cursor-pointer truncate text-left text-[14px] font-semibold text-text hover:text-amber hover:underline">
        {name}
      </button>
      <div className="shrink-0 font-mono text-[11px] text-text-3">{entry.category ?? 'Uncategorized'}</div>
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
      {/* Read more and the action share ONE row, which is where the height
          came from: it deletes a whole row plus its margin, and moves Install
          up, which is what was asked for.

          It does NOT go on the chip row, and that was measured rather than
          assumed. The widest real chip combination (type + Privileged + x86
          only + No in-place update) is ~281px, and an xs Install is ~53px
          plus an 8px gap. Against the chip lane that is 342 vs 365 at four
          columns (fits), 342 vs 343 at three (fits by one pixel, which is
          inside the error of these estimates), and 342 vs 295 on a
          single-column phone card, where it WRAPS. A wrapped chip row is the
          one thing a fixed height cannot absorb, so the chip row keeps the
          full width it needs to stay on one line, and the button sits here
          instead. On this row the same worst case is Read more (~54px) plus
          the control (~53px), which is 115px against that same 295px lane.

          All three action states share this row and it stays one line in each:
          - installable      the Install button, pushed right with ml-auto.
          - installed        the same slot, disabled.
          - NOT installable  the reason, which is the hard one. These strings
            are long, so it truncates with the FULL text in `title`, and the
            popup carries it complete in its Availability section. Truncating
            text whose full form is one click away is honest; wrapping it
            would make this card taller than every other card in its row.

          The upstream link stays. It is the only outward affordance a
          non-installable app has, it costs one shrink-0 element, and dropping
          it would be a capability removal dressed up as a layout change. */}
      <div className="mt-1 flex shrink-0 items-center gap-2">
        <button type="button"
          onClick={(e) => { e.stopPropagation(); onOpenDetail(entry.slug) }}
          className="shrink-0 cursor-pointer text-[11.5px] text-amber hover:underline">
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
                className="ml-auto shrink-0 text-[11.5px] text-amber hover:underline">upstream</a>
            )}
          </>
        ) : (
          /* size="xs" is the small size in ui/button.tsx: roughly 25px tall
             against md's ~35px, by request. Worth knowing: that is still well
             under the ~44px normally recommended for a touch target, so it is
             a deliberately small control on a touch screen. The LABEL is
             untouched: e2e/journey.spec.ts clicks
             getByRole('button', { name: 'Install', exact: true }). */
          <>
            {/* Status, not a control: it reports what exists and never takes
                the action away. The count is the useful half once two copies
                are the point, since "Installed" alone cannot answer "is the
                prod one already there". */}
            {installCount > 0 && (
              <span className="ml-auto shrink-0 rounded-full border border-line-soft
                               px-2 py-0.5 text-[10.5px] text-text-3">
                {installCount === 1 ? 'Installed' : `Installed ×${installCount}`}
              </span>
            )}
            {/* Label stays exactly "Install" in every state: e2e/journey.spec.ts
                clicks getByRole('button', { name: 'Install', exact: true }). */}
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
      {/* Whatever is left over, which is now a few pixels rather than the ~34
          this used to hold. It stays because it is the drift absorber that
          keeps all three action states at one height: the not-installable arm
          is text (~17px) where the other two are a ~25px control, and this
          swallows that 8px difference instead of letting it reach the card
          edge. */}
      <div className="flex-1" />
    </div>
  )
}

/**
 * StoreCard's placeholder.
 *
 * The easiest of the four to get right and the one it matters most for: the
 * real card is `h-[240px]` and so is this, so the Store grid does not resize
 * when the catalog lands. e2e/harness/main.tsx renders it beside the real
 * card at every viewport width, and `npm run harness` fails on unequal
 * heights among `.rounded-card` matches, so that equality is checked in real
 * Chromium rather than asserted from a class name.
 *
 * The internal rhythm is the card's own budget, block for block: 40px header,
 * name, category, the fixed 53px three-line description box, the action row
 * (~25px xs Button), the chip row, and the same `flex-1` spacer soaking up
 * what is left.
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
