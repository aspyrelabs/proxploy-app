import type { ReactNode } from 'react'
import * as AlertDialogPrimitive from '@radix-ui/react-alert-dialog'

import { Button } from './button'
import { dialogOverlayClass, dialogPanelClass, useRadixClose } from './overlay'

/**
 * The destructive modal: removing a host, uninstalling an app, confirming an
 * action against the container Proxploy itself runs in.
 *
 * Separate from Dialog because the behaviour genuinely differs. Radix's
 * AlertDialog does not close on a click outside and focuses the cancel control
 * first, which is what you want when the panel is asking whether to destroy
 * something. role="alertdialog" also tells a screen reader this is not a
 * routine form.
 *
 * The typed-name confirmation gate is NOT here. It lives in the call sites
 * that need it, because what counts as a correct phrase is theirs to decide.
 */
export function AlertDialog({
  title,
  description,
  onCancel,
  onOpenAutoFocus,
  children,
}: {
  title: string
  description: ReactNode
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
            className={`w-[420px] max-w-[92vw] ${dialogPanelClass}`}
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
