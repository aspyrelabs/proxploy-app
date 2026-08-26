import { useEffect, useState } from 'react'

/** Shared behaviour and chrome for the two overlay primitives.
 *
 *  Separate from dialog.tsx and alert-dialog.tsx so those files export only
 *  components, which is what React fast refresh needs to work.
 */

export const dialogOverlayClass =
  'fixed inset-0 z-30 grid place-items-center bg-scrim backdrop-blur-[3px]'

/**
 * max-w-[92vw] lives here, not at call sites: a raw fixed width with no cap
 * overflowed a phone by 130px. Baking the cap in means a call site cannot
 * forget it, whatever width it asks for. */
const dialogPanelChrome = 'rounded-card border border-line bg-panel p-5'

export const dialogPanelClass = `max-w-[92vw] ${dialogPanelChrome}`

/**
 * The other sizing model: no width at all, take the content's, stop at 80vw
 * and 80vh. For the job log there is no honest number to pass as `width` — a
 * transcript is one component whether it's two lines or four hundred, so
 * `w-fit` hands the decision to the content.
 *
 * 80vw/80vh is a ceiling, not a size, and tighter than the shared 92vw: one
 * long line can push this panel flush to the window edge, where it stops
 * reading as a dialog. The height cap earns its place the same way — an
 * uncapped panel taller than the viewport overhangs the top with no way to
 * scroll back.
 *
 * flex-col makes the cap survivable: the body child carries min-h-0 and its
 * own overflow, so when the transcript is taller than 80vh that child shrinks
 * and scrolls while the heading and Close stay put. */
export const dialogFitPanelClass = `flex w-fit max-h-[80vh] max-w-[80vw] flex-col ${dialogPanelChrome}`

/**
 * Opt-in height cap and scroll container for a dialog whose body can outgrow
 * the viewport. The number lives here for the same reason max-w-[92vw] does:
 * a call site that passes its own cap is one that can forget it. `Dialog`
 * takes a boolean, not a height.
 *
 * 70vh is the cap: a panel taller than the viewport cannot be centred by
 * `place-items-center` (no free space to distribute), so it overhangs the top
 * with no way to scroll back. Capping restores the centring. flex-col keeps
 * the heading put while only the body scrolls — a heading that scrolls away
 * leaves the reader with no anchor and nothing to aim the close button at. */
export const dialogScrollPanelClass = 'flex max-h-[70vh] flex-col'

/** min-h-0 is load bearing: a flex child's default min-height is auto, which
 *  refuses to shrink below its content, so the container would grow past the
 *  cap instead of scrolling. pp-scroll-hidden (styles/tokens.css) hides the
 *  bar while leaving every scrolling mechanism intact (wheel, trackpad,
 *  touch, keys, focus moving to an offscreen control); it's scoped to this
 *  one class. */
export const dialogScrollBodyClass = 'min-h-0 flex-1 overflow-y-auto pp-scroll-hidden'

/** The command palette sits high on the screen rather than centred, so it does
 *  not jump as results appear under it. */
export const paletteOverlayClass =
  'fixed inset-0 z-30 grid place-items-start justify-center bg-scrim pt-[12vh] backdrop-blur-[3px]'

export const palettePanelClass = 'max-w-[92vw] rounded-card border border-line bg-panel p-3'

/**
 * Every call site renders its dialog conditionally and unmounts it to close,
 * so the naive onOpenChange -> onClose -> parent-unmounts-us wiring tears
 * Radix down mid-close and focus lands on document.body, not the opener. So
 * the primitive owns closing: flip Radix's open flag first, let it run its
 * close sequence and restore focus, then tell the parent — whose unmount
 * happens on the following effect, after focus has landed. */
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
