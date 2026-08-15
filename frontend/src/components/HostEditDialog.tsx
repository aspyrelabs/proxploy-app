import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api, apiErrorDetail } from '../api/client'
import { notify } from '../lib/notify'
import { inputCls } from './LoginForm'
import { Button } from './ui/button'
import { Dialog } from './ui/dialog'
import { HostCapabilityList } from './HostCapabilityList'
import { HostScriptPanel } from './HostScriptPanel'

export type HostSummary = { name: string; address: string }

type TestResult = { status: string; pve_version: string | null }
type HostCapabilities = { capabilities?: Record<string, boolean> }
type SshRotateResult = { public_key?: string; consent_note?: string }

/**
 * The single Edit dialog for a host: name, address, capability tokens, the
 * setup script, and SSH key regeneration, in one popup card (`Dialog`, which
 * already brings Escape/focus-trap/focus-restore -- see
 * components/ui/dialog.tsx). Save runs PATCH /hosts/{id} for name/address
 * (proxploy/api/hosts.py `patch_host`, extended for this: it used to only
 * take node_shell_enabled/team_id). Opened from both the node detail page's
 * actions menu (HostActionsMenu) and the Settings hosts row, so there is one
 * Edit dialog rather than one per entry point.
 *
 * Token management for every capability, including monitoring, lives below
 * in `HostCapabilityList`, not here. The "Generate setup script" panel used
 * to live in the now-deleted HostTokensDialog (Settings only); it is here so
 * that affordance is not lost now that Settings opens this dialog instead.
 * SSH key regeneration used to live in the now-deleted HostRotateDialog; it
 * is the only place in the frontend that can do it, so it moved here too
 * rather than being dropped. Its token id/secret fields did not come across:
 * that is capability token rotation, and HostCapabilityList's monitoring row
 * already does it, duplicating it there was a real bug.
 *
 * Changing the address can break a live connection, so "Test connection"
 * (POST /hosts/{id}/test, already built for the host page) is offered both
 * standing alone -- check the CURRENT connection before touching anything --
 * and automatically after a successful Save, so a broken result is seen here
 * rather than discovered later as a silently unreachable host.
 */
export function HostEditDialog({ hostId, host, onClose }: {
  hostId: number
  host: HostSummary
  onClose: () => void
}) {
  const qc = useQueryClient()
  const [name, setName] = useState(host.name)
  const [address, setAddress] = useState(host.address)
  const [error, setError] = useState('')
  const [testResult, setTestResult] = useState<TestResult | null>(null)
  const [testing, setTesting] = useState(false)
  const [saving, setSaving] = useState(false)
  const [rotateSsh, setRotateSsh] = useState(false)
  const [rotatingSsh, setRotatingSsh] = useState(false)
  const [sshResult, setSshResult] = useState<SshRotateResult | null>(null)

  // Same key and fetch as HostCapabilityList uses below, so this shares its
  // cache entry instead of doubling the request. It exists here only to pick
  // a sensible default for the script generator: an operator who opens this
  // dialog is missing a token, not looking for a copy of the add-host form.
  const capsQuery = useQuery({
    queryKey: ['hosts', hostId],
    queryFn: () => api<HostCapabilities>(`/hosts/${hostId}`),
  })
  // monitoring is mandatory and the script always prints it regardless of
  // what is asked for, so it is never one of the capabilities requested here
  // (same as HostForm). If nothing is missing, ask for all of them anyway:
  // a stored token can still need replacing, and an empty request would make
  // Generate look broken instead of just less useful.
  const known = Object.keys(capsQuery.data?.capabilities ?? {}).filter(k => k !== 'monitoring')
  const missing = known.filter(k => !capsQuery.data?.capabilities?.[k])
  const defaultCapabilities = missing.length ? missing : known

  const nameChanged = name.trim() !== host.name
  const addressChanged = address.trim() !== host.address
  const nothingToSave = !nameChanged && !addressChanged

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

  async function regenerateSshKey() {
    setError(''); setRotatingSsh(true)
    try {
      const r = await api<SshRotateResult>(`/hosts/${hostId}/credentials`, {
        method: 'POST', body: JSON.stringify({ rotate_ssh: true }),
      })
      setSshResult(r)
      setRotateSsh(false)
      notify.success('SSH key regenerated.')
    } catch (e) {
      setError(apiErrorDetail(e, 'Request failed, try again.'))
    } finally {
      setRotatingSsh(false)
    }
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
        <div className="border-t border-line-soft pt-3">
          <HostCapabilityList hostId={hostId} />
        </div>
        <div className="rounded-ctl border border-line bg-panel-2 p-3">
          <HostScriptPanel capabilities={defaultCapabilities} nodeShell={false} nodePower={false} />
        </div>
        {/* SSH key regeneration, the one thing the deleted HostRotateDialog
            did that HostCapabilityList cannot: it has no SSH handling at
            all. Kept small and below the main form -- this is an occasional
            maintenance action, not a primary field. */}
        <div className="border-t border-line-soft pt-3">
          <label className="flex items-center gap-2 text-[13px] text-text-2">
            <input type="checkbox" checked={rotateSsh}
              onChange={(e) => setRotateSsh(e.target.checked)} />
            Regenerate SSH key (the new key still needs installing on the node)
          </label>
          {rotateSsh && (
            <div className="mt-2">
              <Button type="button" variant="ghost" size="sm" disabled={rotatingSsh}
                onClick={regenerateSshKey}>
                {rotatingSsh ? 'Regenerating…' : 'Regenerate'}
              </Button>
            </div>
          )}
          {sshResult?.public_key && (
            <div className="mt-2 space-y-1">
              <p className="text-[12.5px] text-text-2">{sshResult.consent_note}</p>
              <code className="block max-h-24 overflow-auto rounded-ctl border border-line
                               bg-panel-2 p-2 font-mono text-[11px] text-text">
                {sshResult.public_key}
              </code>
            </div>
          )}
        </div>
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
            <Button disabled={nothingToSave || saving} onClick={save}>
              {saving ? 'Saving…' : 'Save'}
            </Button>
          </div>
        </div>
      </div>
    </Dialog>
  )
}
