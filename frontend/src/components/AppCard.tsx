import { useNavigate } from '@tanstack/react-router'
import type { AppRow } from '../api/hooks'
import { fmtPct } from '../lib/format'
import { IconTile } from './IconTile'
import { LifecycleActions } from './LifecycleActions'
import { StatusPill } from './StatusPill'
import { Button } from './ui/button'
import { Skeleton, SkeletonLine, SkeletonMeterRow } from './ui/skeleton'
import { CPU_GRADIENT, RAM_GRADIENT, UsageBar } from './UsageBar'

export function AppCard({ app }: { app: AppRow }) {
  const navigate = useNavigate()
  const memPct = app.mem_bytes != null && app.mem_total_bytes
    ? (app.mem_bytes / app.mem_total_bytes) * 100 : null
  const stopped = app.status !== 'running'
  return (
    <div
      // The only way into app detail, so it has to work without a mouse:
      // NodeCard.tsx does the identical card-as-navigation this way. Space is
      // prevented so the page does not scroll under the press.
      role="link" tabIndex={0}
      aria-label={app.name}
      className={`cursor-pointer rounded-card border border-line-soft bg-panel p-4 transition-transform hover:-translate-y-[3px] motion-reduce:transform-none ${stopped ? 'opacity-70' : ''}`}
      onClick={() => navigate({ to: '/apps/$appId' as never, params: { appId: String(app.id) } as never })}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          navigate({ to: '/apps/$appId' as never, params: { appId: String(app.id) } as never })
        }
      }}
    >
      <div className="flex items-start justify-between">
        {/* The same tile the Store card draws, so an installed app wears the
            logo of the entry it was installed from. `icon_url` is null when
            that entry is gone or has none, and the initials tile takes over. */}
        <IconTile name={app.name} iconUrl={app.icon_url} size={40}
                  initials={app.icon_initials} colors={app.icon_colors} />
        {app.update_available && (
          <span className="rounded bg-amber-dim px-1.5 py-0.5 font-mono text-[9.5px] uppercase text-amber">
            update
          </span>
        )}
      </div>
      <div className="mt-2 text-[14px] font-semibold text-text">{app.name}</div>
      <div className="font-mono text-[11px] text-text-3">
        {app.host_name} · CT {app.ctid}
      </div>
      <div className="mt-2"><StatusPill status={app.status} /></div>
      <div className="mt-3 space-y-2">
        <div className="flex items-center gap-2">
          <span className="w-8 text-[10.5px] uppercase text-text-3">CPU</span>
          <div className="flex-1"><UsageBar pct={app.cpu_pct} gradient={CPU_GRADIENT} /></div>
          <span className="w-9 text-right font-mono text-[11px] text-text-2">{fmtPct(app.cpu_pct)}</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="w-8 text-[10.5px] uppercase text-text-3">RAM</span>
          <div className="flex-1"><UsageBar pct={memPct} gradient={RAM_GRADIENT} /></div>
          <span className="w-9 text-right font-mono text-[11px] text-text-2">{fmtPct(memPct)}</span>
        </div>
      </div>
      <div className="mt-3 border-t border-line-soft pt-3 flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
        <LifecycleActions target="app" id={app.id} name={app.name} status={app.status} size="sm" />
        <Button variant="ghost" className="px-2 py-1 text-[11px]"
          onClick={() => navigate({ to: '/apps/$appId/console' as never, params: { appId: String(app.id) } as never })}>
          Console
        </Button>
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
      </div>
      {/* LifecycleActions + Console, both `px-2 py-1 text-[11px]` ghosts, so
          ~24px tall. */}
      <div className="mt-3 flex items-center gap-2 border-t border-line-soft pt-3">
        <Skeleton className="h-6 w-16 rounded-ctl" />
        <Skeleton className="h-6 w-20 rounded-ctl" />
      </div>
    </div>
  )
}
