import type { ReactNode } from 'react'
import { Separator } from './separator'

/**
 * Two or more related controls welded into one pill, from shadcn/ui
 * (https://ui.shadcn.com/docs/components/button-group). Reimplemented here
 * rather than installed, for the same reason ui/skeleton.tsx was: there is
 * nothing to install, no dependency and no registry entry, just a flex box
 * and a hairline.
 *
 * Adapted:
 *
 *  - No `cn` helper. `src/lib/utils.ts` does export one, but every primitive
 *    this composes with (ui/button.tsx, ui/skeleton.tsx, ui/loading.tsx)
 *    builds its class list as a plain template literal, and a group whose
 *    children are Buttons should read the same way they do.
 *  - Upstream's half-rounded-corner chain is kept, rather than the shorter
 *    `overflow-hidden` on the group that would clip the children's square
 *    corners for free. Clipping also clips the browser's focus ring on the
 *    two outer edges, which costs a keyboard user the only indicator they
 *    have of where they are, and a squarer corner is the cheaper thing to
 *    lose.
 *  - `[&>button]:border-0` because this app's `ghost` Button already carries
 *    `border border-line`. Left alone, two adjacent ghosts would draw a 2px
 *    seam and then the separator would draw a third line through it. The
 *    group draws the one outer border; the separator draws the one divider.
 *  - `role="group"` is kept. The buttons are alternatives for the same
 *    subject (this row's token), not four unrelated controls that happen to
 *    touch, and the grouping is otherwise purely visual.
 *
 * The variants (nesting, dropdowns, `orientation="vertical"`, the
 * ButtonGroupText slot) are deliberately not here. Add them when a second
 * call site actually needs one.
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
 * The hairline between two buttons in a group.
 *
 * This is ui/separator.tsx with `orientation="vertical"`, not a fresh div:
 * that component already resolves to `w-px self-stretch bg-border`, and
 * tokens.css maps `--border: var(--line)`, so it lands on exactly the same
 * hairline colour as the group's own border and flips with the theme for
 * free. It is `decorative` by default, so it adds no noise to the accessible
 * tree, which is right: the divider is a drawing, the two buttons say what
 * they are themselves.
 */
export function ButtonGroupSeparator({ className = '' }: { className?: string }) {
  return <Separator orientation="vertical" className={className} />
}
