import { type ReactNode, useRef, useState } from 'react'

import { AlertDialog, AlertDialogAction, AlertDialogCancel } from './ui/alert-dialog'

/** The typed gate is deliberately ours, not Radix's: the phrase and the
 *  disabled-until-match rule are product logic, not modal behaviour. */
export function ConfirmSelfDialog({ phrase, detail, title, children, onConfirm, onCancel }: {
  phrase: string
  detail: string
  /** Defaults to the self-CT heading; network apply and in-place restore pass
   *  their own. */
  title?: string
  /** Rendered above the typed field for the audit-log-clear caller, which
   *  needs an "older than" cutoff as well as a confirm. */
  children?: ReactNode
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
      // Radix focuses the cancel control first (right for a yes/no prompt);
      // this one asks you to type a name, so the caret belongs in the field.
      onOpenAutoFocus={(event) => { event.preventDefault(); input.current?.focus() }}
    >
      {children}
      {/* The phrase is a code chip because it is the one string the operator
          must reproduce exactly; its boundaries must stay unambiguous for
          names with spaces or trailing punctuation. */}
      <label className="mt-4 block text-[12px] text-text-3" htmlFor="self-confirm">
        Type{' '}
        <span className="mx-0.5 inline-block rounded border border-line bg-panel-2
                         px-1.5 py-0.5 font-mono text-[12px] text-text">
          {phrase}
        </span>{' '}
        to confirm
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
