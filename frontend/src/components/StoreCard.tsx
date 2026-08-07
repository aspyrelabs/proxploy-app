import type { CatalogRow } from '../api/catalog'
import { Button } from './ui/button'
import { STORE_GRADIENT } from './UsageBar'

export function StoreCard({ entry, onInstall, installed }: {
  entry: CatalogRow; onInstall: (slug: string) => void; installed: boolean
}) {
  return (
    <div className="rounded-card border border-line-soft bg-panel p-4">
      <div className="flex items-start justify-between">
        <div
          className="flex h-10 w-10 items-center justify-center rounded-tile font-display text-[14px] font-semibold text-white"
          style={{ background: STORE_GRADIENT }}
        >
          {(entry.name ?? entry.slug).slice(0, 2).toUpperCase()}
        </div>
        {entry.popularity != null && (
          <span className="font-mono text-[11px] text-text-3">★ {entry.popularity}</span>
        )}
      </div>
      <div className="mt-2 text-[14px] font-semibold text-text">{entry.name ?? entry.slug}</div>
      <div className="font-mono text-[11px] text-text-3">{entry.category ?? 'Uncategorized'}</div>
      <div className="mt-1 min-h-[34px] text-[12px] text-text-2">
        {entry.description ?? ''}
      </div>
      <span className="mt-2 inline-block rounded bg-panel-2 px-1.5 py-0.5 font-mono text-[10px] uppercase text-text-3">
        LXC
      </span>
      <div className="mt-3 border-t border-line-soft pt-3">
        {!entry.installable ? (
          <div className="text-[12px] text-text-3">
            Not installable, {entry.unsupported_reason}
            {entry.website && (
              <>
                {' '}
                <a href={entry.website} target="_blank" rel="noreferrer"
                  className="text-amber hover:underline">upstream</a>
              </>
            )}
          </div>
        ) : installed ? (
          <Button variant="ghost" disabled>Installed</Button>
        ) : (
          <Button variant="primary" onClick={() => onInstall(entry.slug)}>Install</Button>
        )}
      </div>
    </div>
  )
}
