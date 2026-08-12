import {
  CheckCircleIcon,
  ExclamationTriangleIcon,
  InformationCircleIcon,
  XCircleIcon,
  XMarkIcon,
} from '@heroicons/react/24/outline'

/**
 * Vendored by hand from ReUI's `alert` component (https://reui.io/r/alert.json,
 * fetched 2026-08-12). The four severities asked for -- Information, Success,
 * Warning, (Error) -- are ReUI's *usage examples* `c-alert-5..8`; all four
 * render this one primitive with `variant="info"|"success"|"warning"|
 * "destructive"`. There was never a separate component per severity to vendor.
 *
 * Adapted for this codebase:
 *  - Colours come from tokens.css (`--blue`/`--green`/`--amber`/`--red` and
 *    their `-dim` fills), not shadcn's `--info`/`--success`/`--warning`/
 *    `--destructive`, which don't exist here. `-dim` is the same translucent
 *    fill StatusPill uses for its pill backgrounds -- the closest thing this
 *    codebase has to upstream's `bg-<colour>/4`. Border and icon take the
 *    solid colour, matching upstream's `border-<colour>/30 [&>svg]:text-
 *    <colour>`.
 *  - No `class-variance-authority`: four variants is a lookup object
 *    (VARIANT below), not worth a new dependency for.
 *  - No `cn` helper: this repo has no clsx/tailwind-merge; class lists are
 *    plain template literals.
 *  - Icons from @heroicons/react/24/outline (already a dependency) instead
 *    of upstream's lucide placeholders: InformationCircleIcon,
 *    CheckCircleIcon, ExclamationTriangleIcon, XCircleIcon.
 *  - Folded Alert/AlertTitle/AlertDescription/AlertAction into one component
 *    instead of shadcn's four-piece slot system: there is exactly one call
 *    site (LiveProvider's `toast.custom`) and it always wants icon + title +
 *    description + dismiss together, so upstream's composability for
 *    arbitrary children earns nothing here. What's kept, because it's the
 *    part worth having, is the shape that composability produces: the grid
 *    with a dedicated icon column, the title's `line-clamp-1`, the
 *    description's muted treatment, and `role="alert"`.
 *  - AlertAction (upstream's optional trailing action-button slot) is
 *    dropped: no call site here needs one.
 *  - `invert` and `default` variants dropped: nothing here needs a fifth or
 *    sixth kind of card.
 *  - Adds a dismiss button upstream's alert.tsx does not have at all: every
 *    card needs its own x (this replaces sonner's `<Toaster closeButton>`,
 *    which does not apply to a `toast.custom` card -- see AppShell.tsx /
 *    LiveProvider.tsx). `aria-label="Dismiss"` is upstream's icon-only close
 *    buttons' pattern, adapted since upstream's alert has no close button to
 *    borrow one from.
 *  - The outer `<li>` sonner wraps every toast in still carries this app's
 *    global `toastOptions.className` (border/bg/rounded panel chrome meant
 *    for plain-text toasts). Rather than let that box compete with this
 *    card's own severity-coloured border/bg, tokens.css strips it
 *    specifically for `toast.custom` toasts via the `data-styled="false"`
 *    attribute sonner already sets for exactly this case -- see the comment
 *    there.
 */

export type NotificationSeverity = 'info' | 'success' | 'warning' | 'destructive'

const ICON: Record<NotificationSeverity, typeof InformationCircleIcon> = {
  info: InformationCircleIcon,
  success: CheckCircleIcon,
  warning: ExclamationTriangleIcon,
  destructive: XCircleIcon,
}

// Split in two on purpose. The card needs an OPAQUE base (it floats over the
// page in the bell popover, not just over a panel) plus the translucent -dim
// tint on top. Both on one element would be two background-color utilities of
// equal specificity, so which one won would depend on the order Tailwind
// happened to emit them — a coin flip. Two elements, two backgrounds, no race.
const BORDER: Record<NotificationSeverity, string> = {
  info: 'border-blue',
  success: 'border-green',
  warning: 'border-amber',
  destructive: 'border-red',
}

const FILL: Record<NotificationSeverity, string> = {
  info: 'bg-blue-dim [&>svg]:text-blue',
  success: 'bg-green-dim [&>svg]:text-green',
  warning: 'bg-amber-dim [&>svg]:text-amber',
  destructive: 'bg-red-dim [&>svg]:text-red',
}

export function NotificationCard({
  severity, title, description, meta, onDismiss,
}: {
  severity: NotificationSeverity
  title: string
  /** The message itself. Never clamped: on a failure this is the reason, and
   *  a reason you cannot read is not a notification. */
  description?: string
  /** Label/value pairs shown beneath the message — target, timings, who asked
   *  for it. Rendered as a definition list so the pairing survives a screen
   *  reader. */
  meta?: [string, string][]
  onDismiss: () => void
}) {
  const Icon = ICON[severity]
  return (
    <div role="alert"
      className={`relative w-[400px] max-w-[calc(100vw-2rem)] overflow-hidden rounded-ctl border bg-panel text-[13px] shadow-[0_8px_24px_rgba(0,0,0,.28)] ${BORDER[severity]}`}
    >
      <div className={`grid grid-cols-[16px_1fr] items-start gap-x-2.5 gap-y-1 px-3 py-2.5 pr-8 ${FILL[severity]}`}>
        <Icon aria-hidden className="h-4 w-4 translate-y-0.5" />
        <div className="col-start-2 font-medium tracking-tight text-text">
          {title}
        </div>
        {description && (
          // break-words, no clamp: an error can be a long single token (a path,
          // a UUID, a command line) and must wrap rather than overflow.
          <div className="col-start-2 whitespace-pre-wrap break-words text-text-2">
            {description}
          </div>
        )}
        {meta && meta.length > 0 && (
          <dl className="col-start-2 mt-0.5 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 border-t border-line-soft pt-1.5 font-mono text-[11px]">
            {meta.map(([k, v]) => (
              <div key={k} className="contents">
                <dt className="text-text-3">{k}</dt>
                <dd className="break-words text-text-2">{v}</dd>
              </div>
            ))}
          </dl>
        )}
      </div>
      <button type="button" aria-label="Dismiss" onClick={onDismiss}
        className="absolute right-2 top-2 grid h-5 w-5 place-items-center rounded-tile text-text-3 hover:bg-elev hover:text-text"
      >
        <XMarkIcon aria-hidden className="h-3.5 w-3.5" />
      </button>
    </div>
  )
}
