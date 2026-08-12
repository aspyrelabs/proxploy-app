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
import Logo from './Logo'

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
    // offset has to be a number something else can rely on. z-20 keeps it over
    // the sidebar, which is itself sticky.
    <header className="sticky top-0 z-20 flex h-14 items-center justify-end gap-3 border-b border-line-soft bg-topbar px-5 backdrop-blur-[10px]">
      <Logo className="h-6 w-auto shrink-0 text-amber" />
      <button
        aria-label="Search (Ctrl+K)"
        onClick={openCommandPalette}
        className="mr-auto flex h-8 items-center gap-1.5 rounded-tile bg-panel-2 px-2.5 text-text-2 hover:bg-elev"
      >
        <MagnifyingGlassIcon aria-hidden className="h-[18px] w-[18px]" />
        <span className="hidden text-[12px] sm:inline">Search</span>
        <span className="hidden rounded-tile border border-line px-1 font-mono text-[10px] text-text-3 sm:inline">
          Ctrl+K
        </span>
      </button>
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
