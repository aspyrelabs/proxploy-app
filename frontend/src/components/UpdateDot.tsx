import * as Tooltip from '@radix-ui/react-tooltip'

/**
 * The "an update is waiting for this app" mark, in one place.
 *
 * A dot, not the word "update": the pill this replaced was as wide as some
 * app names and pushed the row's most important text around.
 *
 * Losing the word means the wording has to be carried by everything BUT the
 * pixels, so this hangs a real tooltip off the dot as well as an accessible
 * name. Same reasoning as InfoHint: the tooltip is for a sighted mouse or
 * keyboard user who cannot guess what an orange dot means, the aria-label is
 * for a screen reader that never opens it, and the title is the last thing
 * left on a touch device, where a Radix tooltip does not open at all. That is
 * also why this is a component rather than a copied span: the markup was
 * duplicated across the apps table, the guest list and the app card, and
 * three copies of an accessible name is three chances for one of them to
 * drift into meaninglessness.
 *
 * tabIndex makes the dot focusable, which is the only way the tooltip can be
 * reached without a pointer. It carries its own Provider for the same reason
 * InfoHint does: a dot in a table row has no ancestor that supplies one.
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
