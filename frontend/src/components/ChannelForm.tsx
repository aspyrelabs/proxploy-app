import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { api } from '../api/client'
import { useNotificationKinds } from '../api/notificationKinds'
import type { NotificationKind } from '../api/notificationKinds'
import { Button } from './ui/button'

export type ChannelRow = {
  id: number; name: string; kind: string; events: string[]
  enabled: boolean; last_notified_at: string | null
}

const input = 'w-full rounded-ctl border border-line bg-panel px-3 py-1.5 text-[13px] text-text placeholder:text-text-3 focus:outline-none focus:ring-1 focus:ring-amber'

/** The escape hatch, kept as a 21st choice. Apprise reaches 142 services and
 *  the catalog names 20 of them, so someone who already knows the syntax for
 *  one of the other 122 must still be able to use it. */
const PASTE = '__paste__'

/**
 * Pick the service, then answer that service's own questions.
 *
 * This used to be a Name field and one "Apprise URL" box, which meant adding
 * Telegram required already knowing it is tgram://bottoken/ChatID. The 20
 * services we support were only ever a lookup that ran AFTER a URL was pasted,
 * to decide which badge to draw; nothing offered them.
 *
 * The URL is still assembled server-side rather than here. A password
 * containing "@" or "/" has to be percent-encoded or it rewrites the URL into
 * a different host, and the server can hand the assembled result to Apprise's
 * parser before storing it, so a channel cannot save cleanly and then silently
 * never deliver.
 *
 * `events` posts empty on purpose: which events reach a channel is the Events
 * matrix's job now, and empty already means "every event" server-side.
 */
export function ChannelForm({ onSaved }: { onSaved: () => void }) {
  const kinds = useNotificationKinds()
  const [picked, setPicked] = useState<string | null>(null)
  const [name, setName] = useState('')
  const [url, setUrl] = useState('')
  const [fields, setFields] = useState<Record<string, string>>({})
  const [error, setError] = useState<string | null>(null)

  const service: NotificationKind | undefined =
    kinds.data?.find((k) => k.kind === picked)

  const choose = (kind: string) => {
    setPicked(kind)
    setError(null)
    const chosen = kinds.data?.find((k) => k.kind === kind)
    // Seed the defaults so a field that ships with one (ntfy's ntfy.sh) shows
    // it rather than an empty box the operator has to guess at.
    setFields(Object.fromEntries(
      (chosen?.fields ?? []).map((f) => [f.key, f.default])))
  }

  const save = useMutation({
    mutationFn: () =>
      api<ChannelRow>('/notifications/channels', {
        method: 'POST',
        body: JSON.stringify(picked === PASTE
          ? { name, url, events: [] }
          : { name, kind: picked, fields, events: [] }),
      }),
    onSuccess: () => {
      setPicked(null); setName(''); setUrl(''); setFields({}); setError(null)
      onSaved()
    },
    // The server's 422 names the field that is missing or the details Apprise
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
        {kinds.isPending && <p className="text-[12px] text-text-3">Loading services…</p>}
        <div className="flex flex-wrap gap-2">
          {kinds.data?.map((k) => (
            <Button key={k.kind} variant="ghost" onClick={() => choose(k.kind)}>
              {k.label}
            </Button>
          ))}
          <Button variant="ghost" onClick={() => choose(PASTE)}>Paste a URL</Button>
        </div>
      </div>
    )
  }

  const ready = name && (picked === PASTE
    ? url
    : (service?.fields ?? []).every((f) => !f.required || fields[f.key]))

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <Button variant="ghost" onClick={() => { setPicked(null); setError(null) }}>
          Back
        </Button>
        <span className="text-[13px] text-text-2">
          {picked === PASTE ? 'Paste a URL' : service?.label}
        </span>
        {service && (
          <a className="text-[11.5px] text-text-3 underline" href={service.setup_url}
             target="_blank" rel="noreferrer">How to set this up</a>
        )}
      </div>

      <div>
        <label className="block text-[12px] text-text-3" htmlFor="ch-name">Name</label>
        <input id="ch-name" className={input} value={name}
               onChange={(e) => setName(e.target.value)}
               placeholder={picked === PASTE ? 'My webhook' : `My ${service?.label}`} />
      </div>

      {picked === PASTE ? (
        <div>
          <label className="block text-[12px] text-text-3" htmlFor="ch-url">Apprise URL</label>
          <input id="ch-url" className={`${input} font-mono`} value={url}
                 onChange={(e) => setUrl(e.target.value)}
                 placeholder="ntfy://ntfy.sh/your-topic" />
          <p className="mt-1 text-[11.5px] text-text-3">
            Stored encrypted and never shown again.
          </p>
        </div>
      ) : service?.fields.map((f) => (
        <div key={f.key}>
          <label className="block text-[12px] text-text-3" htmlFor={`ch-${f.key}`}>
            {f.label}
          </label>
          <input id={`ch-${f.key}`} className={input}
                 type={f.secret ? 'password' : 'text'}
                 value={fields[f.key] ?? ''} placeholder={f.placeholder}
                 onChange={(e) =>
                   setFields((prev) => ({ ...prev, [f.key]: e.target.value }))} />
          {f.help && <p className="mt-1 text-[11.5px] text-text-3">{f.help}</p>}
        </div>
      ))}

      {error && <div className="text-[12px] text-red">{error}</div>}
      <Button disabled={!ready || save.isPending} onClick={() => save.mutate()}>
        Add channel
      </Button>
    </div>
  )
}
