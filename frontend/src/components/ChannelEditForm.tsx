import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { api } from '../api/client'
import { useNotificationKinds } from '../api/notificationKinds'
import type { NotificationKind } from '../api/notificationKinds'
import type { ChannelRow } from './ChannelForm'
import { Button } from './ui/button'
import {
  KindFields, allRequiredFilled, defaultsFor, fieldErrors, inputClass,
} from './KindFields'

/**
 * Rename a channel, and replace its credentials without losing it.
 *
 * Credentials are replace-only rather than editable, and that is a property of
 * the data rather than a shortcut: `_out` has never returned the URL and the
 * stored value is not recoverable, so there is nothing to prefill. Showing
 * dots in a box that cannot be read back would be a lie about what the form
 * is doing.
 *
 * The point of editing at all is the id. Rotating a bot token by deleting the
 * channel and adding it again loses its column in the Events matrix and
 * everything ticked in it; an edit keeps both.
 */
export function ChannelEditForm({ channel, onSaved, onCancel }: {
  channel: ChannelRow
  onSaved: () => void
  onCancel: () => void
}) {
  const kinds = useNotificationKinds()
  const [name, setName] = useState(channel.name)
  const [replacing, setReplacing] = useState(false)
  const [kind, setKind] = useState(channel.kind)
  const [fields, setFields] = useState<Record<string, string>>({})
  const [error, setError] = useState<string | null>(null)

  const service: NotificationKind | undefined =
    kinds.data?.find((k) => k.kind === kind)

  // Defaults are folded in at render rather than seeded into state on click.
  // The Replace button exists before the kinds query has resolved, so seeding
  // on click races the fetch and leaves a field that ships with a default
  // (ntfy's ntfy.sh) blank. Switching service still clears what was typed, so
  // a Gotify token cannot ride along into an ntfy channel.
  const values = { ...defaultsFor(service), ...fields }

  const switchService = (next: string) => {
    setKind(next)
    setFields({})
  }

  const save = useMutation({
    mutationFn: () =>
      api<ChannelRow>(`/notifications/channels/${channel.id}`, {
        method: 'PATCH',
        // Sending kind and fields ONLY while replacing is what makes a rename
        // leave the stored credential alone: the server treats all three as
        // absent and touches nothing but the name.
        body: JSON.stringify(replacing ? { name, kind, fields: values } : { name }),
      }),
    onSuccess: () => { setError(null); onSaved() },
    onError: (e: unknown) =>
      setError((e as { detail?: string })?.detail
        || 'Could not save that change, check the details and try again.'),
  })

  const errors = replacing ? fieldErrors(service, values) : {}
  const ready = name && Object.keys(errors).length === 0
    && (!replacing || allRequiredFilled(service, values))

  return (
    <div className="space-y-3">
      <div>
        <label className="block text-[12px] text-text-3" htmlFor="ed-name">Name</label>
        <input id="ed-name" className={inputClass} value={name}
               onChange={(e) => setName(e.target.value)} />
      </div>

      {!replacing ? (
        <div className="flex items-center gap-2">
          <span className="text-[12px] text-text-3">
            Credentials are stored and cannot be shown again.
          </span>
          <Button variant="ghost" onClick={() => setReplacing(true)}>
            Replace credentials
          </Button>
        </div>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[12px] text-text-3">Service</span>
            {kinds.data?.map((k) => (
              <Button key={k.kind}
                      variant={k.kind === kind ? 'primary' : 'ghost'}
                      className="px-2 py-1 text-[11px]"
                      aria-pressed={k.kind === kind}
                      onClick={() => switchService(k.kind)}>
                {k.label}
              </Button>
            ))}
          </div>
          {service && (
            <KindFields service={service} values={values} errors={errors}
                        idPrefix="ed"
                        onChange={(k, v) => setFields((p) => ({ ...p, [k]: v }))} />
          )}
        </>
      )}

      {error && <div className="text-[12px] text-red">{error}</div>}
      <div className="flex gap-2">
        <Button disabled={!ready || save.isPending} onClick={() => save.mutate()}>
          Save
        </Button>
        <Button variant="ghost" onClick={onCancel}>Cancel</Button>
      </div>
    </div>
  )
}
