import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { api } from '../api/client'
import { useNotificationKinds } from '../api/notificationKinds'
import type { NotificationKind } from '../api/notificationKinds'
import { Button } from './ui/button'
import { Skeleton, SkeletonGroup } from './ui/skeleton'
import {
  KindFields, allRequiredFilled, defaultsFor, fieldErrors, inputClass,
} from './KindFields'

export type ChannelRow = {
  id: number; name: string; kind: string; events: string[]
  enabled: boolean; last_notified_at: string | null
}

/**
 * Pick the service, then answer that service's own questions.
 *
 * The URL is assembled server-side, not here: a password containing "@" or "/"
 * must be percent-encoded or it rewrites the URL into a different host, and
 * the server validates the assembled result with Apprise's parser before
 * storing it, so a channel cannot save cleanly and then silently never
 * deliver.
 *
 * `events` posts empty on purpose: empty already means "every event"
 * server-side (routing is the Events matrix's job).
 */
export function ChannelForm({ onSaved }: { onSaved: () => void }) {
  const kinds = useNotificationKinds()
  const [picked, setPicked] = useState<string | null>(null)
  const [name, setName] = useState('')
  const [fields, setFields] = useState<Record<string, string>>({})
  const [error, setError] = useState<string | null>(null)

  const service: NotificationKind | undefined =
    kinds.data?.find((k) => k.kind === picked)

  const choose = (kind: string) => {
    setPicked(kind)
    setError(null)
    setFields(defaultsFor(kinds.data?.find((k) => k.kind === kind)))
  }

  const save = useMutation({
    mutationFn: () =>
      api<ChannelRow>('/notifications/channels', {
        method: 'POST',
        body: JSON.stringify({ name, kind: picked, fields, events: [] }),
      }),
    onSuccess: () => {
      setPicked(null); setName(''); setFields({}); setError(null)
      onSaved()
    },
    // The server's 422 names the field that is missing, or the details Apprise
    // would not take. Replacing that with "Could not add that channel" throws
    // away the only part that tells the operator what to fix.
    onError: (e: unknown) =>
      setError((e as { detail?: string })?.detail
        || 'Could not add that channel, check the details and try again.'),
  })

  if (picked === null) {
    return (
      <div className="space-y-3">
        <p className="text-[12px] text-text-3">Where should notifications go?</p>
        {kinds.isPending && (
          // The grid is twenty tiles, so an empty box for the length of the
          // fetch reads as "no services" rather than as "not yet".
          <SkeletonGroup label="Loading services" className="flex flex-wrap gap-2">
            {Array.from({ length: 8 }, (_, i) => (
              <Skeleton key={i} className="h-[30px] w-24 rounded-ctl" />
            ))}
          </SkeletonGroup>
        )}
        <div className="flex flex-wrap gap-2">
          {kinds.data?.map((k) => (
            <Button key={k.kind} variant="ghost" onClick={() => choose(k.kind)}>
              {k.label}
            </Button>
          ))}
        </div>
      </div>
    )
  }

  const errors = fieldErrors(service, fields)
  const ready = name && Object.keys(errors).length === 0
    && allRequiredFilled(service, fields)

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <Button variant="ghost" onClick={() => { setPicked(null); setError(null) }}>
          Back
        </Button>
        <span className="text-[13px] text-text-2">{service?.label}</span>
        {service && (
          <a className="text-[11.5px] text-text-3 underline" href={service.setup_url}
             target="_blank" rel="noreferrer">How to set this up</a>
        )}
      </div>

      <div>
        <label className="block text-[12px] text-text-3" htmlFor="ch-name">Name</label>
        <input id="ch-name" className={inputClass} value={name}
               onChange={(e) => setName(e.target.value)}
               placeholder={`My ${service?.label}`} />
      </div>

      {service && (
        <KindFields service={service} values={fields} errors={errors}
                    onChange={(k, v) => setFields((p) => ({ ...p, [k]: v }))} />
      )}

      {error && <div className="text-[12px] text-red">{error}</div>}
      <Button disabled={!ready || save.isPending} onClick={() => save.mutate()}>
        Add channel
      </Button>
    </div>
  )
}
