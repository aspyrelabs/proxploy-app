import { fieldError } from '../api/notificationKinds'
import type { KindField, NotificationKind } from '../api/notificationKinds'

export const inputClass = 'w-full rounded-ctl border border-line bg-panel px-3 py-1.5 text-[13px] text-text placeholder:text-text-3 focus:outline-none focus:ring-1 focus:ring-amber'

/** Every field of one service, with its rule enforced as you type.
 *
 *  Shared by the add form and the edit form rather than written twice: the
 *  two differ only in what happens on save, and a second copy is how the
 *  edit path ends up without the rules the add path has.
 */
export function KindFields({ service, values, errors, onChange, idPrefix = 'ch' }: {
  service: NotificationKind
  values: Record<string, string>
  errors: Record<string, string>
  onChange: (key: string, value: string) => void
  idPrefix?: string
}) {
  return (
    <>
      {service.fields.map((f: KindField) => {
        const id = `${idPrefix}-${f.key}`
        const err = errors[f.key]
        return (
          <div key={f.key}>
            <label className="block text-[12px] text-text-3" htmlFor={id}>
              {f.label}
              {!f.required && <span className="ml-1 text-text-3">(optional)</span>}
            </label>
            <input id={id} className={`${inputClass} ${err ? 'border-red' : ''}`}
                   type={f.secret ? 'password' : 'text'}
                   aria-invalid={err ? true : undefined}
                   aria-describedby={err ? `${id}-err` : undefined}
                   value={values[f.key] ?? ''} placeholder={f.placeholder}
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
 *  empty required field is not a rule failure, it is simply not done yet, and
 *  shouting "that is not right" at an untouched box is obnoxious. */
export function allRequiredFilled(service: NotificationKind | undefined,
                                  values: Record<string, string>): boolean {
  return (service?.fields ?? []).every((f) => !f.required || values[f.key])
}

/** The values a freshly picked service starts with: its defaults, so a field
 *  that ships with one (ntfy's ntfy.sh) shows it rather than an empty box. */
export function defaultsFor(service: NotificationKind | undefined): Record<string, string> {
  return Object.fromEntries((service?.fields ?? []).map((f) => [f.key, f.default]))
}
