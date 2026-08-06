import { useState } from 'react'
import { api, ApiError } from '../api/client'
import { Button } from './ui/button'
import { inputCls } from './LoginForm'

export type HostCreated = {
  id: number; name: string; ssh_public_key?: string
  authorized_keys_line?: string; consent_note?: string
}

const CONSENT_COPY = 'App Store installs run community scripts through a dedicated ' +
  'SSH key — a root shell on the node, exactly as if you ran them yourself. ' +
  'Optional: skip it and everything except installs/updates/migration still works.'

// Each kind names a different fix. "Request failed" named none of them.
const KIND_COPY: Record<string, string> = {
  auth: 'Proxmox rejected the API token. Check the token id and secret, and that the token has not expired.',
  unreachable: 'Could not reach that address. Check the host is up and that :8006 is reachable from Proxploy.',
  tls_fingerprint: "The node's TLS certificate does not match the fingerprint you pinned. "
    + 'If you did not just replace the certificate, stop and investigate before continuing.',
  refused: 'Proxploy refused to connect to that address because it resolves somewhere unsafe '
    + '(loopback, link-local, or metadata). Use the node\'s real address.',
}

const errText = (e: unknown) => {
  if (!(e instanceof ApiError)) return 'Request failed.'
  const body = e.body as { error?: string; detail?: string | { error?: string } } | null
  const kind = body?.error
  if (kind && KIND_COPY[kind]) return KIND_COPY[kind]
  if (e.status === 409) return 'A host with that name already exists.'
  if (e.status === 403) return 'Managing more than one host needs a paid tier.'
  return typeof body?.detail === 'string' ? body.detail : 'Request failed.'
}

export function HostForm({ onCreated }: { onCreated: (h: HostCreated) => void }) {
  const [f, setF] = useState({ name: '', address: 'https://', token_id: '',
    token_secret: '', verify_tls: true, ssh_enroll: false })
  const [probe, setProbe] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const set = (k: string, v: unknown) => setF(s => ({ ...s, [k]: v }))

  async function testConnection() {
    setProbe(''); setError('')
    try {
      const r = await api<{ version: string; release: string }>('/hosts/probe', {
        method: 'POST', body: JSON.stringify(f) })
      setProbe(`Connected — PVE ${r.version}`)
    } catch (e) { setError(errText(e)) }
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault(); setBusy(true); setError('')
    try {
      onCreated(await api<HostCreated>('/hosts', {
        method: 'POST',
        body: JSON.stringify({ ...f, ssh_consent: f.ssh_enroll }) }))
    } catch (e) { setError(errText(e)) } finally { setBusy(false) }
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      {([['name', 'Name', 'pve-01'], ['address', 'Address', 'https://10.0.0.5:8006'],
         ['token_id', 'API token id', 'proxploy@pve!monitoring'],
         ['token_secret', 'API token secret', '']] as const).map(([k, label, ph]) => (
        <div key={k}>
          <label htmlFor={k} className="mb-1 block text-[11px] uppercase tracking-wide text-text-3">{label}</label>
          <input id={k} required placeholder={ph} className={inputCls}
            type={k === 'token_secret' ? 'password' : 'text'}
            value={f[k]} onChange={e => set(k, e.target.value)} />
        </div>
      ))}
      <label className="flex items-center gap-2 text-[13px] text-text-2">
        <input type="checkbox" checked={f.verify_tls}
          onChange={e => set('verify_tls', e.target.checked)} /> Verify TLS certificate
      </label>
      <label className="flex items-start gap-2 text-[13px] text-text-2">
        <input type="checkbox" checked={f.ssh_enroll}
          onChange={e => set('ssh_enroll', e.target.checked)} className="mt-0.5" />
        <span>Enable App Store installs (SSH key enrolment).
          <span className="block text-[12px] text-text-3">
            I understand this authorizes a root shell on the node: {CONSENT_COPY}
          </span>
        </span>
      </label>
      {probe && <p className="font-mono text-[12px] text-green">{probe}</p>}
      {error && <p className="text-[12.5px] text-red">{error}</p>}
      <div className="flex gap-2">
        <Button type="button" variant="ghost" onClick={testConnection}>Test connection</Button>
        <Button type="submit" disabled={busy}>{busy ? 'Adding…' : 'Add host'}</Button>
      </div>
    </form>
  )
}
