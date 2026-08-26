import { useRef, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'

import { api, apiErrorDetail } from '../api/client'
import { useDetectPorts } from '../api/apps-ports'
import type { AppRow } from '../api/hooks'
import { notify } from '../lib/notify'
import { Button } from './ui/button'
import { Dialog } from './ui/dialog'
import { IconTile } from './IconTile'
import { inputCls } from './LoginForm'
import { RAMP, monogram } from '../lib/app-identity'

/**
 * Finish setting up an app Proxploy did not install (adopted by hand, so no
 * port or icon came from the store). Asks for the port and the tile, both
 * unvalidated: the port is a guess, the tile is decoration.
 */
export function AppSetupDialog({ app, onClose }: { app: AppRow; onClose: () => void }) {
  const qc = useQueryClient()
  const detect = useDetectPorts(app.id)
  const [port, setPort] = useState(app.web_port != null ? String(app.web_port) : '')
  const [initials, setInitials] = useState(app.icon_initials ?? monogram(app.name))
  const [colors, setColors] = useState(app.icon_colors ?? RAMP[0])
  const [error, setError] = useState('')
  const fileRef = useRef<HTMLInputElement>(null)
  // The uploaded icon, once there is one, is what IconTile draws instead of
  // the monogram. Held locally so the tile updates the instant the upload
  // returns rather than after the apps query refetches.
  const [iconUrl, setIconUrl] = useState<string | null>(
    app.icon_url?.startsWith(`/api/v1/apps/${app.id}/icon`) ? app.icon_url : null)

  const upload = useMutation({
    mutationFn: (f: File) => {
      const form = new FormData()
      form.append('file', f)
      return api<{ icon_url: string }>(`/apps/${app.id}/icon`,
                                       { method: 'PUT', body: form })
    },
    onSuccess: (r) => {
      setError('')
      setIconUrl(r.icon_url)
      qc.invalidateQueries({ queryKey: ['apps'] })
    },
    onError: (e) => setError(apiErrorDetail(e, 'Could not use that image.')),
  })

  const clearIcon = useMutation({
    mutationFn: () => api(`/apps/${app.id}/icon`, { method: 'DELETE' }),
    onSuccess: () => {
      setIconUrl(null)
      qc.invalidateQueries({ queryKey: ['apps'] })
    },
    onError: (e) => setError(apiErrorDetail(e, 'Could not remove the image.')),
  })

  const save = useMutation({
    mutationFn: () => api(`/apps/${app.id}`, {
      method: 'PATCH',
      body: JSON.stringify({
        ...(port.trim() !== '' ? { web_port: Number(port) } : {}),
        icon_initials: initials.slice(0, 3),
        icon_colors: colors,
      }),
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['apps'] })
      notify.success('Saved.')
      onClose()
    },
    onError: (e) => setError(apiErrorDetail(e, 'Could not save that.')),
  })

  return (
    <Dialog title={`Finish setting up ${app.name}`} width={460} onClose={onClose}>
      <div className="mt-4 space-y-4">
        <div>
          <span className="mb-1 block text-[11px] uppercase tracking-wide text-text-3">
            Web port
          </span>
          <p className="mb-2 text-[12px] text-text-3">
            Proxploy installed apps carry this from the store. This one was
            adopted, so it has to come from you or from a look inside.
          </p>
          <div className="flex items-center gap-2">
            <input className={inputCls} type="number" min={1} placeholder="e.g. 443"
                   aria-label="Web port"
                   value={port} onChange={(e) => setPort(e.target.value)} />
            <Button variant="ghost" size="sm" disabled={detect.isPending}
                    onClick={() => detect.mutate(undefined, {
                      onError: (e) => setError(apiErrorDetail(
                        e, 'Could not read the container ports.')),
                    })}>
              {detect.isPending ? 'Looking…' : 'Detect'}
            </Button>
          </div>
          {detect.data && (detect.data.ports.length === 0 ? (
            <p className="mt-1.5 text-[11.5px] text-text-3">
              Nothing was listening that a browser could reach. The app may be
              stopped, or it may only listen on localhost.
            </p>
          ) : (
            <div className="mt-1.5">
              <div className="flex flex-wrap gap-1">
                {detect.data.ports.map((c) => (
                  <Button key={c.port} size="sm"
                          variant={String(c.port) === port ? 'go' : 'ghost'}
                          title={`${c.process ?? 'unknown process'} on ${c.address}`}
                          onClick={() => setPort(String(c.port))}>
                    {c.port}{c.process ? ` · ${c.process}` : ''}
                  </Button>
                ))}
              </div>
              <p className="mt-1 text-[11.5px] text-text-3">
                A guess, not a reading from Proxmox, which does not know. Best
                first. Pick one and check it opens.
              </p>
            </div>
          ))}
        </div>

        <div>
          <span className="mb-1 block text-[11px] uppercase tracking-wide text-text-3">
            Tile
          </span>
          {/* No catalog entry (served_icon_url) means no icon; the initials
              tile is the icon it can have, and IconTile draws it everywhere. */}
          <p className="mb-2 text-[12px] text-text-3">
            {iconUrl
              ? 'Your image is what this app shows. The letters and colour '
                + 'below are what it falls back to if you remove it.'
              : 'Apps from the store bring their own logo. This one gets three '
                + 'letters and a colour. Change either, or upload an image.'}
          </p>
          <div className="flex items-center gap-3">
            <IconTile name={app.name} iconUrl={iconUrl} size={40}
                      initials={initials} colors={colors} />
            <input className={`${inputCls} w-20`} maxLength={3} aria-label="Tile letters"
                   value={initials}
                   onChange={(e) => setInitials(e.target.value.toUpperCase())} />
            <div className="flex flex-wrap gap-1">
              {RAMP.map((p) => (
                <button key={p.dark} type="button" aria-label={`Tile colour ${p.dark}`}
                        onClick={() => setColors(p)}
                        className={`mono-tile h-6 w-6 rounded-tile ${
                          p.dark === colors.dark
                            ? 'ring-2 ring-text ring-offset-2 ring-offset-panel'
                            : ''}`}
                        style={{ '--mono-dark': p.dark,
                                 '--mono-light': p.light } as React.CSSProperties} />
              ))}
            </div>
          </div>

          <div className="mt-3 flex flex-wrap items-center gap-2">
            <input ref={fileRef} type="file" className="hidden"
                   accept="image/png,image/jpeg,image/webp,image/gif,image/bmp"
                   onChange={(e) => {
                     const f = e.target.files?.[0]
                     if (f) upload.mutate(f)
                     e.target.value = ''
                   }} />
            <Button variant="ghost" size="sm" disabled={upload.isPending}
                    onClick={() => fileRef.current?.click()}>
              {upload.isPending ? 'Uploading…'
                : iconUrl ? 'Replace image' : 'Upload an image'}
            </Button>
            {iconUrl && (
              <Button variant="ghost" size="sm" disabled={clearIcon.isPending}
                      onClick={() => clearIcon.mutate()}>
                Remove image
              </Button>
            )}
            <span className="text-[11.5px] text-text-3">
              PNG, JPEG, WebP, GIF or BMP. Resized to 512x512.
            </span>
          </div>
        </div>

        {error && <p className="text-[12.5px] text-red">{error}</p>}

        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button disabled={save.isPending} onClick={() => { setError(''); save.mutate() }}>
            {save.isPending ? 'Saving…' : 'Save'}
          </Button>
        </div>
      </div>
    </Dialog>
  )
}
