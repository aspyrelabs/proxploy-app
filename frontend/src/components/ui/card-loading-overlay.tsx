import type { ReactNode } from 'react'
import { ArrowPathIcon } from '@heroicons/react/24/outline'

/**
 * Vendored by hand from ReUI's `c-spinner-11` usage example
 * (https://reui.io/r/c-spinner-11.json, fetched 2026-08-12): a translucent,
 * blurred veil pinned over a card while it (re)loads, with the previous
 * content held underneath so nothing jumps.
 *
 * `c-spinner-11` is itself a *usage example* (registry `type: "block"`) of
 * two base primitives named in its own `registryDependencies`: `card` and
 * `spinner`. `card` was not fetched: this app's cards are plain
 * `<section className="rounded-card ...">`, not shadcn's `<Card>`
 * component, and there is nothing to vendor there. `spinner`
 * (https://reui.io/r/spinner.json) could not be fetched at all -- unlike
 * `c-spinner-11.json`, that endpoint 401s with "Provide your license key via
 * Authorization header", it sits behind ReUI's paid tier and this task has
 * no license key for it. Per this repo's own documented fallback ("if the
 * spinner needs an icon, use @heroicons/react"), the spin is
 * `@heroicons/react`'s `ArrowPathIcon` (a circular-arrow glyph, the standard
 * stand-in for a loading spinner) driven by Tailwind's `animate-spin`,
 * standing in for ReUI's own `<Spinner>` primitive.
 *
 * Further adaptations from the fetched example:
 *  - No `cn` helper: this repo has no clsx/tailwind-merge; class lists are
 *    plain template literals.
 *  - Upstream's `bg-background/80` does not exist here: tokens.css has no
 *    `--background`. Mapped onto `bg-panel/80` -- `--panel` is this app's
 *    card surface colour in both themes (see tokens.css), so a translucent
 *    veil at 80% reads as "this same card, temporarily busy" rather than a
 *    foreign colour dropped on top. `text-text-2` (not a hardcoded grey) for
 *    the spinner keeps it visible on both themes' `--panel`.
 *  - `backdrop-blur-xs` (upstream) -> `backdrop-blur-sm`: this repo's
 *    smallest *named* Tailwind blur step in active use; `xs` was never used
 *    anywhere else here and `sm` already reads clearly against `--panel` in
 *    both themes.
 *  - `motion-reduce:` opt-outs added on both the blur and the spin (neither
 *    exists upstream), matching the pattern already used by
 *    UsageBar/SidebarNav/AppCard: the blur drops to none and the spin stops,
 *    but the veil itself, and `aria-busy`, stay -- the loading state is not
 *    lost, only the motion.
 *  - This is a plain visual veil, not a modal -- the same category as
 *    `components/LockVeil.tsx`, not `ui/dialog.tsx`. No focus trap, no
 *    Escape handling, no `aria-modal`, no portal. It is deliberately absent
 *    from overlay-contract.test.ts's dialog sweep because it never uses that
 *    pattern to begin with (no `fixed inset-0` + scrim; this is `absolute
 *    inset-0` scoped to one card, not a viewport-covering modal layer).
 *  - `relative` and `aria-busy` are owned by this component, not by each
 *    call site. `CardLoadingOverlay` wraps `children` in the positioned,
 *    `aria-busy` container itself, so a call site cannot forget to add
 *    `relative` to its card, there is nowhere else in this component for the
 *    veil to be positioned against.
 */

export type CardLoadingState = {
  /** True until this card's data has ever loaded once -- pass the query's
   *  own `isPending`. TanStack Query flips this false the moment the first
   *  fetch settles, success or error, and never true again after that, so it
   *  does NOT fire on a background poll or a post-mutation refetch. */
  firstLoad: boolean
  /** True only while a fetch the user explicitly asked for (a refresh
   *  control, not a poll) is in flight. `isFetching` alone cannot tell a
   *  poll from a click, TanStack Query does not know the difference either,
   *  so the call site has to track *why* the fetch started (e.g. flip a
   *  local flag when the refresh handler runs, clear it when the query
   *  settles) and report that here. Omit entirely on a card with no manual
   *  refresh control -- there is nothing to distinguish yet. */
  refreshing?: boolean
  /** True while a mutation that changes this card's content is in flight. */
  mutating?: boolean
}

export function CardLoadingOverlay({ state, label = 'Loading', className = '', children }: {
  state: CardLoadingState
  /** Accessible name for the veil's spinner, and its `aria-label`. */
  label?: string
  className?: string
  children: ReactNode
}) {
  const active = state.firstLoad || !!state.refreshing || !!state.mutating
  return (
    <div className={`relative ${className}`} aria-busy={active}>
      {children}
      {active && (
        <div
          className="absolute inset-0 z-10 grid place-items-center rounded-card
                     bg-panel/80 backdrop-blur-sm motion-reduce:backdrop-blur-none"
        >
          <ArrowPathIcon
            aria-hidden="true"
            className="h-5 w-5 animate-spin text-text-2 motion-reduce:animate-none"
          />
          <span role="status" className="sr-only">{label}</span>
        </div>
      )}
    </div>
  )
}
