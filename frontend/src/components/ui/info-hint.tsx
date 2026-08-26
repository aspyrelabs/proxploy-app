import * as Tooltip from '@radix-ui/react-tooltip'
import { Icon } from './icon'

/**
 * An (i) explaining why a figure is missing, or anything too long for the
 * cell it sits in.
 *
 * Carries its own Tooltip.Provider: without one Radix tooltips silently render
 * nothing, and a lone table-cell hint has no rail (unlike SidebarNav) to
 * supply it.
 *
 * `text` is also the trigger's accessible name and native `title`. Radix opens
 * on hover and focus but not touch, so `title` is all a phone gets; a screen
 * reader shouldn't have to open a tooltip to learn why a value says "unknown".
 */
export function InfoHint({ text }: { text: string }) {
  return (
    <Tooltip.Provider delayDuration={150}>
      <Tooltip.Root>
        <Tooltip.Trigger asChild>
          <button type="button" aria-label={text} title={text}
            // The row underneath expands on click, and asking what a hint means
            // is not asking to open the row.
            onClick={(e) => { e.stopPropagation(); e.preventDefault() }}
            className="cursor-help align-middle text-text-3 transition hover:text-text-2">
            <Icon name="info" size={13} />
          </button>
        </Tooltip.Trigger>
        <Tooltip.Portal>
          <Tooltip.Content side="top" sideOffset={6} collisionPadding={8}
            className="z-50 max-w-[260px] rounded-tile border border-line bg-elev
                       px-2 py-1.5 text-[12px] leading-snug text-text shadow-lg">
            {text}
          </Tooltip.Content>
        </Tooltip.Portal>
      </Tooltip.Root>
    </Tooltip.Provider>
  )
}
