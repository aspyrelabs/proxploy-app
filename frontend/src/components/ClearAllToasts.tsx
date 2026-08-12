import { toast, useSonner } from 'sonner'

/** One control to dismiss every toast at once.
 *
 *  Only shown from two toasts up: sonner's own close button already handles a
 *  single one, and a "clear all" beside one item is two controls for the same
 *  action.
 *
 *  The count comes from sonner's own store via useSonner() rather than from a
 *  counter of our own, because toasts also disappear on their duration timer
 *  and on the per-toast x — a hand-kept tally would drift out of sync with
 *  what is actually on screen. */
export function ClearAllToasts() {
  const { toasts } = useSonner()
  if (toasts.length < 2) return null
  return (
    <div className="fixed bottom-2 right-4 z-[9999]">
      <button type="button" onClick={() => toast.dismiss()}
        className="rounded-ctl border border-line bg-panel-2 px-2.5 py-1 text-[11px]
                   text-text-2 shadow-lg transition hover:bg-elev hover:text-text">
        Clear all ({toasts.length})
      </button>
    </div>
  )
}
