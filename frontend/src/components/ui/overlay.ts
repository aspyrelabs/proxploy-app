import { useEffect, useState } from 'react'

/** Shared behaviour and chrome for the two overlay primitives.
 *
 *  Separate from dialog.tsx and alert-dialog.tsx so those files export only
 *  components, which is what React fast refresh needs to work.
 */

export const dialogOverlayClass =
  'fixed inset-0 z-30 grid place-items-center bg-scrim backdrop-blur-[3px]'

/**
 * max-w-[92vw] lives in the shared panel class, not at the call sites. Four
 * dialogs shipped a raw w-[520px] with no cap and overflowed a phone by 130px;
 * baking the cap in here means a call site cannot forget it, whatever width it
 * asks for. The widths themselves range 380 to 560, so they stay a number
 * rather than a name that would fit none of them.
 */
const dialogPanelChrome = 'rounded-card border border-line bg-panel p-5'

export const dialogPanelClass = `max-w-[92vw] ${dialogPanelChrome}`

/**
 * The other sizing model: no width at all, take the content's, and stop at 80%
 * of the window in BOTH axes.
 *
 * For the job log there is no honest number to pass as `width`. The panel holds
 * a transcript, and a two-line "storage is full" and a 400-line install run are
 * the same component; a fixed 720 was too wide for the first and too narrow for
 * the second. `w-fit` hands the decision to the content: the panel comes out as
 * wide as the longest log line and as tall as the transcript, and shrinks below
 * both when there is less to show.
 *
 * 80vw/80vh is the ceiling, and it is a ceiling rather than a size: it only
 * bites once the content asks for more than that. It is tighter than the shared
 * 92vw because this panel can be pushed to it by one long line, and a dialog
 * flush to the window edge stops reading as a dialog. The height cap earns its
 * place for the same reason 70vh does above: `place-items-center` cannot centre
 * a panel taller than the viewport, so an uncapped one overhangs the top with
 * no way to scroll back to it.
 *
 * flex-col is what makes the cap survivable. The body child carries min-h-0 and
 * its own overflow (TerminalPanel already does), so when the transcript is
 * taller than 80vh the flexbox shrinks that child and it scrolls, while the
 * heading and the Close button stay put.
 */
export const dialogFitPanelClass = `flex w-fit max-h-[80vh] max-w-[80vw] flex-col ${dialogPanelChrome}`

/**
 * Opt-in height cap and scroll container, for a dialog whose body is long
 * enough to outgrow the viewport.
 *
 * The numbers live HERE rather than at the call site, for the same reason
 * max-w-[92vw] does: a call site that passes its own cap is a call site that
 * can forget one. `Dialog` takes a boolean, not a height.
 *
 * 70vh is the cap: the App Store's detail popup was rendering at full content
 * height, which for that content is taller than the screen, and a panel taller
 * than the viewport cannot be centred by `place-items-center` because there is
 * no free space to distribute. So it overhung the top with no way to scroll
 * back to it. Capping the height is what restores the centring; no centring
 * code was added or needed.
 *
 * The panel becomes a flex column so the heading can stay put while only the
 * body scrolls. A dialog whose heading scrolls away leaves the reader with no
 * anchor and nothing to aim the close button at.
 */
export const dialogScrollPanelClass = 'flex max-h-[70vh] flex-col'

/** min-h-0 is load bearing: a flex child's default min-height is auto, which
 *  refuses to shrink below its content, so the container would grow past the
 *  cap instead of scrolling.
 *
 *  pp-scroll-hidden (styles/tokens.css) hides the bar itself while leaving
 *  every scrolling mechanism intact: wheel, trackpad, touch, arrow keys,
 *  Page Up/Down, Home/End, and focus moving to an offscreen control. It is
 *  scoped to this one class, so no other scroll surface in the app loses its
 *  bar. */
export const dialogScrollBodyClass = 'min-h-0 flex-1 overflow-y-auto pp-scroll-hidden'

/** The command palette sits high on the screen rather than centred, so it does
 *  not jump as results appear under it. */
export const paletteOverlayClass =
  'fixed inset-0 z-30 grid place-items-start justify-center bg-scrim pt-[12vh] backdrop-blur-[3px]'

export const palettePanelClass = 'max-w-[92vw] rounded-card border border-line bg-panel p-3'

/**
 * Every call site renders its dialog conditionally and unmounts it to close,
 * so the naive wiring is onOpenChange -> onClose -> parent unmounts us. That
 * tears Radix down mid-close and focus lands on document.body instead of the
 * control that opened the dialog, which is one of the four defects this whole
 * change exists to fix.
 *
 * So the primitive owns closing: flip Radix's own open flag first, let it run
 * its close sequence and restore focus, and only then tell the parent. The
 * parent's unmount happens on the following effect, after focus has landed.
 */
export function useRadixClose(onClose: () => void) {
  const [open, setOpen] = useState(true)

  // Radix restores focus to its own <Dialog.Trigger>. These dialogs are
  // rendered conditionally by their parent rather than opened by a Trigger,
  // so that ref is always null and focus would land on document.body. Capture
  // the opener during the first render, before Radix's own effects move focus
  // into the panel, and put it back ourselves.
  const [opener] = useState<HTMLElement | null>(
    () => (typeof document === 'undefined' ? null : (document.activeElement as HTMLElement | null)),
  )

  useEffect(() => { if (!open) onClose() }, [open, onClose])

  return {
    open,
    requestClose: (next: boolean) => { if (!next) setOpen(false) },
    onCloseAutoFocus: (event: Event) => {
      event.preventDefault()
      opener?.focus()
    },
  }
}
