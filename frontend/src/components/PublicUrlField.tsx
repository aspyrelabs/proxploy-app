import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import { Button } from './ui/button'
import { inputClass } from './KindFields'

/**
 * Where this installation lives, for the link at the bottom of a notification.
 *
 * Cannot be derived: `api_base_url` in the backend config is the licence
 * server, and the Host header is attacker-controllable, so a guess could link
 * to somebody else's installation in a message we sent. The suggestion is the
 * browser's own origin (whoever reads this page reached the app at the right
 * URL), offered unsaved because it may be a private LAN address nobody else
 * can resolve.
 */
export function PublicUrlField() {
  const qc = useQueryClient()
  // Its own endpoint rather than the generic /settings key-value route, which
  // keeps a deliberate allowlist and refuses fresh keys. It also validates the
  // scheme, which a generic write cannot: this string is interpolated into a
  // Markdown link in mail we send.
  const saved = useQuery({
    queryKey: ['notifications', 'public-url'],
    queryFn: () => api<{ url: string }>('/notifications/public-url'),
  })
  const [value, setValue] = useState('')
  const [done, setDone] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const stored = saved.data?.url ?? ''
  useEffect(() => { setValue(stored) }, [stored])

  const save = useMutation({
    mutationFn: () => api<{ url: string }>('/notifications/public-url', {
      method: 'PUT', body: JSON.stringify({ url: value }),
    }),
    onSuccess: () => {
      setDone(true); setError(null)
      qc.invalidateQueries({ queryKey: ['notifications', 'public-url'] })
    },
    onError: (e: unknown) =>
      setError((e as { detail?: string })?.detail
        || 'Could not save that address, check it and try again.'),
  })

  const suggestion = typeof window === 'undefined' ? '' : window.location.origin

  return (
    <div className="space-y-2 border-t border-line-soft pt-4">
      <label className="block text-[12px] text-text-3" htmlFor="public-url">
        This installation&apos;s address
      </label>
      <p className="text-[11.5px] text-text-3">
        Used for the link at the bottom of every notification. Leave it empty
        and notifications carry no link.
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <input id="public-url" className={`${inputClass} max-w-md`} value={value}
               placeholder="https://proxploy.example.com"
               onChange={(e) => { setValue(e.target.value); setDone(false); setError(null) }} />
        <Button disabled={value === stored || save.isPending}
                onClick={() => save.mutate()}>Save</Button>
        {suggestion && value !== suggestion && (
          <Button variant="ghost"
                  onClick={() => { setValue(suggestion); setDone(false); setError(null) }}>
            Use {suggestion}
          </Button>
        )}
        {done && !error && <span className="text-[12px] text-green">Saved</span>}
      </div>
      {error && <p className="text-[12px] text-red">{error}</p>}
    </div>
  )
}
