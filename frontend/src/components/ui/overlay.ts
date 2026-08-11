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

/** The command palette sits high on the screen rather than centred, so it does
 *  not jump as results appear under it. */
export const paletteOverlayClass =
  'fixed inset-0 z-30 grid place-items-start justify-center bg-scrim pt-[12vh] backdrop-blur-[3px]'

export const palettePanelClass = 'max-w-[92vw] rounded-card border border-line bg-panel p-3'

/** The activity drawer: same modal behaviour, docked to the right edge. */
export const sheetOverlayClass = 'fixed inset-0 z-20 bg-scrim'

export const sheetPanelClass =
  'fixed inset-y-0 right-0 z-20 flex max-w-full flex-col border-l border-line bg-panel-2'

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
