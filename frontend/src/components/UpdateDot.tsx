import * as Tooltip from '@radix-ui/react-tooltip'

/**
 * An orange dot marking an available update — smaller than a text label.
 *
 * Three accessibility layers for three interaction modes: tooltip (mouse),
 * aria-label (screen reader), title (touch — Radix tooltips don't open on
 * touch). Extracted to a component so the accessible name stays consistent
 * across every usage site. Own Tooltip.Provider because table rows don't
 * supply one.
 */
export function UpdateDot() {
  return (
    <Tooltip.Provider delayDuration={150}>
      <Tooltip.Root>
        <Tooltip.Trigger asChild>
          <span role="img" aria-label="Update available" tabIndex={0}
                title="An update is available for this app"
                className="size-2 shrink-0 cursor-help rounded-full bg-amber" />
        </Tooltip.Trigger>
        <Tooltip.Portal>
          <Tooltip.Content side="top" sideOffset={6} collisionPadding={8}
            className="z-50 rounded-tile border border-line bg-elev
                       px-2 py-1.5 text-[12px] leading-snug text-text shadow-lg">
            Update available
          </Tooltip.Content>
        </Tooltip.Portal>
      </Tooltip.Root>
    </Tooltip.Provider>
  )
}
