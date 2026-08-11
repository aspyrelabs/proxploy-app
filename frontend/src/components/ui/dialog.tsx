import type { ReactNode } from 'react'
import * as DialogPrimitive from '@radix-ui/react-dialog'

import {
  dialogOverlayClass, dialogPanelClass, paletteOverlayClass, palettePanelClass,
  sheetOverlayClass, sheetPanelClass, useRadixClose,
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
  onClose,
  children,
}: {
  title: ReactNode
  /** Rendered under the title, and wired to aria-describedby when present. */
  description?: ReactNode
  /** Panel width in px. The 92vw cap is applied for you, always. */
  width?: number
  /** 'sheet' docks it to the right edge, 'palette' sits high and hides its
   *  heading (the command palette names itself through its input). */
  variant?: 'center' | 'sheet' | 'palette'
  /** Sits on the title's row, pushed right. The VM wizard's step pills use it
   *  so converting did not have to move them below the heading. */
  headerRight?: ReactNode
  onClose: () => void
  children: ReactNode
}) {
  const { open, requestClose, onCloseAutoFocus } = useRadixClose(onClose)
  return (
    <DialogPrimitive.Root open={open} onOpenChange={requestClose}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className={variant === 'sheet' ? sheetOverlayClass
          : variant === 'palette' ? paletteOverlayClass : dialogOverlayClass}>
          <DialogPrimitive.Content
            onCloseAutoFocus={onCloseAutoFocus}
            // Radix hides the rest of the tree with aria-hidden rather than
            // emitting this, which is a valid way to do it. We state it too:
            // role="dialog" plus aria-modal is what a screen reader user and
            // an auditor both expect to find.
            aria-modal="true"
            className={variant === 'sheet' ? sheetPanelClass
              : variant === 'palette' ? palettePanelClass : dialogPanelClass}
            style={{ width }}
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
            ) : headerRight || variant === 'sheet' ? (
              // The sheet's header is a bordered bar rather than a heading with
              // margin under it, which is the drawer's existing chrome kept
              // exactly as it was.
              <div className={variant === 'sheet'
                ? 'flex items-center justify-between border-b border-line px-4 py-3'
                : 'mb-4 flex items-center justify-between'}>
                <DialogPrimitive.Title className={variant === 'sheet'
                  ? 'font-display text-[15px] font-semibold'
                  : 'font-display text-[16px] font-semibold text-text'}>
                  {title}
                </DialogPrimitive.Title>
                {headerRight}
              </div>
            ) : (
              <DialogPrimitive.Title className="font-display text-[16px] font-semibold text-text">
                {title}
              </DialogPrimitive.Title>
            )}
            {description && (
              <DialogPrimitive.Description className="mt-2 text-[13px] text-text-2">
                {description}
              </DialogPrimitive.Description>
            )}
            {children}
          </DialogPrimitive.Content>
        </DialogPrimitive.Overlay>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  )
}
