import { Icon } from './ui/icon'
import { BellPopover } from './BellPopover'
import { ThemeToggle } from './ThemeToggle'
import { TierPill } from './TierPill'
import { useEntitlements } from '../api/hooks'
import { AccountMenu } from './AccountMenu'
import { Skeleton, SkeletonGroup } from './ui/skeleton'
import { openCommandPalette } from './CommandPalette'
import { Link } from '@tanstack/react-router'
import Logo, { GhostMark } from './Logo'

export function Topbar() {
  const ent = useEntitlements()
  return (
    // h-14 rather than py-2.5: the sidebar now sticks BELOW this bar, so its
    // offset has to be a number something else can rely on. z-10 is enough to
    // stay above it: a sticky element with z-index:auto paints in stacking
    // step 8, any positive z-index in step 9, and the sidebar is still
    // z-index:auto. (Radix dialogs are also z-index'd, but that tie doesn't
    // matter here either: Radix portals them to the end of document.body,
    // later in tree order, so they paint above this header regardless of
    // what z-index either one carries.)
    // justify-end is gone with the search lane's arrival: a flex-1 child
    // absorbs every pixel of free space, so there is nothing left to justify.
    <header className="sticky top-0 z-10 flex h-14 items-center gap-3 border-b border-line-soft bg-topbar px-5 backdrop-blur-[10px]">
      {/* GhostMark below sm: Logo's viewBox (aspect ratio ~4.9) renders it
          217px wide at h-11, which alone overruns a 375px header once search,
          bell, tier pill, theme toggle and avatar are laid out beside it.
          The ghost is the mark's small-screen form (see Logo.tsx); swapping
          to it below sm keeps the mark square down to a 36px footprint. */}
      {/* h-11 (44px) in an h-14 (56px) items-center header leaves 6px above and
          below. Growing the mark must not grow the BAR: the sidebar sticks at
          top-14 and its height is calc(100vh-3.5rem), both of which are that
          56px, so h-12 is the hard ceiling and this sits one step under it.
          The artwork itself carries no padding any more (the source files were
          a 1024x768 canvas holding a 201-unit-tall lockup, so 74% of every
          rendered pixel was empty and the mark looked tiny at any height). */}
      <Link to={'/hosts' as never} aria-label="Proxploy" className="shrink-0 text-amber">
        <GhostMark className="h-9 w-9 sm:hidden" />
        <Logo className="hidden h-11 w-auto sm:block" />
      </Link>
      {/* Centred in a flex-1 lane rather than absolutely positioned: the bar
          already overran a 375px phone once, and an absolutely-centred control
          would sit under the mark and the account menu instead of pushing
          against them. The lane centres the box between the two groups and
          still collapses cleanly when there is no room. */}
      <div className="flex min-w-0 flex-1 justify-center">
        {/* max-w is 1.5x what it was (220px -> 330px), and it needed no
            responsive clamp to stay safe. The cap is the only thing that
            changed: the button is `w-full` inside a `min-w-0 flex-1` lane, so
            its real width has always been whatever the lane has left after the
            mark, tier pill, bell, theme toggle and avatar are laid out. Below
            ~330px of free space the cap never binds and the button simply
            fills the lane, exactly as before, so nothing is crowded or
            overflowed at narrow viewports; above it, the box is half again as
            wide. Growing this does not take space from the controls beside it
            either, since flex-1 sizes the lane before the cap applies inside
            it. */}
        <button
          aria-label="Search (Ctrl+K)"
          onClick={openCommandPalette}
          className="flex h-8 w-full max-w-[330px] items-center gap-1.5 rounded-tile bg-panel-2 px-2.5 text-text-2 hover:bg-elev"
        >
          <Icon name="search" className="shrink-0" />
          <span className="hidden text-[12px] sm:inline">Search</span>
          {/* ml-auto, not a gap: the box is now wider than its contents, so the
              shortcut belongs against the right edge rather than floating
              beside the word. */}
          <span className="ml-auto hidden shrink-0 rounded-tile border border-line px-1 font-mono text-[10px] text-text-3 sm:inline">
            Ctrl+K
          </span>
        </button>
      </div>
      <TierPill />
      {/* Three states, not two. api/hooks.ts keeps has() fail-closed on
          purpose, but that is a security default and not a statement of
          fact, so gating the bell on it alone read "your plan does not
          include this" for every plan while /entitlements was in flight,
          and forever if that request failed. A user whose entitlements call
          500s then had no surface at all telling them whether their install
          worked, and nothing explaining why it had gone.

          pending  -> a placeholder the size of the bell, same answer
                      TierPill gives beside it: no claim either way, and no
                      control popping in and out of the bar.
          errored  -> the bell. Not a fail-open: what the tray shows is
                      /jobs, which the backend authorises on its own, so
                      nothing here unlocks anything the server would refuse.
                      Hiding it would assert a plan limit we could not check.
          not entitled (data read, feature absent) -> no bell, as before. */}
      {ent.isPending ? (
        <SkeletonGroup label="Checking your plan" className="shrink-0">
          <Skeleton className="h-8 w-8 rounded-tile" />
        </SkeletonGroup>
      ) : (ent.data == null || ent.has('notify.inapp')) && <BellPopover />}
      <ThemeToggle />
      <AccountMenu />
    </header>
  )
}
