import { Icon } from './ui/icon'
import { BellPopover } from './BellPopover'
import { ThemeToggle } from './ThemeToggle'
import { TierPill } from './TierPill'
import { useEntitlements } from '../api/hooks'
import { AccountMenu } from './AccountMenu'
import { openCommandPalette } from './CommandPalette'
import { Link } from '@tanstack/react-router'
import Logo, { GhostMark } from './Logo'

export function Topbar() {
  const { has } = useEntitlements()
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
      {/* GhostMark below sm: Logo's viewBox (aspect ratio 5.6) renders it
          134px wide at h-6, which alone overruns a 375px header once search,
          bell, tier pill, theme toggle and avatar are laid out beside it.
          The ghost is the mark's small-screen form (see Logo.tsx); swapping
          to it below sm keeps the same h-6 footprint down to a 24px square. */}
      {/* h-9 is the tallest the mark can be without changing the bar: the
          header is h-14 (56px) and items-center, so a 36px mark leaves exactly
          10px above and below it. Growing the mark must not grow the bar:
          the sidebar sticks at top-14 and its height is calc(100vh-3.5rem),
          both of which are that 56px. */}
      <Link to={'/hosts' as never} aria-label="Proxploy" className="shrink-0 text-amber">
        <GhostMark className="h-9 w-9 sm:hidden" />
        <Logo className="hidden h-9 w-auto sm:block" />
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
      {has('notify.inapp') && <BellPopover />}
      <ThemeToggle />
      <AccountMenu />
    </header>
  )
}
