import type { ReactNode } from 'react'
import * as DialogPrimitive from '@radix-ui/react-dialog'

import {
  dialogFitPanelClass, dialogOverlayClass, dialogPanelClass, dialogScrollBodyClass,
  dialogScrollPanelClass, paletteOverlayClass, palettePanelClass, useRadixClose,
} from './overlay'

/**
 * The one modal in the product. Everything that used to hand-roll a scrim and
 * a panel comes through here.
 *
 * Radix owns the parts that were missing from all 18 hand-rolled versions and
 * that are genuinely hard to get right: Escape, focus trap, focus restore to
 * whatever opened the dialog, aria-modal, and scroll lock. We own only the
 * look, which is the existing tokens unchanged.
 *
 * Mounting model matches the call sites it replaces: render it when it should
 * be open, unmount it to close. onClose fires for Escape and for a click on
 * the scrim.
 */

export function Dialog({
  title,
  description,
  width = 420,
  variant = 'center',
  headerRight,
  scrollBody = false,
  fit = false,
  onClose,
  children,
}: {
  title: ReactNode
  /** Rendered under the title, and wired to aria-describedby when present. */
  description?: ReactNode
  /** Panel width in px. The 92vw cap is applied for you, always. */
  width?: number
  /** 'palette' sits high and hides its heading (the command palette names
   *  itself through its input). */
  variant?: 'center' | 'palette'
  /** Sits on the title's row, pushed right. The VM wizard's step pills use it
   *  so converting did not have to move them below the heading. */
  headerRight?: ReactNode
  /** Caps the panel height and scrolls the BODY, leaving the heading in place.
   *  Opt-in on purpose: this is shared by InstallDialog, the VM create wizard,
   *  the schedule dialogs and the rest, and a dialog that fits on screen must
   *  not grow a scroll container it never needed. A dialog that does not pass
   *  this renders exactly as it did before the prop existed. The cap itself
   *  lives in overlay.ts, so a call site cannot pick its own. */
  scrollBody?: boolean
  /** Drops `width` entirely and sizes the panel to its content, capped at
   *  80vw/80vh (dialogFitPanelClass). For the job log, whose size is whatever
   *  the transcript turned out to be. Unlike scrollBody this does NOT wrap the
   *  children in a scroller: the body child owns the scrolling, because the
   *  thing that has to stay scrolled to the newest line is TerminalPanel
   *  itself. A `fit` child must therefore carry min-h-0 and its own overflow,
   *  which is what `<JobLog height="fill">` passes down. */
  fit?: boolean
  onClose: () => void
  children: ReactNode
}) {
  const { open, requestClose, onCloseAutoFocus } = useRadixClose(onClose)
  // Empty string unless the panel is a capped flex column, so a dialog that
  // opts into neither emits the exact same class strings it did before.
  const shrink = scrollBody || fit ? ' shrink-0' : ''
  return (
    <DialogPrimitive.Root open={open} onOpenChange={requestClose}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className={variant === 'palette' ? paletteOverlayClass : dialogOverlayClass}>
          <DialogPrimitive.Content
            onCloseAutoFocus={onCloseAutoFocus}
            // Radix hides the rest of the tree with aria-hidden rather than
            // emitting this, which is a valid way to do it. We state it too:
            // role="dialog" plus aria-modal is what a screen reader user and
            // an auditor both expect to find.
            aria-modal="true"
            className={variant === 'palette' ? palettePanelClass
              : fit ? dialogFitPanelClass
              : scrollBody ? `${dialogPanelClass} ${dialogScrollPanelClass}` : dialogPanelClass}
            // No inline width when fitting: a stated width would win over
            // w-fit and there would be nothing left for the content to decide.
            style={fit ? undefined : { width }}
            // Radix wires aria-describedby itself when a Description is
            // rendered, and warns when one is missing. Most of these dialogs
            // carry a whole form rather than one describing sentence, so opt
            // out explicitly instead of letting a console warning ride along
            // in every test run.
            {...(description ? {} : { 'aria-describedby': undefined })}
          >
            {variant === 'palette' ? (
              // Radix requires a Title. The palette has never shown one, and
              // adding a visible heading above the search field would be a
              // change to the design, not to the accessibility.
              <DialogPrimitive.Title className="sr-only">{title}</DialogPrimitive.Title>
            ) : headerRight ? (
              <div className={`mb-4 flex items-center justify-between${shrink}`}>
                <DialogPrimitive.Title className="font-display text-[16px] font-semibold text-text">
                  {title}
                </DialogPrimitive.Title>
                {headerRight}
              </div>
            ) : (
              <DialogPrimitive.Title className={`font-display text-[16px] font-semibold text-text${shrink}`}>
                {title}
              </DialogPrimitive.Title>
            )}
            {description && (
              <DialogPrimitive.Description className={`mt-2 text-[13px] text-text-2${shrink}`}>
                {description}
              </DialogPrimitive.Description>
            )}
            {scrollBody ? (
              <div className={dialogScrollBodyClass}>{children}</div>
            ) : children}
          </DialogPrimitive.Content>
        </DialogPrimitive.Overlay>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  )
}
