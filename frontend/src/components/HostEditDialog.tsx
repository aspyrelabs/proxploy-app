import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api, apiErrorDetail } from '../api/client'
import { notify } from '../lib/notify'
import { inputCls } from './LoginForm'
import { Button } from './ui/button'
import { Dialog } from './ui/dialog'
import { HostCapabilityList } from './HostCapabilityList'

export type HostSummary = { name: string; address: string }

type TestResult = { status: string; pve_version: string | null }

/**
 * The host actions menu's Edit: name, address, and the API token id/secret,
 * in one popup card (`Dialog`, which already brings Escape/focus-trap/focus-
 * restore -- see components/ui/dialog.tsx).
 *
 * Two backend calls, composed rather than merged into one:
 *  - PATCH /hosts/{id} for name/address (proxploy/api/hosts.py `patch_host`,
 *    extended for this: it used to only take node_shell_enabled/team_id).
 *  - POST /hosts/{id}/credentials for the token id/secret -- the SAME route
 *    HostRotateDialog already drives, reused rather than duplicated. It
 *    verifies a new token against the host's address before it replaces the
 *    old one, which is exactly why the PATCH runs FIRST: a changed address
 *    plus a changed token must verify the token against the NEW address, not
 *    the one being replaced.
 *
 * Changing the address or credentials can break a live connection, so
 * "Test connection" (POST /hosts/{id}/test, already built for the host page)
 * is offered both standing alone -- check the CURRENT connection before
 * touching anything -- and automatically after a successful Save, so a
 * broken result is seen here rather than discovered later as a silently
 * unreachable host.
 */
export function HostEditDialog({ hostId, host, onClose }: {
  hostId: number
  host: HostSummary
  onClose: () => void
}) {
  const qc = useQueryClient()
  const [name, setName] = useState(host.name)
  const [address, setAddress] = useState(host.address)
  const [tokenId, setTokenId] = useState('')
  const [tokenSecret, setTokenSecret] = useState('')
  const [error, setError] = useState('')
  const [testResult, setTestResult] = useState<TestResult | null>(null)
  const [testing, setTesting] = useState(false)
  const [saving, setSaving] = useState(false)

  const nameChanged = name.trim() !== host.name
  const addressChanged = address.trim() !== host.address
  const halfFilled = Boolean(tokenId) !== Boolean(tokenSecret)
  const nothingToSave = !nameChanged && !addressChanged && !tokenId && !tokenSecret

  function invalidate() {
    qc.invalidateQueries({ queryKey: ['hosts'] })
    qc.invalidateQueries({ queryKey: ['cluster', 'nodes'] })
  }

  async function testConnection() {
    setError(''); setTesting(true)
    try {
      const r = await api<TestResult>(`/hosts/${hostId}/test`, { method: 'POST' })
      setTestResult(r)
      if (r.status !== 'connected') {
        setError(`Could not connect: the host reports "${r.status}". `
                + 'Check the address and credentials.')
      }
    } catch (e) { setError(apiErrorDetail(e, 'Request failed, try again.')) } finally { setTesting(false) }
  }

  async function save() {
    setError(''); setSaving(true); setTestResult(null)
    try {
      if (nameChanged || addressChanged) {
        const patch: Record<string, string> = {}
        if (nameChanged) patch.name = name.trim()
        if (addressChanged) patch.address = address.trim()
        await api(`/hosts/${hostId}`, { method: 'PATCH', body: JSON.stringify(patch) })
      }
      if (tokenId && tokenSecret) {
        await api(`/hosts/${hostId}/credentials`, {
          method: 'POST',
          body: JSON.stringify({ token_id: tokenId, token_secret: tokenSecret, rotate_ssh: false }),
        })
      }
      invalidate()
      notify.success(`${name.trim() || host.name} saved.`)
      // Verify what is now actually stored, not what used to be here.
      const r = await api<TestResult>(`/hosts/${hostId}/test`, { method: 'POST' })
      setTestResult(r)
      if (r.status === 'connected') {
        onClose()
      } else {
        setError(`Saved, but Proxploy could not connect: the host reports `
                + `"${r.status}". Check the address and credentials.`)
      }
    } catch (e) {
      setError(apiErrorDetail(e, 'Request failed, try again.'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog title={<>Edit {host.name}</>} width={440} scrollBody onClose={onClose}>
      <div className="mt-4 space-y-3">
        <div>
          <label htmlFor="edit-host-name"
            className="mb-1 block text-[11px] uppercase tracking-wide text-text-3">
            Name
          </label>
          <input id="edit-host-name" className={inputCls} value={name}
            onChange={(e) => setName(e.target.value)} />
        </div>
        <div>
          <label htmlFor="edit-host-address"
            className="mb-1 block text-[11px] uppercase tracking-wide text-text-3">
            Address
          </label>
          <input id="edit-host-address" className={inputCls} value={address}
            onChange={(e) => setAddress(e.target.value)} />
        </div>
        <div>
          <label htmlFor="edit-token-id"
            className="mb-1 block text-[11px] uppercase tracking-wide text-text-3">
            New monitoring token id
          </label>
          <input id="edit-token-id" className={inputCls} value={tokenId}
            onChange={(e) => setTokenId(e.target.value)}
            placeholder="leave blank to keep the current one" />
        </div>
        <div>
          <label htmlFor="edit-token-secret"
            className="mb-1 block text-[11px] uppercase tracking-wide text-text-3">
            New monitoring token secret
          </label>
          <input id="edit-token-secret" type="password" className={inputCls} value={tokenSecret}
            onChange={(e) => setTokenSecret(e.target.value)} />
        </div>
        {/* HostCapabilityList below renders all FOUR capabilities, monitoring
            included -- it is not "the other three". The fields above are a
            second, independent way to rotate monitoring specifically: they
            run through save(), which does the PATCH (name/address) before the
            credentials POST, so a changed address and a changed token verify
            together against the NEW address. HostCapabilityList's per-row
            POST has no such ordering, which is why monitoring's own row below
            stays rotate-only rather than replacing these fields. */}
        <div className="border-t border-line-soft pt-3">
          <HostCapabilityList hostId={hostId} />
        </div>
        {halfFilled && (
          <p className="text-[12px] text-red">
            Token id and secret must both be filled in, or both left blank.
          </p>
        )}
        {testResult && testResult.status === 'connected' && (
          <p className="font-mono text-[12px] text-green">
            Connected, PVE {testResult.pve_version ?? '?'}
          </p>
        )}
        {error && <p className="text-[12.5px] text-red">{error}</p>}
        <div className="flex items-center justify-between gap-2">
          <Button type="button" variant="ghost" onClick={testConnection}
            disabled={testing || saving}>
            {testing ? 'Testing…' : 'Test connection'}
          </Button>
          <div className="flex gap-2">
            <Button variant="ghost" onClick={onClose}>Cancel</Button>
            <Button disabled={nothingToSave || halfFilled || saving} onClick={save}>
              {saving ? 'Saving…' : 'Save'}
            </Button>
          </div>
        </div>
      </div>
    </Dialog>
  )
}
