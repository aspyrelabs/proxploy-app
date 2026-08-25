import { useNavigate } from '@tanstack/react-router'
import type { AppRow } from '../api/hooks'
import { fmtBps, fmtBytes, fmtPct } from '../lib/format'
import { openConsoleWindow } from '../lib/console-window'
import { ConsoleButton, LifecycleActions } from './LifecycleActions'
import { IconTile } from './IconTile'
import { StatusPill } from './StatusPill'
import { UpdateDot } from './UpdateDot'
import { Skeleton, SkeletonLine, SkeletonMeterRow } from './ui/skeleton'
import { CPU_GRADIENT, RAM_GRADIENT, STORAGE_GRADIENT, UsageBar } from './UsageBar'

export function AppCard({ app }: { app: AppRow }) {
  const navigate = useNavigate()
  const memPct = app.mem_bytes != null && app.mem_total_bytes
    ? (app.mem_bytes / app.mem_total_bytes) * 100 : null
  const diskPct = app.disk_bytes != null && app.disk_total_bytes
    ? (app.disk_bytes / app.disk_total_bytes) * 100 : null
  const stopped = app.status !== 'running'
  // App detail is a row that expands on the Apps table now, not a page, so
  // both the click and the keyboard path land on the same search param.
  const open = () => navigate({ to: '/apps' as never, search: { open: app.id } as never })
  return (
    <div
      // The only way into app detail, so it has to work without a mouse:
      // NodeCard.tsx does the identical card-as-navigation this way. Space is
      // prevented so the page does not scroll under the press.
      role="link" tabIndex={0}
      aria-label={app.name}
      className={`cursor-pointer rounded-card border border-line-soft bg-panel p-4 transition-transform hover:-translate-y-[3px] motion-reduce:transform-none ${stopped ? 'opacity-70' : ''}`}
      onClick={() => open()}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          open()
        }
      }}
    >
      <div className="flex items-start justify-between">
        {/* The same tile the Store card draws, so an installed app wears the
            logo of the entry it was installed from. `icon_url` is null when
            that entry is gone or has none, and the initials tile takes over. */}
        <IconTile name={app.name} iconUrl={app.icon_url} size={40}
                  initials={app.icon_initials} colors={app.icon_colors} />
        {app.update_available && <UpdateDot />}
      </div>
      <div className="mt-2 text-[14px] font-semibold text-text">{app.name}</div>
      <div className="font-mono text-[11px] text-text-3">
        {app.host_name} · CT {app.ctid}
      </div>
      <div className="mt-2"><StatusPill status={app.status} /></div>
      <div className="mt-3 space-y-2">
        <div className="flex items-center gap-2">
          <span className="w-8 text-[10.5px] uppercase text-text-3">CPU</span>
          <div className="flex flex-1 items-center gap-[3px]">
            <div className="flex-1"><UsageBar pct={app.cpu_pct} gradient={CPU_GRADIENT} /></div>
            <span className="w-9 text-right font-mono text-[11px] text-text-2">{fmtPct(app.cpu_pct)}</span>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className="w-8 text-[10.5px] uppercase text-text-3">RAM</span>
          <div className="flex flex-1 items-center gap-[3px]">
            <div className="flex-1"><UsageBar pct={memPct} gradient={RAM_GRADIENT} /></div>
            <span className="w-9 text-right font-mono text-[11px] text-text-2">{fmtPct(memPct)}</span>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className="w-8 text-[10.5px] uppercase text-text-3">DSK</span>
          <div className="flex flex-1 items-center gap-[3px]">
            <div className="flex-1"><UsageBar pct={diskPct} gradient={STORAGE_GRADIENT} /></div>
            <span className="w-9 text-right font-mono text-[11px] text-text-2">{fmtPct(diskPct)}</span>
          </div>
        </div>
        <div className="font-mono text-[11px] text-text-2">
          {app.disk_total_bytes
            ? `${fmtBytes(app.disk_bytes)} / ${fmtBytes(app.disk_total_bytes)}`
            : fmtBytes(app.disk_bytes)}
        </div>
        {/* No bar for network: there is no denominator. Inventing a link
            speed to draw against would be making up a number, which is the
            same call GuestList makes about VM memory. */}
        <div className="flex items-center gap-2">
          <span className="w-8 text-[10.5px] uppercase text-text-3">NET</span>
          <span className="font-mono text-[11px] text-text-2">↓ {fmtBps(app.net_in_bps)}</span>
          <span className="font-mono text-[11px] text-text-2">↑ {fmtBps(app.net_out_bps)}</span>
        </div>
      </div>
      <div className="mt-3 border-t border-line-soft pt-3 flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
        <LifecycleActions target="app" id={app.id} name={app.name} status={app.status} hostId={app.host_id} size="sm" />
        {/* A window of its own, never a route: the in-page console tab is
            gone (lib/console-window.ts). */}
        <ConsoleButton hostId={app.host_id}
          onClick={() => openConsoleWindow('app', app.id)} />
      </div>
    </div>
  )
}

/**
 * AppCard's placeholder, kept in this file so the two are edited together:
 * every wrapper class, margin and font size below is copied from the card
 * above, which is the only way the placeholder ends up the same height as the
 * thing it stands in for. If you change the card, change this.
 *
 * The one thing it does not reproduce is the `update` badge, which is
 * conditional on the real card too, so the header row is the icon tile's 40px
 * either way.
 */
export function AppCardSkeleton() {
  return (
    <div className="rounded-card border border-line-soft bg-panel p-4">
      <div className="flex items-start justify-between">
        <Skeleton className="h-10 w-10 rounded-tile" />
      </div>
      <SkeletonLine className="mt-2 w-28 text-[14px]" />
      <SkeletonLine className="w-36 text-[11px]" />
      {/* StatusPill: px-2 py-0.5 around a 10.5px line box. */}
      <div className="mt-2"><Skeleton className="h-[19px] w-20 rounded-full" /></div>
      <div className="mt-3 space-y-2">
        <SkeletonMeterRow />
        <SkeletonMeterRow />
        <SkeletonMeterRow />
        <SkeletonLine className="w-28 text-[11px]" />
        <SkeletonLine className="w-40 text-[11px]" />
      </div>
      {/* LifecycleActions (size="sm") + the Console ghost, both 32px: h-8 is
          measured off a real rendered sm button, not computed. These were h-6
          on the old belief that `px-2 py-1 text-[11px]` made a ~24px control;
          that className never applied, so the real bar was 37px. */}
      <div className="mt-3 flex items-center gap-2 border-t border-line-soft pt-3">
        <Skeleton className="h-8 w-16 rounded-ctl" />
        <Skeleton className="h-8 w-20 rounded-ctl" />
      </div>
    </div>
  )
}
