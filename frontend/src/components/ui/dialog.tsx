import type { ReactNode } from 'react'
import * as DialogPrimitive from '@radix-ui/react-dialog'

import { Button } from './button'
import { Icon } from './icon'
import {
  dialogFitPanelClass, dialogOverlayClass, dialogPanelClass, dialogScrollBodyClass,
  dialogScrollPanelClass, paletteOverlayClass, palettePanelClass, useRadixClose,
} from './overlay'

/**
 * The one modal in the product. Radix owns the hard parts — Escape, focus
 * trap, focus restore, aria-modal, scroll lock; we own only the look.
 *
 * Mounting model: render it when open, unmount to close. onClose fires for
 * Escape, the X, and (palette only) an outside click. A standard dialog no
 * longer closes on an outside click: a stray click on browser UI (e.g. a
 * password manager's save prompt) used to dismiss it and lose whatever had
 * been typed.
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
  /** Panel width. A number is px; a string is any CSS width, which is how a
   *  panel asks for a share of the WINDOW rather than a fixed size. The 92vw
   *  cap is applied for you either way, so a percentage cannot push the panel
   *  off screen on a narrow one. */
  width?: number | string
  /** 'palette' sits high and hides its heading (the command palette names
   *  itself through its input). */
  variant?: 'center' | 'palette'
  /** Sits on the title's row, pushed right. */
  headerRight?: ReactNode
  /** Caps the panel height and scrolls the BODY, leaving the heading in place.
   *  Opt-in: a dialog that fits on screen must not grow a scroll container it
   *  never needed. The cap lives in overlay.ts, so a call site cannot pick
   *  its own. */
  scrollBody?: boolean
  /** Drops `width` and sizes the panel to its content, capped at 80vw/80vh
   *  (dialogFitPanelClass). Unlike scrollBody this does NOT wrap the children
   *  in a scroller: the body child owns the scrolling, so a `fit` child must
   *  carry min-h-0 and its own overflow. */
  fit?: boolean
  onClose: () => void
  children: ReactNode
}) {
  const { open, requestClose, onCloseAutoFocus } = useRadixClose(onClose)
  // Empty string unless the panel is a capped flex column, so a dialog that
  // opts into neither emits the exact same class strings it did before.
  const shrink = scrollBody || fit ? ' shrink-0' : ''
  const isPalette = variant === 'palette'
  // The palette is a deliberate exception, not an oversight: it hides its
  // heading, names itself through its input, and conventionally dismisses on
  // an outside click. It has no header row to hang an X on. Every other
  // dialog blocks outside clicks; the X is the only pointer way out.
  const closeButton = isPalette ? null : (
    // DialogPrimitive.Close rather than an onClick calling onClose directly,
    // so this goes through the same context.onOpenChange -> requestClose path
    // Escape already used, preserving the close animation/focus-restore
    // contract useRadixClose sets up.
    <DialogPrimitive.Close asChild>
      {/* "Close dialog" rather than the shorter "Close": several dialogs also
          show their own in-body "Close" button once a job finishes (the
          JobLog done state), and two controls both named "Close" in the same
          dialog is a real ambiguity for a screen reader user, not only a
          test-query collision. */}
      <Button variant="ghost" size="icon-xs" aria-label="Close dialog" className="shrink-0">
        <Icon name="close" size={16} />
      </Button>
    </DialogPrimitive.Close>
  )
  return (
    <DialogPrimitive.Root open={open} onOpenChange={requestClose}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className={isPalette ? paletteOverlayClass : dialogOverlayClass}>
          <DialogPrimitive.Content
            onCloseAutoFocus={onCloseAutoFocus}
            // Radix runs a pointer-down-outside or a focus-outside interaction
            // through onInteractOutside right after its own more specific
            // callback, using the SAME event object, and only dismisses if
            // that event is still not defaultPrevented (see
            // @radix-ui/react-dismissable-layer's usePointerDownOutside and
            // useFocusOutside). Preventing default here therefore blocks both
            // outside pointer and outside focus, not only one of them. The
            // palette is left wired to the default (dismiss), on purpose.
            onInteractOutside={isPalette ? undefined : (event) => event.preventDefault()}
            // Escape is untouched: onEscapeKeyDown is not set, so Radix's
            // default (call onDismiss) still runs.
            aria-modal="true"
            className={isPalette ? palettePanelClass
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
            {isPalette ? (
              // Radix requires a Title. The palette has never shown one, and
              // adding a visible heading above the search field would be a
              // change to the design, not to the accessibility.
              <DialogPrimitive.Title className="sr-only">{title}</DialogPrimitive.Title>
            ) : headerRight ? (
              <div className={`mb-4 flex items-center justify-between${shrink}`}>
                <DialogPrimitive.Title className="font-display text-[16px] font-semibold text-text">
                  {title}
                </DialogPrimitive.Title>
                {/* headerRight and the X share this row so they can never
                    overlap: headerRight stays exactly where it was, with the
                    X pushed to its right. */}
                <div className="flex shrink-0 items-center gap-2">
                  {headerRight}
                  {closeButton}
                </div>
              </div>
            ) : (
              <div className={`flex items-center justify-between${shrink}`}>
                <DialogPrimitive.Title className={`font-display text-[16px] font-semibold text-text${shrink}`}>
                  {title}
                </DialogPrimitive.Title>
                {closeButton}
              </div>
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
