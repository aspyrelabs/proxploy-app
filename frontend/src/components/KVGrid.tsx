import type { ReactNode } from 'react'

export function KVGrid({ items }: { items: [string, ReactNode][] }) {
  return (
    <div className="grid grid-cols-[repeat(auto-fit,minmax(150px,1fr))] gap-4">
      {items.map(([k, v]) => (
        <div key={k} className="min-w-0">
          <div data-kv-term className="text-[10.5px] uppercase tracking-wide text-text-3">{k}</div>
          {/* min-w-0 above and truncate here, together: a grid item defaults to
              min-width:auto, so a long value (an ISO filename is the one that
              found this) refuses to shrink and widens its column until it
              spills out of the panel. The title carries the full text for a
              value that has been cut. */}
          <div className="mt-1 truncate font-mono text-[13px] text-text"
            title={typeof v === 'string' ? v : undefined}>{v}</div>
        </div>
      ))}
    </div>
  )
}
