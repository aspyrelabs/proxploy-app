import { useQuery } from '@tanstack/react-query'
import { ThemeToggle } from './ThemeToggle'
import { TierPill } from './TierPill'
import { useEntitlements, useMe } from '../api/hooks'
import { api } from '../api/client'
import type { JobRow } from '../api/jobs'
import { useActivityDrawer } from './ActivityDrawer'
import { openCommandPalette } from './CommandPalette'

export function Topbar() {
  const { data: me } = useMe()
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
    <header className="sticky top-0 z-10 flex items-center justify-end gap-3 border-b border-line-soft bg-topbar px-5 py-2.5 backdrop-blur-[10px]">
      <button
        aria-label="Search (Ctrl+K)"
        onClick={openCommandPalette}
        className="mr-auto flex h-8 items-center gap-1.5 rounded-tile bg-panel-2 px-2.5 text-text-2 hover:bg-elev"
      >
        <span aria-hidden>🔎</span>
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
          <span aria-hidden>🔔</span>
          {count > 0 && (
            <span className="absolute -right-1 -top-1 rounded-full bg-amber px-1 font-mono text-[9px] text-[#20160a]">
              {count}
            </span>
          )}
        </button>
      )}
      <TierPill />
      <ThemeToggle />
      <span className="grid h-8 w-8 place-items-center rounded-tile bg-[linear-gradient(150deg,#5B9DF9,#7C5CFB)] font-display text-[12px] font-semibold text-white">
        {(me?.display_name ?? me?.email ?? '?').slice(0, 1).toUpperCase()}
      </span>
    </header>
  )
}
