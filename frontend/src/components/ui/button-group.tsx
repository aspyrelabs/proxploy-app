import type { ReactNode } from 'react'
import { Separator } from './separator'

/**
 * Two or more related controls welded into one pill, from shadcn/ui
 * (https://ui.shadcn.com/docs/components/button-group). Reimplemented rather
 * than installed — there is nothing to install, just a flex box and a hairline.
 *
 * Adapted:
 *  - No `cn` helper: the primitives this composes with build class lists as
 *    plain template literals, and a group of Buttons reads the same way.
 *  - Upstream's half-rounded-corner chain is kept over `overflow-hidden`, which
 *    would clip the browser's focus ring on the two outer edges and cost a
 *    keyboard user their only indicator of position.
 *  - `[&>button]:border-0` because this app's `ghost` Button already carries
 *    `border border-line`: two adjacent ghosts would draw a 2px seam. The group
 *    draws the one outer border; the separator draws the one divider.
 *  - `role="group"`: the buttons are alternatives for the same subject, not
 *    unrelated controls that happen to touch.
 *
 * Nesting, dropdowns, `orientation="vertical"` and the ButtonGroupText slot are
 * deliberately absent — add them when a second call site needs one.
 */
export function ButtonGroup({ className = '', children }: {
  className?: string
  children: ReactNode
}) {
  return (
    <div role="group"
      className={`inline-flex items-center rounded-ctl border border-line [&>button]:rounded-none [&>button]:border-0 [&>button:first-child]:rounded-l-ctl [&>button:last-child]:rounded-r-ctl ${className}`}>
      {children}
    </div>
  )
}

/**
 * The hairline between two buttons in a group — ui/separator.tsx with
 * `orientation="vertical"`, not a fresh div: it resolves to `w-px self-stretch
 * bg-border`, which tokens.css maps to the same hairline colour as the group's
 * border, and flips with the theme. Decorative by default, so it adds no noise
 * to the accessible tree — the divider is a drawing, the buttons say what they
 * are themselves.
 */
export function ButtonGroupSeparator({ className = '' }: { className?: string }) {
  return <Separator orientation="vertical" className={className} />
}
