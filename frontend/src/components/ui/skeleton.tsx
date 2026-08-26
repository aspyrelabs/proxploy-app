import type { ReactNode } from 'react'

/**
 * The skeleton placeholder, adapted from shadcn/ui (reimplemented because
 * there is nothing to install -- no dependency, no CLI, just those classes).
 *
 * Adaptations vs upstream: no `cn` helper (this repo uses plain template
 * literals); `bg-accent` spelled `bg-elev` (same colour -- tokens.css maps
 * `--accent: var(--elev)`); `motion-reduce:animate-none` added so readers who
 * ask for less motion still see the placeholder; `rounded-md` -> `rounded`
 * (this app's `--radius-*` is a card/tile/control scale); `aria-hidden` -- a
 * skeleton is scaffolding, not content, and the one announcement belongs on
 * `SkeletonGroup`.
 *
 * WHEN TO USE THIS AND NOT ui/loading.tsx: the ring answers "how far along is
 * this job"; a skeleton answers "what is about to appear here", and only
 * where the SHAPE is already known. Where the shape is unknown, or the wait
 * belongs to a job with real progress, keep the ring.
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
 * `1.45` is the body line-height in styles/tokens.css (unitless), so one line
 * box is 1.45x the font size; the outer box claims that line box and pads the
 * bar down to ~0.85em, making the skeleton the same height as the text it
 * replaces.
 *
 * Set the font size (`text-[13px]`, matching the element it stands in for) and
 * the width (`w-24`, `w-1/2`) on the SkeletonLine itself; `em` resolves
 * against this element.
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
 * Deliberately the same announcement shape `Loading` makes (role=status,
 * aria-busy, aria-label, no visible text), so swapping a ring for a skeleton
 * changes what is drawn and nothing about what is announced.
 *
 * `className` carries the layout the real content uses -- pass the same grid
 * classes the loaded branch renders.
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
 * The Avatar pattern from the shadcn page: a round placeholder with the lines
 * of text beside it. `tile` names the roundness (IconTile is `rounded-tile`,
 * a genuine avatar `rounded-full`) and its size. `lines` is one class per
 * line of text, so widths and font sizes are the caller's. `children` land
 * after the lines, where detail headers put their trailing controls.
 */
export function SkeletonAvatar({ tile = 'h-10 w-10 rounded-full', lines, className = '', children }: {
  tile?: string
  lines: string[]
  className?: string
  children?: ReactNode
}) {
  return (
    <div aria-hidden className={`flex items-start gap-3 ${className}`}>
      <Skeleton className={`shrink-0 ${tile}`} />
      <div className="min-w-0 flex-1">
        {lines.map((cls, i) => <SkeletonLine key={i} className={cls} />)}
      </div>
      {children}
    </div>
  )
}

/**
 * The Form pattern from the same page: one label above one control.
 *
 * The measurements are this app's field (`px-3 py-2 text-[13px]`,
 * `rounded-ctl`, the 11.5px uppercase caption label), not upstream's `h-4`/
 * `h-8` -- a guess would shift every control when the real one landed. `label`
 * is a width class because labels differ.
 *
 * No `SkeletonForm` wrapper: the forms here carry their own grid, and that
 * layout belongs on the `SkeletonGroup` at the call site.
 */
export function SkeletonField({ label = 'w-20', className = '' }: {
  label?: string
  className?: string
}) {
  return (
    <div aria-hidden className={className}>
      <SkeletonLine className={`mb-1 ${label} text-[11.5px]`} />
      <Skeleton className="h-[37px] w-full rounded-ctl" />
    </div>
  )
}

/**
 * One CPU/RAM/Disk row, matching components/UsageBar.tsx as NodeCard stacks
 * it three deep: a fixed-width label, the 6px track, a fixed-width figure. The track needs no skeleton of its own -- an unfilled UsageBar IS a
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
 * `py-2.5` cells. `cols` is one Tailwind width class per column rather than a
 * count, because the widths ARE the shape. `head` is a flag because some
 * tables have no header row at all (e.g. the "Recently resolved" list), and
 * drawing one would shift rows down then snap them back.
 */
export function SkeletonTable({ cols, rows = 5, head = true }: {
  cols: string[]
  rows?: number
  head?: boolean
}) {
  return (
    <table className="w-full text-left text-[13px]">
      {head && (
        <thead>
          <tr className="text-[11px] uppercase text-text-3">
            {cols.map((w, i) => (
              <th key={i} scope="col" className="pb-2 font-medium"><SkeletonLine className={w} /></th>
            ))}
          </tr>
        </thead>
      )}
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
