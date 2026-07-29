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

export function HostForm({ onCreated }: { onCreated: (h: HostCreated) => void }) {
  const [f, setF] = useState({ name: '', address: 'https://', token_id: '',
    token_secret: '', verify_tls: true, ssh_enroll: false })
  const [probe, setProbe] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const set = (k: string, v: unknown) => setF(s => ({ ...s, [k]: v }))
  const errText = (e: unknown) =>
    e instanceof ApiError ? String((e.body as any)?.detail ?? (e.body as any)?.title ?? e.message) : 'Request failed'

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
