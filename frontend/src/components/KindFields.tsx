import { fieldError } from '../api/notificationKinds'
import type { KindField, NotificationKind } from '../api/notificationKinds'
import { InfoHint } from './ui/info-hint'

export const inputClass = 'w-full rounded-ctl border border-line bg-panel px-3 py-1.5 text-[13px] text-text placeholder:text-text-3 focus:outline-none focus:ring-1 focus:ring-amber'

/** Every field of one service, with its rule enforced as you type. Shared by
 *  add and edit forms; a second copy is how the edit path loses the rules. */
export function KindFields({ service, values, errors, onChange, idPrefix = 'ch',
                            keepBlank = [] }: {
  service: NotificationKind
  values: Record<string, string>
  errors: Record<string, string>
  onChange: (key: string, value: string) => void
  idPrefix?: string
  /** Secret fields the server already holds a value for. Blank here means
   *  "keep what you have", so the box says so instead of looking unfilled. */
  keepBlank?: string[]
}) {
  return (
    <>
      {service.fields.map((f: KindField) => {
        const id = `${idPrefix}-${f.key}`
        const err = errors[f.key]
        return (
          <div key={f.key}>
            {/* The (i) sits BESIDE the label, not inside it. A button nested
                in a label is labelled by that label implicitly, so every field
                ended up with two elements answering to its name. */}
            <div className="flex items-center gap-1.5">
              <label className="text-[12px] text-text-3" htmlFor={id}>
                {f.label}
                {!f.required && <span className="ml-1 text-text-3">(optional)</span>}
              </label>
              {/* The example lives here rather than under the field, where
                  `help` already sits: a secret field has no placeholder to
                  borrow, so for a token box this is the only thing that
                  answers "what shape is this meant to be". */}
              <InfoHint text={hintText(f)} />
            </div>
            <input id={id} className={`${inputClass} ${err ? 'border-red' : ''}`}
                   type={f.secret ? 'password' : 'text'}
                   aria-invalid={err ? true : undefined}
                   aria-describedby={err ? `${id}-err` : undefined}
                   value={values[f.key] ?? ''}
                   placeholder={keepBlank.includes(f.key)
                     ? 'Leave blank to keep the saved one'
                     : f.placeholder}
                   onChange={(e) => onChange(f.key, e.target.value)} />
            {err
              ? <p id={`${id}-err`} className="mt-1 text-[11.5px] text-red">{err}</p>
              : f.help && <p className="mt-1 text-[11.5px] text-text-3">{f.help}</p>}
          </div>
        )
      })}
    </>
  )
}

/** What the (i) says: the rule first when there is one, then an example. */
export function hintText(f: KindField): string {
  const parts = [f.hint, f.example && `Example: ${f.example}`].filter(Boolean)
  return parts.join(' ')
}

/** Every rule broken right now, keyed by field. Empty means ready to send. */
export function fieldErrors(service: NotificationKind | undefined,
                            values: Record<string, string>): Record<string, string> {
  const out: Record<string, string> = {}
  for (const f of service?.fields ?? []) {
    const e = fieldError(f, values[f.key] ?? '')
    if (e) out[f.key] = e
  }
  return out
}

/** Are all the required ones filled in? Separate from fieldErrors because an
 *  empty required field is not a rule failure, it is simply not done yet. */
export function allRequiredFilled(service: NotificationKind | undefined,
                                  values: Record<string, string>,
                                  alreadySet: string[] = []): boolean {
  // A secret the server already holds is not missing, it is unchanged. Without
  // alreadySet, Save stays disabled forever on an edit that only corrects a
  // hostname, because the token box is required and deliberately blank.
  return (service?.fields ?? []).every(
    (f) => !f.required || values[f.key] || alreadySet.includes(f.key))
}

/** The values a freshly picked service starts with: its defaults, so a field
 *  that ships with one (ntfy's ntfy.sh) shows it rather than an empty box. */
export function defaultsFor(service: NotificationKind | undefined): Record<string, string> {
  return Object.fromEntries((service?.fields ?? []).map((f) => [f.key, f.default]))
}
