import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { api } from '../api/client'
import { useChannelFields, useNotificationKinds } from '../api/notificationKinds'
import type { NotificationKind } from '../api/notificationKinds'
import type { ChannelRow } from './ChannelForm'
import { Button } from './ui/button'
import {
  KindFields, allRequiredFilled, defaultsFor, fieldErrors, inputClass,
} from './KindFields'

/**
 * Rename a channel, and replace its credentials without losing it.
 *
 * Credentials are replace-only rather than editable: `_out` never returned the
 * URL and the stored secret is not recoverable, so there is nothing to
 * prefill. Editing keeps the channel's id — deleting and re-adding would lose
 * its Events-matrix column and everything ticked in it.
 */
export function ChannelEditForm({ channel, onSaved, onCancel }: {
  channel: ChannelRow
  onSaved: () => void
  onCancel: () => void
}) {
  const kinds = useNotificationKinds()
  const saved = useChannelFields(channel.id)
  const [name, setName] = useState(channel.name)
  const [replacing, setReplacing] = useState(false)
  const [kind, setKind] = useState(channel.kind)
  const [fields, setFields] = useState<Record<string, string>>({})
  const [error, setError] = useState<string | null>(null)

  const service: NotificationKind | undefined =
    kinds.data?.find((k) => k.kind === kind)

  // What the channel already had, when the service has not been switched
  // away from. Correcting one mistyped password should not mean re-entering
  // the server and the topic as well. Secrets are absent from `saved` by
  // design and stay blank; the server keeps the stored one for any secret
  // sent empty.
  const prefill = kind === channel.kind ? (saved.data?.fields ?? {}) : {}
  const secretsSet = kind === channel.kind ? (saved.data?.secrets_set ?? []) : []
  // Folded in at render rather than seeded into state on click: the Replace
  // button exists before either query has resolved, so seeding on click races
  // the fetch and leaves a field that ships with a default blank.
  const values = { ...defaultsFor(service), ...prefill, ...fields }

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
    && (!replacing || allRequiredFilled(service, values, secretsSet))

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
            {saved.data?.known === false
              ? 'This channel was added before Proxploy kept its details, so replacing them means entering them all again.'
              : 'Its details are saved. Replacing lets you correct any of them, and anything secret stays as it is unless you type a new one.'}
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
              <Button size="sm" key={k.kind}
                      variant={k.kind === kind ? 'primary' : 'ghost'}
                      aria-pressed={k.kind === kind}
                      onClick={() => switchService(k.kind)}>
                {k.label}
              </Button>
            ))}
          </div>
          {service && (
            <KindFields service={service} values={values} errors={errors}
                        idPrefix="ed" keepBlank={secretsSet}
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
