import { ThemeToggle } from './ThemeToggle'
import { TierPill } from './TierPill'
import { useEntitlements, useMe } from '../api/hooks'
import { useActivity } from '../api/jobs'
import { useActivityDrawer } from './ActivityDrawer'

export function Topbar() {
  const { data: me } = useMe()
  const { has } = useEntitlements()
  const drawer = useActivityDrawer()
  // Doc 06 §d gates the ['jobs'] 10s poll to "while the activity drawer is
  // open, else never" — useJobs({enabled}) couples fetch-at-all to that same
  // poll, so the always-mounted bell can't use it without leaving a poll
  // running on every page. useActivity already polls unconditionally at 30s
  // (a separate, pre-existing budget line) and carries running jobs, so the
  // bell rides that instead of opening a second permanent ['jobs'] poll.
  const { data: activity } = useActivity()
  const count = activity?.filter(
    (a) => a.kind === 'job' && (a.status === 'running' || a.status === 'queued'),
  ).length ?? 0
  return (
    <header className="sticky top-0 z-10 flex items-center justify-end gap-3 border-b border-line-soft bg-[rgba(11,15,22,.82)] px-5 py-2.5 backdrop-blur-[10px]">
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
