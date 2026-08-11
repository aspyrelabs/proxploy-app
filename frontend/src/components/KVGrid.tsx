import type { ReactNode } from 'react'

export function KVGrid({ items }: { items: [string, ReactNode][] }) {
  return (
    <div className="grid grid-cols-[repeat(auto-fit,minmax(150px,1fr))] gap-4">
      {items.map(([k, v]) => (
        <div key={k}>
          <div data-kv-term className="text-[10.5px] uppercase tracking-wide text-text-3">{k}</div>
          <div className="mt-1 font-mono text-[13px] text-text">{v}</div>
        </div>
      ))}
    </div>
  )
}
