import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { api } from '../api/client'
import { useEntitlements } from '../api/hooks'
import { Button } from './ui/button'

export type ChannelRow = {
  id: number; name: string; kind: string; events: string[]
  enabled: boolean; last_notified_at: string | null
}

// Doc 04's example event list. Empty means "all events" server-side, but a
// fresh ntfy target shouldn't buzz on every start/stop, so the form defaults
// to job.failed (plan decision 8).
export const EVENT_CHOICES = [
  'job.failed', 'job.succeeded', 'job.canceled', 'job.interrupted', 'alert.fired', 'app.updated',
] as const

const input = 'w-full rounded-ctl border border-line bg-panel px-3 py-1.5 text-[13px] text-text placeholder:text-text-3 focus:outline-none focus:ring-1 focus:ring-amber'

export function ChannelForm({ onSaved }: { onSaved: () => void }) {
  const ent = useEntitlements()
  // Same wait-for-first-fetch pattern as LifecycleActions.tsx: `has()`
  // defaults to false until /entitlements resolves, so gating the fieldset
  // on `!has(...)` directly locked event routing for every plan (Pro
  // included) during the initial fetch, not just for plans that lack it.
  const routingAllowed = ent.data != null && ent.has('notify.routing')
  const [name, setName] = useState('')
  const [url, setUrl] = useState('')
  const [events, setEvents] = useState<string[]>(['job.failed'])
  const [error, setError] = useState<string | null>(null)

  const save = useMutation({
    mutationFn: () =>
      api<ChannelRow>('/notifications/channels', {
        method: 'POST',
        body: JSON.stringify({ name, url, events }),
      }),
    onSuccess: () => {
      setName(''); setUrl(''); setEvents(['job.failed']); setError(null)
      onSaved()
    },
    onError: () => setError('Could not add that channel, check the Apprise URL.'),
  })

  const toggle = (e: string) =>
    setEvents((prev) => (prev.includes(e) ? prev.filter((x) => x !== e) : [...prev, e]))

  return (
    <div className="space-y-3">
      <div>
        <label className="block text-[12px] text-text-3" htmlFor="ch-name">Name</label>
        <input id="ch-name" className={input} value={name}
               onChange={(e) => setName(e.target.value)} placeholder="Home ntfy" />
      </div>
      <div>
        <label className="block text-[12px] text-text-3" htmlFor="ch-url">Apprise URL</label>
        <input id="ch-url" className={`${input} font-mono`} value={url}
               onChange={(e) => setUrl(e.target.value)}
               placeholder="ntfy://ntfy.sh/your-topic" />
        <p className="mt-1 text-[11.5px] text-text-3">
          Stored encrypted and never shown again. ntfy, gotify, email, Telegram,
          Slack and generic webhooks are all supported.
        </p>
      </div>
      <fieldset disabled={!routingAllowed}>
        <legend className="text-[12px] text-text-3">
          Send on {!routingAllowed && '(Pro: event routing)'}
        </legend>
        <div className="mt-1 flex flex-wrap gap-3">
          {EVENT_CHOICES.map((e) => (
            <label key={e} className="flex items-center gap-1.5 font-mono text-[11.5px] text-text-2">
              <input type="checkbox" aria-label={e} checked={events.includes(e)}
                     onChange={() => toggle(e)} />
              {e}
            </label>
          ))}
        </div>
      </fieldset>
      {error && <div className="text-[12px] text-red">{error}</div>}
      <Button disabled={!name || !url || save.isPending} onClick={() => save.mutate()}>
        Add channel
      </Button>
    </div>
  )
}
