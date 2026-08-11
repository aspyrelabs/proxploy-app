import { useRef, useState } from 'react'

import { AlertDialog, AlertDialogAction, AlertDialogCancel } from './ui/alert-dialog'

/**
 * Doc 06: destructive actions against the CT Proxploy itself runs in route
 * through a stronger typed-confirmation instead of the one-click action, with
 * an explicit warning that stopping it can strand its own recovery path.
 *
 * The typed gate is deliberately ours, not Radix's. Radix supplies the modal
 * behaviour; what counts as a correct phrase, and the fact that the confirm
 * control stays disabled until it matches, is product logic.
 */
export function ConfirmSelfDialog({ phrase, detail, title, onConfirm, onCancel }: {
  phrase: string
  detail: string
  /** Defaults to the self-CT heading. Phase 6's network apply and in-place
   *  restore reuse the same typed-confirmation control for a different danger,
   *  and a false heading above the most destructive button in the product is
   *  worse than a prop. */
  title?: string
  onConfirm: (typed: string) => void
  onCancel: () => void
}) {
  const [typed, setTyped] = useState('')
  const input = useRef<HTMLInputElement>(null)

  return (
    <AlertDialog
      title={title ?? "This is Proxploy's own container"}
      description={detail}
      onCancel={onCancel}
      // Radix focuses the cancel control first, which is the right default for
      // a yes/no destructive prompt. This one asks you to type a name, so the
      // field is where the caret belongs. The gate below is what makes that
      // safe, not the focus order.
      onOpenAutoFocus={(event) => { event.preventDefault(); input.current?.focus() }}
    >
      <label className="mt-4 block text-[12px] text-text-3" htmlFor="self-confirm">
        Type <span className="font-mono text-text">{phrase}</span> to confirm
      </label>
      <input
        id="self-confirm"
        ref={input}
        className="mt-1 w-full rounded-ctl border border-line bg-panel px-3 py-1.5 font-mono text-[13px] text-text focus:outline-none focus:ring-1 focus:ring-amber"
        value={typed}
        onChange={(e) => setTyped(e.target.value)}
      />
      <div className="mt-4 flex justify-end gap-2">
        <AlertDialogCancel onClick={onCancel}>Cancel</AlertDialogCancel>
        <AlertDialogAction disabled={typed !== phrase} onClick={() => onConfirm(typed)}>
          Confirm
        </AlertDialogAction>
      </div>
    </AlertDialog>
  )
}
