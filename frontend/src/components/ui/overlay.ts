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
export const dialogPanelClass = 'max-w-[92vw] rounded-card border border-line bg-panel p-5'

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
 *  cap instead of scrolling. */
export const dialogScrollBodyClass = 'min-h-0 flex-1 overflow-y-auto'

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
