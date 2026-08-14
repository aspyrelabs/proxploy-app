import type { ReactNode } from 'react'

/**
 * The skeleton placeholder, from shadcn/ui
 * (https://ui.shadcn.com/docs/components/base/skeleton). Upstream is three
 * lines:
 *
 *   <div data-slot="skeleton" className={cn("animate-pulse rounded-md bg-accent", className)} />
 *
 * Reimplemented here rather than installed, because there is nothing to
 * install: no dependency, no CLI, no registry entry, just those classes.
 * Adapted:
 *
 *  - No `cn` helper: this repo has no clsx/tailwind-merge, class lists are
 *    plain template literals (same as ui/loading.tsx and ui/button.tsx).
 *  - `bg-accent` is kept in spirit but spelled `bg-elev`. Those are the SAME
 *    colour here: tokens.css maps `--accent: var(--elev)` so shadcn components
 *    land on this app's raised surface. Naming the app's own token rather than
 *    the shadcn alias keeps the skeleton in the same vocabulary as everything
 *    around it, and it flips with the theme for free (`--elev` is #1B2531 dark,
 *    #E7ECF2 light) with no second palette to keep in sync.
 *  - `motion-reduce:animate-none` added. Upstream pulses unconditionally. The
 *    pulse is decoration, the block itself is the message, so a reader who
 *    asked for less motion still sees the placeholder, just still. Same
 *    treatment as ui/loading.tsx's spin and ui/card-loading-overlay.tsx's blur.
 *  - `rounded-md` -> `rounded`. `--radius-*` here is a card/tile/control scale
 *    (14/9/10px); a 6px bar with a 6px radius is a lozenge. Call sites that
 *    stand in for something genuinely round (a StatusPill, an icon tile) pass
 *    their own `rounded-full` / `rounded-tile`.
 *  - `aria-hidden`. A skeleton is scaffolding, not content. The one
 *    announcement belongs on the group (see `SkeletonGroup`), otherwise a
 *    grid of eight placeholder cards is eight things for a screen reader to
 *    read out and none of them say anything.
 *
 * WHEN TO USE THIS AND NOT ui/loading.tsx. They answer different questions.
 * The ring answers "how far along is this job" (determinate) or "is anything
 * happening at all" (indeterminate). A skeleton answers "what is about to
 * appear here", and it can only answer that where the SHAPE is already known:
 * a grid of app cards, a table of five columns. Where the shape is not known
 * up front, or the wait belongs to a job with real progress, keep the ring.
 */
export function Skeleton({ className = '' }: { className?: string }) {
  return (
    <div aria-hidden
      className={`animate-pulse rounded bg-elev motion-reduce:animate-none ${className}`} />
  )
}

/**
 * One line of text, exactly.
 *
 * `1.45` is the body line-height set in styles/tokens.css, and it is unitless,
 * so one line box is always 1.45x the font size. The outer box claims that
 * whole line box and pads the bar back down to the ~0.85em an average glyph
 * actually inks, which is what makes a skeleton stack the same height as the
 * text it replaces instead of a rough guess at it.
 *
 * Set the font size on the SkeletonLine itself (`text-[13px]`), matching the
 * element it stands in for -- `em` here resolves against this element.
 * Width goes here too (`w-24`, `w-1/2`); the bar inside fills it.
 */
export function SkeletonLine({ className = '' }: { className?: string }) {
  return (
    <div aria-hidden className={`h-[1.45em] py-[0.3em] ${className}`}>
      <Skeleton className="h-full w-full" />
    </div>
  )
}

/**
 * The wrapper a group of skeletons goes in: one busy announcement for the
 * whole placeholder, since every skeleton inside is `aria-hidden`.
 *
 * Deliberately the same shape of announcement `Loading` makes (role=status,
 * aria-busy, aria-label, no visible text), so swapping a ring for a skeleton
 * at a call site changes what is drawn and nothing about what is announced.
 *
 * `className` carries the layout the real content uses -- pass the same grid
 * classes the loaded branch renders, or the placeholder will be a different
 * shape from the thing it is standing in for.
 */
export function SkeletonGroup({ label, className = '', children }: {
  label: string
  className?: string
  children: ReactNode
}) {
  return (
    <div role="status" aria-busy="true" aria-label={label} className={className}>
      {children}
    </div>
  )
}

/**
 * One CPU/RAM/Disk row, matching components/UsageBar.tsx in its two call
 * sites (AppCard, NodeCard): a fixed-width label, the 6px track, a fixed-width
 * figure. The track needs no skeleton of its own -- an unfilled UsageBar IS a
 * `bg-elev` 6px rounded bar, which is exactly what `Skeleton` draws, so this
 * renders the real empty track shape and pulses it.
 */
export function SkeletonMeterRow() {
  return (
    <div className="flex items-center gap-2">
      <SkeletonLine className="w-8 text-[10.5px]" />
      <div className="flex-1"><Skeleton className="h-1.5 w-full rounded-full" /></div>
      <SkeletonLine className="w-9 text-[11px]" />
    </div>
  )
}

/**
 * A table's worth of placeholder, in this app's one table shape: an 11px
 * uppercase header row, then `border-t border-line-soft` body rows with
 * `py-2.5` cells (routes/vms.tsx, routes/backups.tsx, routes/network.tsx and
 * routes/alerts.tsx all spell it that way).
 *
 * `cols` is one Tailwind width class per column rather than a count, because
 * the widths ARE the shape: a Name column and a Status column are not the same
 * size, and a table of identical bars reads as a grey grid rather than as the
 * table about to replace it.
 */
export function SkeletonTable({ cols, rows = 5 }: { cols: string[]; rows?: number }) {
  return (
    <table className="w-full text-left text-[13px]">
      <thead>
        <tr className="text-[11px] uppercase text-text-3">
          {cols.map((w, i) => (
            <th key={i} scope="col" className="pb-2 font-medium"><SkeletonLine className={w} /></th>
          ))}
        </tr>
      </thead>
      <tbody>
        {Array.from({ length: rows }, (_, r) => (
          <tr key={r} className="border-t border-line-soft">
            {cols.map((w, i) => (
              <td key={i} className="py-2.5"><SkeletonLine className={w} /></td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  )
}
