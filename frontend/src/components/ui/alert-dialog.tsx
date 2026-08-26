import type { ReactNode } from 'react'
import * as AlertDialogPrimitive from '@radix-ui/react-alert-dialog'

import { Button } from './button'
import { dialogOverlayClass, dialogPanelClass, useRadixClose } from './overlay'

/**
 * Destructive modal (host removal, app uninstall, etc.).
 *
 * Separate from Dialog: Radix AlertDialog does not close on click-outside,
 * focuses the cancel control first, and role="alertdialog" tells screen
 * readers this is not a routine form.
 *
 * Typed-name confirmation gate lives in call sites — they own the phrase.
 */
export function AlertDialog({
  title,
  description,
  onCancel,
  onOpenAutoFocus,
  width,
  children,
}: {
  title: ReactNode
  description: ReactNode
  /** Override panel width (default 420px). 92vw cap applies either way. */
  width?: number | string
  /** Escape and the cancel control both route here. */
  onCancel: () => void
  /** Override which control gets the caret on open. Radix picks the cancel
   *  button, which is right for a plain yes/no but wrong for a dialog whose
   *  job is to have you type something. */
  onOpenAutoFocus?: (event: Event) => void
  /** The action row. Use AlertDialogCancel and AlertDialogAction. */
  children: ReactNode
}) {
  const { open, requestClose, onCloseAutoFocus } = useRadixClose(onCancel)
  return (
    <AlertDialogPrimitive.Root open={open} onOpenChange={requestClose}>
      <AlertDialogPrimitive.Portal>
        <AlertDialogPrimitive.Overlay className={dialogOverlayClass}>
          <AlertDialogPrimitive.Content
            onCloseAutoFocus={onCloseAutoFocus}
            onOpenAutoFocus={onOpenAutoFocus}
            aria-modal="true"
            className={`${width == null ? 'w-[420px] ' : ''}max-w-[92vw] ${dialogPanelClass}`}
            style={width == null ? undefined : { width }}
          >
            <AlertDialogPrimitive.Title className="font-display text-[16px] font-semibold text-amber">
              {title}
            </AlertDialogPrimitive.Title>
            <AlertDialogPrimitive.Description asChild>
              <div className="mt-2 text-[13px] text-text-2">{description}</div>
            </AlertDialogPrimitive.Description>
            {children}
          </AlertDialogPrimitive.Content>
        </AlertDialogPrimitive.Overlay>
      </AlertDialogPrimitive.Portal>
    </AlertDialogPrimitive.Root>
  )
}

/** The way out. Radix gives this initial focus, which is the point. */
export function AlertDialogCancel({ children, onClick }: {
  children: ReactNode
  onClick?: () => void
}) {
  return (
    <AlertDialogPrimitive.Cancel asChild>
      <Button variant="ghost" onClick={onClick}>{children}</Button>
    </AlertDialogPrimitive.Cancel>
  )
}

/**
 * The destructive control. Deliberately not wired to close the dialog: the
 * host-removal flow answers a 409 by swapping the panel's contents for a
 * second step, and a control that always dismissed would lose it.
 */
export function AlertDialogAction({ children, onClick, disabled }: {
  children: ReactNode
  onClick?: () => void
  disabled?: boolean
}) {
  return (
    <Button variant="danger" disabled={disabled} onClick={onClick}>{children}</Button>
  )
}
