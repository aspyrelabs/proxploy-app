import { useState } from 'react'
import { Button } from './ui/button'

/**
 * Doc 06: destructive actions against the CT Proxploy itself runs in route
 * through a stronger typed-confirmation instead of the one-click action, with
 * an explicit warning that stopping it can strand its own recovery path.
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
  return (
    <div role="dialog" aria-label="Confirm destructive action"
         className="fixed inset-0 z-30 grid place-items-center bg-scrim backdrop-blur-[3px]">
      <div className="w-[420px] max-w-[92vw] rounded-card border border-line bg-panel p-5">
        <h2 className="font-display text-[16px] font-semibold text-amber">
          {title ?? "This is Proxploy's own container"}
        </h2>
        <p className="mt-2 text-[13px] text-text-2">{detail}</p>
        <label className="mt-4 block text-[12px] text-text-3" htmlFor="self-confirm">
          Type <span className="font-mono text-text">{phrase}</span> to confirm
        </label>
        <input
          id="self-confirm"
          className="mt-1 w-full rounded-ctl border border-line bg-panel px-3 py-1.5 font-mono text-[13px] text-text focus:outline-none focus:ring-1 focus:ring-amber"
          value={typed}
          onChange={(e) => setTyped(e.target.value)}
          autoFocus
        />
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="ghost" onClick={onCancel}>Cancel</Button>
          <Button variant="danger" disabled={typed !== phrase}
                  onClick={() => onConfirm(typed)}>
            Confirm
          </Button>
        </div>
      </div>
    </div>
  )
}
