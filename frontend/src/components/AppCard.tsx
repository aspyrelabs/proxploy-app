import { useNavigate } from '@tanstack/react-router'
import type { AppRow } from '../api/hooks'
import { fmtPct } from '../lib/format'
import { LifecycleActions } from './LifecycleActions'
import { StatusPill } from './StatusPill'
import { CPU_GRADIENT, RAM_GRADIENT, UsageBar } from './UsageBar'

function initials(app: AppRow): string {
  return app.icon_initials ?? app.name.slice(0, 2).toUpperCase()
}

export function AppCard({ app }: { app: AppRow }) {
  const navigate = useNavigate()
  const memPct = app.mem_bytes != null && app.mem_total_bytes
    ? (app.mem_bytes / app.mem_total_bytes) * 100 : null
  const stopped = app.status !== 'running'
  return (
    <div
      className={`cursor-pointer rounded-card border border-line-soft bg-panel p-4 transition-transform hover:-translate-y-[3px] motion-reduce:transform-none ${stopped ? 'opacity-70' : ''}`}
      onClick={() => navigate({ to: '/apps/$appId' as never, params: { appId: String(app.id) } as never })}
    >
      <div className="flex items-start justify-between">
        <div
          className="flex h-10 w-10 items-center justify-center rounded-tile font-display text-[14px] font-semibold text-white"
          style={{
            background: app.icon_colors
              ? `linear-gradient(135deg, ${app.icon_colors.c1}, ${app.icon_colors.c2})`
              : 'linear-gradient(135deg,#F5B544,#E0862B)',
          }}
        >
          {initials(app)}
        </div>
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
      <div className="mt-3 border-t border-line-soft pt-3" onClick={(e) => e.stopPropagation()}>
        <LifecycleActions target="app" id={app.id} name={app.name} status={app.status} size="sm" />
      </div>
    </div>
  )
}
