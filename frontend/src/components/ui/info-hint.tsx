import * as Tooltip from '@radix-ui/react-tooltip'
import { Icon } from './icon'

/**
 * A small (i) that explains why a figure is missing, or anything else too long
 * to write in the cell it sits in.
 *
 * Carries its own Tooltip.Provider rather than expecting an ancestor to supply
 * one. SidebarNav wraps its whole rail in a Provider because every item in it
 * wants a tooltip; a lone hint in a table cell has no such rail to hang off,
 * and requiring callers to remember a Provider is how you get a component that
 * silently renders nothing.
 *
 * The text is ALSO the trigger's accessible name and its native `title`. A
 * Radix tooltip opens on hover and on keyboard focus but not on touch, so on a
 * phone the title attribute is the only thing left; and a screen reader should
 * not have to open a tooltip to find out why a number says "unknown".
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
