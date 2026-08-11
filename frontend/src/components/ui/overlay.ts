import { useEffect, useState } from 'react'

/** Shared behaviour and chrome for the two overlay primitives.
 *
 *  Separate from dialog.tsx and alert-dialog.tsx so those files export only
 *  components, which is what React fast refresh needs to work.
 */

/**
 * Widths are a closed set on purpose. Four dialogs shipped a raw w-[520px]
 * with no viewport cap and overflowed a phone by 130px; a prop that always
 * carries its own max-width makes that defect impossible to write again.
 */
export const WIDTHS = {
  sm: 'w-[420px] max-w-[92vw]',
  md: 'w-[480px] max-w-[92vw]',
  lg: 'w-[520px] max-w-[92vw]',
} as const

export type DialogWidth = keyof typeof WIDTHS

export const dialogOverlayClass =
  'fixed inset-0 z-30 grid place-items-center bg-scrim backdrop-blur-[3px]'

export const dialogPanelClass = 'rounded-card border border-line bg-panel p-5'

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
