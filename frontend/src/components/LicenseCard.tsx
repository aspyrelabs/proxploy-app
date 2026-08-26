import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError, api, apiErrorDetail } from '../api/client'
import { Button } from './ui/button'
import { Dialog } from './ui/dialog'
import { inputCls } from './LoginForm'

type Occupant = {
  installation_id: string
  last_seen_at: string | null
  activated_at: string | null
  stale: boolean
}

type Activation = {
  id: number
  installation_id: string
  status: string
  conflict_reason: string | null
  activated_at: string | null
  last_seen_at: string | null
  released_at: string | null
  release_reason: string | null
  current: boolean
}

/** "2 minutes ago". The owner is matching this against a server they know is
 *  either running or dead, so recency is the whole signal; an absolute
 *  timestamp makes them do the subtraction. */
function ago(iso: string | null): string {
  if (!iso) return 'never'
  const secs = Math.max(0, (Date.now() - new Date(iso + (iso.endsWith('Z') ? '' : 'Z')).getTime()) / 1000)
  if (secs < 90) return 'just now'
  const mins = Math.round(secs / 60)
  if (mins < 60) return `${mins} minutes ago`
  const hours = Math.round(mins / 60)
  if (hours < 48) return `${hours} hours ago`
  return `${Math.round(hours / 24)} days ago`
}

function shortId(id: string): string {
  return id.length > 12 ? id.slice(0, 8) : id
}

export function LicenseCard({ tier, licensed }: { tier: string; licensed: boolean }) {
  const qc = useQueryClient()
  const [key, setKey] = useState('')
  const [recovery, setRecovery] = useState('')
  const [occupant, setOccupant] = useState<Occupant | null>(null)
  const [showTransfer, setShowTransfer] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [showHistory, setShowHistory] = useState(false)

  const invalidate = () => qc.invalidateQueries({ queryKey: ['entitlements'] })

  const history = useQuery({
    queryKey: ['activations'],
    queryFn: () => api<{ activations: Activation[] }>('/entitlements/activations'),
    enabled: showHistory && licensed,
  })

  const activate = useMutation({
    mutationFn: () =>
      api('/entitlements/license', { method: 'POST', body: JSON.stringify({ license_key: key }) }),
    onSuccess: () => { setKey(''); setError(null); setOccupant(null); invalidate() },
    onError: (e: unknown) => {
      // 409 is not a failure the user can only read about: it is the one
      // error with an action attached, so it opens the transfer path instead
      // of landing in the error line with everything else.
      if (e instanceof ApiError && e.status === 409) {
        const body = e.body as { occupant?: Occupant }
        if (body?.occupant) { setOccupant(body.occupant); setError(null); return }
      }
      setError(apiErrorDetail(e, 'Could not activate this license.'))
    },
  })

  const transfer = useMutation({
    mutationFn: () =>
      api('/entitlements/license/transfer', {
        method: 'POST',
        body: JSON.stringify({ license_key: key, recovery_code: recovery }),
      }),
    onSuccess: () => {
      setKey(''); setRecovery(''); setOccupant(null); setShowTransfer(false)
      setError(null); invalidate()
    },
    onError: (e: unknown) =>
      setError(apiErrorDetail(e, 'Transfer failed. Check the recovery code.')),
  })

  const release = useMutation({
    mutationFn: () => api('/entitlements/license', { method: 'DELETE' }),
    onSuccess: () => { setError(null); invalidate() },
    onError: (e: unknown) => setError(apiErrorDetail(e, 'Could not release this license.')),
  })

  if (licensed) {
    return (
      <div className="flex flex-col gap-3">
        <p className="text-[13.5px] text-text-2">
          <span className="font-mono text-amber">{tier.toUpperCase()}</span>
          {', '}active on this installation.
        </p>
        <div className="flex flex-wrap gap-2">
          <Button variant="ghost" onClick={() => setShowHistory(h => !h)}>
            {showHistory ? 'Hide installations' : 'Installations'}
          </Button>
          <Button variant="danger" disabled={release.isPending}
                  onClick={() => release.mutate()}>
            {release.isPending ? 'Releasing…' : 'Release license'}
          </Button>
        </div>
        <p className="text-[12.5px] text-text-3">
          Releasing hands the license back so another installation can use it. Do this
          before rebuilding this server, and you will not need the recovery code.
        </p>
        {showHistory && (
          <div className="flex flex-col gap-1.5">
            {history.isPending && <p className="text-[13px] text-text-3">Loading…</p>}
            {history.data?.activations.map(a => (
              <div key={a.id} className="flex flex-wrap items-baseline gap-x-3 text-[13px]">
                <span className="font-mono text-text-2">{shortId(a.installation_id)}</span>
                <span className={a.current ? 'text-amber' : 'text-text-3'}>
                  {a.current ? 'this installation' : a.status}
                </span>
                <span className="text-text-3">last seen {ago(a.last_seen_at)}</span>
                {a.conflict_reason && (
                  <span className="text-red">conflict: {a.conflict_reason}</span>
                )}
              </div>
            ))}
          </div>
        )}
        {error && <p className="text-[13px] text-red">{error}</p>}
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-3">
      <p className="text-[13.5px] text-text-2">
        <span className="font-mono text-amber">{tier.toUpperCase()}</span>
        {', '}one Proxmox host. Enter a license key to activate this installation.
      </p>
      <div className="flex flex-col gap-2 sm:flex-row">
        <input
          aria-label="License key"
          className={inputCls}
          placeholder="PPL-XXXXX-XXXXX-XXXXX-XXXXX-XXXXX"
          value={key}
          onChange={e => { setKey(e.target.value); setOccupant(null) }}
        />
        <Button variant="primary" disabled={!key.trim() || activate.isPending}
                onClick={() => activate.mutate()}>
          {activate.isPending ? 'Activating…' : 'Activate'}
        </Button>
      </div>

      {occupant && (
        <div className="flex flex-col gap-2 rounded-lg border border-amber/30 bg-amber-dim p-3">
          <p className="text-[13.5px] text-text">
            This license is already active on another installation.
          </p>
          <div className="text-[13px] text-text-2">
            <div>Installation: <span className="font-mono">{shortId(occupant.installation_id)}</span></div>
            <div>Last seen: {ago(occupant.last_seen_at)}</div>
          </div>
          <p className="text-[12.5px] text-text-3">
            If that server is still running, release the license there instead. Force
            transfer is for a server you cannot get back.
          </p>
          <div className="flex gap-2">
            <Button variant="ghost" onClick={() => setOccupant(null)}>Cancel</Button>
            <Button variant="go" onClick={() => setShowTransfer(true)}>Force Transfer</Button>
          </div>
        </div>
      )}

      {/* One error line, never two: while the dialog is open it owns the
          message, and the card behind it would otherwise show the same text. */}
      {error && !showTransfer && <p className="text-[13px] text-red">{error}</p>}

      {showTransfer && (
        <Dialog
          title="Force transfer this license"
          description="The other installation will stop being licensed."
          onClose={() => setShowTransfer(false)}
        >
          <div className="flex flex-col gap-3">
            <p className="text-[13.5px] text-text-2">
              {occupant && (
                <>Installation <span className="font-mono">{shortId(occupant.installation_id)}</span>{' '}
                  was last seen {ago(occupant.last_seen_at)}. </>
              )}
              After transferring, it drops to the free tier the next time it checks in.
              Your remaining license time carries over.
            </p>
            <label className="flex flex-col gap-1.5 text-[13px] text-text-2">
              Recovery code
              <input
                className={inputCls}
                autoFocus
                value={recovery}
                onChange={e => setRecovery(e.target.value)}
                placeholder="From your purchase confirmation"
              />
            </label>
            <p className="text-[12.5px] text-text-3">
              The license key alone cannot move a license. The recovery code is what
              proves this is yours.
            </p>
            {error && <p className="text-[13px] text-red">{error}</p>}
            <div className="flex justify-end gap-2">
              <Button variant="ghost" onClick={() => setShowTransfer(false)}>Cancel</Button>
              <Button variant="go" disabled={!recovery.trim() || transfer.isPending}
                      onClick={() => transfer.mutate()}>
                {transfer.isPending ? 'Transferring…' : 'Transfer license here'}
              </Button>
            </div>
          </div>
        </Dialog>
      )}
    </div>
  )
}
