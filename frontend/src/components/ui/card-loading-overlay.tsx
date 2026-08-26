import type { ReactNode } from 'react'
import { Icon } from './icon'

/**
 * Vendored from ReUI's `c-spinner-11` usage example
 * (https://reui.io/r/c-spinner-11.json, fetched 2026-08-12): a translucent,
 * blurred veil over a card while it loads, previous content held underneath.
 * ReUI's `spinner` primitive sits behind its paid tier (the registry endpoint
 * 401s), so the spin is the Material Symbols `progress_activity` glyph driven
 * by `animate-spin`. `bg-panel/80` because this repo has no `--background`
 * token; `--panel` is the card surface in both themes.
 *
 * Not a modal (unlike ui/dialog.tsx): no focus trap, Escape handling,
 * `aria-modal`, or portal -- deliberately absent from
 * overlay-contract.test.ts's dialog sweep.
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
          <Icon
            name="progress_activity"
            size={20}
            className="animate-spin text-text-2 motion-reduce:animate-none"
          />
          <span role="status" className="sr-only">{label}</span>
        </div>
      )}
    </div>
  )
}
