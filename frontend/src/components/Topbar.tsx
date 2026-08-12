import { useQuery } from '@tanstack/react-query'
import { BellIcon, MagnifyingGlassIcon } from '@heroicons/react/24/outline'
import { ThemeToggle } from './ThemeToggle'
import { TierPill } from './TierPill'
import { useEntitlements } from '../api/hooks'
import { AccountMenu } from './AccountMenu'
import { api } from '../api/client'
import type { JobRow } from '../api/jobs'
import { useActivityDrawer } from './ActivityDrawer'
import { openCommandPalette } from './CommandPalette'
import { Link } from '@tanstack/react-router'
import Logo, { GhostMark } from './Logo'

export function Topbar() {
  const { has } = useEntitlements()
  const drawer = useActivityDrawer()
  // GET /cluster/activity applies LIMIT 20 to its jobs subquery ordered by
  // created_at desc, so a long-running job older (by creation time) than the
  // 20 most-recently-created jobs would silently drop out of that feed while
  // still running. The bell's count needs to be unbounded, so it runs its own
  // one-shot query against /jobs?status=running instead of riding useActivity
  // or useJobs({status}), the latter couples fetch-at-all to the drawer's
  // 10s-while-open poll (doc 06 §d), which this always-mounted bell must not
  // trigger unconditionally.
  const { data: running } = useQuery({
    queryKey: ['jobs', 'running-count'],
    queryFn: () => api<JobRow[]>('/jobs?status=running'),
    refetchInterval: 30_000,
  })
  const count = running?.length ?? 0
  return (
    // h-14 rather than py-2.5: the sidebar now sticks BELOW this bar, so its
    // offset has to be a number something else can rely on. z-10 is enough to
    // stay above it: a sticky element with z-index:auto paints in stacking
    // step 8, any positive z-index in step 9, and the sidebar is still
    // z-index:auto. (The activity drawer's sheet is also z-index'd, but that
    // tie doesn't matter here either — Radix portals it to the end of
    // document.body, later in tree order, so it paints above this header
    // regardless of what z-index either one carries.)
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
          10px above and below it. Growing the mark must not grow the bar —
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
        <button
          aria-label="Search (Ctrl+K)"
          onClick={openCommandPalette}
          className="flex h-8 w-full max-w-[220px] items-center gap-1.5 rounded-tile bg-panel-2 px-2.5 text-text-2 hover:bg-elev"
        >
          <MagnifyingGlassIcon aria-hidden className="h-[18px] w-[18px] shrink-0" />
          <span className="hidden text-[12px] sm:inline">Search</span>
          {/* ml-auto, not a gap: the box is now wider than its contents, so the
              shortcut belongs against the right edge rather than floating
              beside the word. */}
          <span className="ml-auto hidden shrink-0 rounded-tile border border-line px-1 font-mono text-[10px] text-text-3 sm:inline">
            Ctrl+K
          </span>
        </button>
      </div>
      {has('notify.inapp') && (
        <button
          aria-label="Activity"
          onClick={drawer.toggle}
          className="relative grid h-8 w-8 place-items-center rounded-tile bg-panel-2 text-text-2 hover:bg-elev"
        >
          <BellIcon aria-hidden className="h-[18px] w-[18px]" />
          {count > 0 && (
            <span className="absolute -right-1 -top-1 rounded-full bg-amber px-1 font-mono text-[9px] text-[#20160a]">
              {count}
            </span>
          )}
        </button>
      )}
      <TierPill />
      <ThemeToggle />
      <AccountMenu />
    </header>
  )
}
