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
    // h-14 (not py-2.5): the sidebar sticks below this bar and its offset needs
    // a fixed number to rely on. z-10 suffices: the sidebar is z-index:auto, so
    // any positive z-index paints above it (Radix dialogs portal to the end of
    // document.body, so they paint above regardless).
    <header className="sticky top-0 z-10 flex h-14 items-center gap-3 border-b border-line-soft bg-topbar px-5 backdrop-blur-[10px]">
      {/* GhostMark is the mark's small-screen form: Logo renders ~217px wide at
          h-11 and alone overruns a 375px header beside the other controls. */}
      {/* h-11 sits one step under the h-12 ceiling: growing the mark would grow
          the 56px bar, which the sidebar's top-14 offset depends on. */}
      <Link to={'/hosts' as never} aria-label="Proxploy" className="shrink-0 text-amber">
        <GhostMark className="h-9 w-9 sm:hidden" />
        <Logo className="hidden h-11 w-auto sm:block" />
      </Link>
      {/* A flex-1 lane, not absolute centring, so the box pushes against the
          mark and account menu and collapses when there is no room. */}
      <div className="flex min-w-0 flex-1 justify-center">
        {/* max-w-[330px] is a pure cap: the button is w-full in a min-w-0
            flex-1 lane, so its real width is the lane's leftover and the cap
            never steals space from the controls beside it. */}
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
      {/* Three states: pending -> a placeholder (no claim either way, nothing
          pops in and out); errored -> the bell — not a fail-open, since the
          tray's /jobs is authorised by the backend; not entitled -> no bell.
          has() fail-closes, so gating on it alone would hide the bell while
          /entitlements is in flight or after it 500s. */}
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
