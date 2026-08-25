import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'

import { api, apiErrorDetail } from '../api/client'
import { useDetectPorts } from '../api/apps-ports'
import type { AppRow } from '../api/hooks'
import { notify } from '../lib/notify'
import { Button } from './ui/button'
import { Dialog } from './ui/dialog'
import { IconTile } from './IconTile'
import { inputCls } from './LoginForm'

/** The tiles an app can wear. Pairs rather than single colours because
 *  IconTile draws a gradient, and picking two that go together is not
 *  something to make anyone do by hand. */
const PALETTES = [
  { c1: '#F5B544', c2: '#E79126' },
  { c1: '#5B9DF9', c2: '#3C6FD1' },
  { c1: '#34D3C6', c2: '#1FA192' },
  { c1: '#B389F5', c2: '#8257D1' },
  { c1: '#F58A8A', c2: '#D14F4F' },
  { c1: '#8DC63F', c2: '#5E9A22' },
]

/** Two letters off the name, which is what a person would have picked. */
function initialsFor(name: string): string {
  const words = name.split(/[^A-Za-z0-9]+/).filter(Boolean)
  if (words.length === 0) return '??'
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase()
  return (words[0][0] + words[1][0]).toUpperCase()
}

/**
 * Finish setting up an app Proxploy did not install.
 *
 * An app from the store arrives knowing its port and wearing its icon. One
 * adopted by hand knows neither, and the row simply hid the Open button, which
 * left the operator with nothing to click and nothing to read: the fix existed
 * only inside Reconfigure, which is not where anyone notices the problem.
 *
 * So the row offers this instead, and it asks for exactly the two things that
 * are missing. Both are optional in the sense that neither is validated
 * against reality: the port is a guess Proxploy is checking with you, and the
 * tile is decoration.
 */
export function AppSetupDialog({ app, onClose }: { app: AppRow; onClose: () => void }) {
  const qc = useQueryClient()
  const detect = useDetectPorts(app.id)
  const [port, setPort] = useState(app.web_port != null ? String(app.web_port) : '')
  const [initials, setInitials] = useState(app.icon_initials ?? initialsFor(app.name))
  const [colors, setColors] = useState(app.icon_colors ?? PALETTES[0])
  const [error, setError] = useState('')

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
              {/* The caveat lives with the numbers, every time they are shown. */}
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
          {/* Initials and a colour, not an upload. The icon a row draws comes
              from the CATALOG (served_icon_url), so an app with no catalog
              entry can never have one; the initials tile is the icon it can
              have, and IconTile already draws it everywhere. */}
          <p className="mb-2 text-[12px] text-text-3">
            Apps in the store bring their own logo. This one gets letters.
          </p>
          <div className="flex items-center gap-3">
            <IconTile name={app.name} iconUrl={null} size={40}
                      initials={initials} colors={colors} />
            <input className={`${inputCls} w-20`} maxLength={3} aria-label="Tile letters"
                   value={initials}
                   onChange={(e) => setInitials(e.target.value.toUpperCase())} />
            <div className="flex flex-wrap gap-1">
              {PALETTES.map((p) => (
                <button key={p.c1} type="button" aria-label={`Tile colour ${p.c1}`}
                        onClick={() => setColors(p)}
                        className={`h-6 w-6 rounded-tile border ${
                          p.c1 === colors.c1 ? 'border-amber' : 'border-line'}`}
                        style={{ background: `linear-gradient(150deg, ${p.c1}, ${p.c2})` }} />
              ))}
            </div>
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
