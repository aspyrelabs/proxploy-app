import { useNavigate } from '@tanstack/react-router'
import type { AppRow } from '../api/hooks'
import { statusLabel } from '../lib/activityDisplay'
import { AppIconMenu } from './AppIconMenu'
import { IconTile } from './IconTile'
import { Icon } from './ui/icon'
import { Skeleton, SkeletonLine } from './ui/skeleton'

/**
 * State, as a glyph and the word, for the icon grid.
 *
 * The COLOURS are StatusPill's, and the WORD is statusLabel's, so this view
 * cannot drift from the status vocabulary the rest of the app uses.
 *
 * Every status gets its own entry rather than collapsing to running/stopped:
 * paused and unknown are not "not running", and an operator who cannot tell
 * them apart cannot tell a container someone suspended from one PVE has lost
 * track of. `icon:` is the field shape scripts/icon-names.mjs reads, which is
 * why these are literals in a table rather than a computed name.
 *
 * `pending` is not one of StatusPill's STYLES keys either (it falls to its
 * `unknown` grey there): it is the optimistic patch useLifecycle applies for
 * the span between a click and the job's own resolution, covered here for
 * the same reason. `connected`/`online` are node-only statuses StatusPill
 * also carries, never a value AppRow.status takes, so they are left out.
 */
const STATE: Record<string, { icon: string; cls: string }> = {
  running: { icon: 'play_arrow', cls: 'text-green' },
  paused: { icon: 'pause', cls: 'text-amber' },
  stopped: { icon: 'stop', cls: 'text-text-3' },
  pending: { icon: 'hourglass_empty', cls: 'text-text-3' },
  error: { icon: 'error', cls: 'text-red' },
  unknown: { icon: 'help', cls: 'text-text-3' },
}

export function AppIconGrid({ apps }: { apps: AppRow[] }) {
  return (
    <div className="grid grid-cols-1 gap-x-6 gap-y-4 rounded-card border border-line-soft
                    bg-panel p-4 sm:grid-cols-2 xl:grid-cols-4">
      {apps.map((a) => <AppIconCell key={a.id} app={a} />)}
    </div>
  )
}

function AppIconCell({ app }: { app: AppRow }) {
  const navigate = useNavigate()
  const state = STATE[app.status] ?? STATE.unknown
  return (
    <div className="flex items-center gap-3">
      {/* The logo is the menu. Nothing is drawn ON it: the tile is the app's
          own artwork and a badge over it would compete with whatever the
          logo already puts in that corner. */}
      <AppIconMenu app={app}>
        <button type="button" data-testid={`app-icon-${app.id}`}
          aria-label={`Actions for ${app.name}`}
          className="shrink-0 rounded-card transition hover:brightness-110">
          <IconTile name={app.name} iconUrl={app.icon_url} size={64}
                    initials={app.icon_initials} colors={app.icon_colors} />
        </button>
      </AppIconMenu>
      <div className="min-w-0">
        {/* The name is the way to the app page. The reference this view is
            modelled on has no detail page and so has only one target; this
            one does, and keeps a way in. */}
        <button type="button"
          className="block max-w-full truncate text-left text-[13px] text-text
                     transition hover:text-amber"
          onClick={() => navigate({ to: '/apps/$appId' as never,
                                    params: { appId: String(app.id) } as never })}>
          {app.name}
        </button>
        <div className={`flex items-center gap-1 font-mono text-[11px] uppercase ${state.cls}`}>
          <Icon name={state.icon} size={14} />
          {statusLabel(app.status)}
        </div>
      </div>
    </div>
  )
}

/** The grid's placeholder, mirroring the cell's 64px tile and two text lines
 *  so the page below does not shift when the apps land. */
export function AppIconGridSkeleton({ count = 8 }: { count?: number }) {
  return (
    <div className="grid grid-cols-1 gap-x-6 gap-y-4 rounded-card border border-line-soft
                    bg-panel p-4 sm:grid-cols-2 xl:grid-cols-4">
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className="flex items-center gap-3">
          <Skeleton className="h-16 w-16 shrink-0 rounded-card" />
          <div className="min-w-0 flex-1">
            <SkeletonLine className="w-24 text-[13px]" />
            <SkeletonLine className="w-16 text-[11px]" />
          </div>
        </div>
      ))}
    </div>
  )
}
