import type { ReactNode } from 'react'
import * as DialogPrimitive from '@radix-ui/react-dialog'

import { Button } from './button'
import { Icon } from './icon'
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
 * be open, unmount it to close. onClose fires for Escape, for the X in a
 * standard dialog, and (for the palette only, see below) for an outside
 * click. A standard dialog no longer closes on an outside click: a stray
 * click on browser UI that has nothing to do with the app, such as a
 * password manager's save prompt, used to dismiss the dialog and lose
 * whatever had been typed into it.
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
  const isPalette = variant === 'palette'
  // The palette is a deliberate exception, not an oversight: it hides its
  // heading and names itself through its input, and a command palette
  // conventionally dismisses on an outside click, the way this one always
  // has. It also has no header row to hang an X on. Every other dialog gets
  // the new behaviour: outside clicks are blocked, and the X is the only
  // pointer-driven way out.
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
                    overlap: headerRight (e.g. the VM wizard's step pills)
                    stays exactly where it was, with the X pushed to its
                    right. */}
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
