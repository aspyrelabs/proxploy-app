import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api, ApiError } from '../api/client'
import { useHostCapabilityCatalog } from '../api/hosts'
import { Button } from './ui/button'
import { HostScriptPanel } from './HostScriptPanel'
import { PeerEnrolmentPanel } from './PeerEnrolmentPanel'
import { inputCls } from './LoginForm'
import { Loading } from './ui/loading'

export type HostCreated = {
  id: number; name: string; ssh_public_key?: string
  authorized_keys_line?: string; consent_note?: string
  // Both come from POST /hosts and are only used by the peer panel below.
  // Either can be null when the probe could not read /cluster/status.
  node_name?: string | null; cluster_name?: string | null
}

const CONSENT_COPY = 'App Store installs run community scripts through a dedicated ' +
  'SSH key, a root shell on the node, exactly as if you ran them yourself. ' +
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
  // KIND_COPY says what to DO about a kind. The server's `detail` says what
  // actually happened, and only it can: which privilege Proxmox refused, or
  // which fingerprint was pinned against which was presented. Both, in that
  // order: act on the first sentence, verify with the second.
  const detail = typeof body?.detail === 'string' ? body.detail : null
  if (kind && KIND_COPY[kind]) {
    return detail ? `${KIND_COPY[kind]} ${detail}` : KIND_COPY[kind]
  }
  // 409 and 403 keep their own wording with no detail appended: the server's
  // detail restates the same fact, and "already exists. host name already
  // exists" reads worse than either half.
  if (e.status === 409) return 'A host with that name already exists.'
  if (e.status === 403) return 'Managing more than one host needs a paid tier.'
  return detail ?? 'Request failed.'
}

// docs.proxploy.com is the shipping docs site. The staging mirror
// (docs.proxploy.dev) is deliberately NOT linked — a link that is right
// in dev and wrong for every customer is the worse failure.
const TOKEN_DOCS = 'https://docs.proxploy.com/getting-started/proxmox-token/'

// Monitoring is deliberately absent: it is mandatory and the generator
// emits it whether or not it is asked for, so offering it as a checkbox
// would be offering a choice that does not exist.
// 
// Labels and the "why" explanation normally come from
// useHostCapabilityCatalog. This hand-written copy is the fallback while
// that request is still loading or has failed: the form must work without
// it.
const CAPABILITY_FALLBACK: { key: string; label: string; why?: string }[] = [
  { key: 'lifecycle', label: 'Lifecycle' },
  { key: 'console', label: 'Console' },
  { key: 'backup', label: 'Backup' },
]

// Only the two fields that ask for something the operator must go and
// create somewhere else. Name and Address explain themselves.
const FIELD_HELP: Partial<Record<string, React.ReactNode>> = {
  token_id: <>
    Proxmox names a token <code className="text-text-2">user@realm!name</code>, for
    example <code className="text-text-2">proxploy@pve!monitoring</code>. Create one
    under Datacenter → Permissions → API Tokens, or with <code className="text-text-2">pveum</code>.
    Proxploy wants a privilege-separated token, never root.
  </>,
  token_secret: <>
    The UUID Proxmox shows <strong className="text-text-2">only once</strong>, at the
    moment the token is created. It cannot be retrieved afterwards: if you did not
    copy it, delete the token and create another.
  </>,
}

/** A disclosure, not a tooltip: this copy is several lines long, has to be
 *  reachable by keyboard, and has to survive on a touch screen, none of which
 *  a hover tooltip manages. */
function FieldInfo({ label, body }: { label: string; body: React.ReactNode }) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button type="button" onClick={() => setOpen(o => !o)} aria-expanded={open}
        aria-label={`What is the ${label}?`}
        className="grid size-[15px] shrink-0 cursor-pointer place-items-center rounded-full
                   border border-line text-[10px] leading-none text-text-3 transition
                   hover:border-amber hover:text-amber">
        i
      </button>
      {open && (
        <p className="order-last w-full basis-full text-[12px] leading-[1.55] text-text-3">
          {body}{' '}
          <a href={TOKEN_DOCS} target="_blank" rel="noopener noreferrer"
            className="text-amber underline underline-offset-2">How to create one</a>
        </p>
      )}
    </>
  )
}

export function HostForm({ onCreated }: { onCreated: (h: HostCreated) => void }) {
  const qc = useQueryClient()
  const [f, setF] = useState({ name: '', address: 'https://', token_id: '',
    // Off by default: a stock Proxmox node serves a self-signed certificate,
    // so verifying by default failed the first connection for almost every
    // operator. Fingerprint pinning (HostIn.tls_fingerprint) is implemented
    // in the backend but not yet collected here.
    token_secret: '', verify_tls: false, ssh_enroll: false })
  const [probe, setProbe] = useState('')
  const [missing, setMissing] = useState<string[] | null>(null)
  const [caps, setCaps] = useState<string[]>(['lifecycle', 'console', 'backup'])
  // Off by default: Sys.PowerMgmt can take the whole node down, so it is
  // never on unless the operator explicitly ticks it. Independent of `caps`
  // — Reboot/Power off is offered on every host regardless.
  const [nodePower, setNodePower] = useState(false)
  // One token per capability the operator ticked above. Keyed by capability
  // so the retry path can tell which one the node rejected.
  const [capTokens, setCapTokens] =
    useState<Record<string, { id: string; secret: string } | undefined>>({})
  // The host, once POST /hosts has succeeded. Non-null means a retry must NOT
  // create it again (409 host name already exists).
  const [created, setCreated] = useState<HostCreated | null>(null)
  // The host and its tokens are stored, so the peer panel takes over: it
  // asks whether this host has other cluster nodes. On a standalone host it
  // renders nothing and calls onCreated immediately.
  const [peerStage, setPeerStage] = useState(false)
  const [storedCaps, setStoredCaps] = useState<string[]>([])
  const [capErrors, setCapErrors] = useState<Record<string, string>>({})
  const setCapToken = (key: string, field: 'id' | 'secret', v: string) =>
    setCapTokens(s => ({ ...s, [key]: { id: '', secret: '', ...s[key], [field]: v } }))
  // Never gates the form: capCatalog.data is undefined both while loading
  // and after a failed request, and CAPABILITY_FALLBACK covers both the
  // same way, so the checkboxes and submit always work.
  const capCatalog = useHostCapabilityCatalog()
  const capChoices: { key: string; label: string; why?: string }[] =
    capCatalog.data ? capCatalog.data.filter(c => !c.required) : CAPABILITY_FALLBACK
  const labelOf = (key: string) =>
    capChoices.find(c => c.key === key)?.label ?? key
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [testing, setTesting] = useState(false)
  const set = (k: string, v: unknown) => setF(s => ({ ...s, [k]: v }))

  async function testConnection() {
    setProbe(''); setError(''); setMissing(null); setTesting(true)
    try {
      const r = await api<{ version: string; release: string
                            missing_privileges: string[] | null }>('/hosts/probe', {
        method: 'POST', body: JSON.stringify(f) })
      setProbe(`Connected, PVE ${r.version}`)
      // Connecting is not the same as being able to read anything. A privsep
      // token with no ACLs connects fine and then fails every monitoring read,
      // which used to surface minutes later as the host being "unreachable".
      setMissing(r.missing_privileges?.length ? r.missing_privileges : null)
    } catch (e) { setError(errText(e)) } finally { setTesting(false) }
  }


  async function submit(e: React.FormEvent) {
    e.preventDefault(); setBusy(true); setError('')
    try {
      // `created` non-null is the retry path: the host already exists and
      // works for the capabilities that verified, so re-creating it would
      // 409 and rolling it back would throw away a working enrolment.
      let h = created
      if (!h) {
        h = await api<HostCreated>('/hosts', {
          method: 'POST',
          body: JSON.stringify({ ...f, ssh_consent: f.ssh_enroll }) })
        // Invalidate as soon as the host exists on the server, not only in
        // onCreated: if the operator abandons this panel after a rejected token
        // instead of clicking Retry or Continue, the host must still show up in
        // the list.
        qc.invalidateQueries({ queryKey: ['hosts'] })
      }
      setCreated(h)
      // Each token is verified against the node individually by
      // POST /hosts/{id}/credentials, so one rejection is one capability's
      // failure, not the enrolment's.
      const done = [...storedCaps]
      const failed: Record<string, string> = {}
      for (const key of caps) {
        const t = capTokens[key]
        if (done.includes(key) || !t?.id || !t?.secret) continue
        try {
          await api(`/hosts/${h.id}/credentials`, {
            method: 'POST',
            body: JSON.stringify({ token_id: t.id, token_secret: t.secret,
                                  capability: key }) })
          done.push(key)
        } catch (err) { failed[key] = `${labelOf(key)}: ${errText(err)}` }
      }
      setStoredCaps(done); setCapErrors(failed)
      if (!Object.keys(failed).length) setPeerStage(true)
    } catch (e) { setError(errText(e)) } finally { setBusy(false) }
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      {([['name', 'Name', 'pve-01'], ['address', 'Address', 'https://10.0.0.5:8006']] as const)
        .map(([k, label, ph]) => (
        <div key={k}>
          <div className="mb-1 flex flex-wrap items-center gap-x-1.5 gap-y-1">
            <label htmlFor={k} className="block text-[11px] uppercase tracking-wide text-text-3">{label}</label>
          </div>
          <input id={k} required placeholder={ph} className={inputCls}
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
      {/* One box for all four capability tokens. Monitoring is mandatory and
              creates the host, so its row always renders; the other three are
              optional and only appear once ticked. */}
      <div className="rounded-ctl border border-line bg-panel-2 p-3">
        <HostScriptPanel capabilities={caps} nodeShell={f.ssh_enroll} nodePower={nodePower} />
        {/* Monitoring is mandatory, the rest are the operator's call. Anything
                  left unticked gets no role and no token at all. Unticking one
                  shows what it would have covered, right under it. */}
        <div className="mt-2 space-y-1.5">
          <p className="text-[11.5px] text-text-3">Read-only monitoring is always included.</p>
          {capChoices.map(({ key, label, why }) => {
            const ticked = caps.includes(key)
            return (
              <label key={key} className="flex items-start gap-1.5 text-[11.5px] text-text-2">
                <input type="checkbox" className="mt-0.5" checked={ticked}
                  onChange={e => setCaps(cs => e.target.checked
                    ? [...cs, key] : cs.filter(c => c !== key))} />
                <span>
                  {label}
                  {/* `why` only exists once the catalog has loaded; while it
                      is still the fallback there is nothing to show, which
                      is why this is a plain checkbox with no text below it
                      in that state. */}
                  {!ticked && why && (
                    <span className="block text-[11px] text-text-3">
                      Without a token for {label}, this will not work: {why}
                    </span>
                  )}
                </span>
              </label>
            )
          })}
        </div>
        {/* Monitoring's row always renders below, it is mandatory and creates
                  the host. Optional capabilities only show when ticked: an
                  unticked capability got no role and no token from the script.
                  All four are visible once the host exists. */}
        <div className="mt-3 space-y-3 border-t border-line-soft pt-3">
          {/* flex-wrap is load-bearing: FieldInfo's explanation is basis-full so
              it drops onto its own line under the label. Without wrapping it
              squeezes alongside and the label collapses into a column. */}
          <div className="grid gap-2 sm:grid-cols-2">
            <div>
              <div className="mb-1 flex flex-wrap items-center gap-x-1.5 gap-y-1">
                <label htmlFor="token_id" className="block text-[11px] uppercase tracking-wide text-text-3">
                  Monitoring token id
                </label>
                {FIELD_HELP.token_id && <FieldInfo label="Monitoring token id" body={FIELD_HELP.token_id} />}
              </div>
              <input id="token_id" required placeholder="proxploy@pve!monitoring" className={inputCls}
                value={f.token_id} onChange={e => set('token_id', e.target.value)} />
            </div>
            <div>
              <div className="mb-1 flex flex-wrap items-center gap-x-1.5 gap-y-1">
                <label htmlFor="token_secret" className="block text-[11px] uppercase tracking-wide text-text-3">
                  Monitoring token secret
                </label>
                {FIELD_HELP.token_secret && <FieldInfo label="Monitoring token secret" body={FIELD_HELP.token_secret} />}
              </div>
              <input id="token_secret" required type="password" className={inputCls}
                value={f.token_secret} onChange={e => set('token_secret', e.target.value)} />
            </div>
          </div>
          {caps.length > 0 && (
            <>
            <p className="text-[11.5px] text-text-3">
              The script prints one token per capability. Paste them here, or
              leave a pair blank and add it later from the host's Edit dialog.
            </p>
            {capChoices.filter(c => caps.includes(c.key)).map(({ key, label }) => (
              <div key={key} className="grid gap-2 sm:grid-cols-2">
                <div>
                  <label htmlFor={`cap-${key}-id`}
                    className="mb-1 block text-[11px] uppercase tracking-wide text-text-3">
                    {label} token id
                  </label>
                  <input id={`cap-${key}-id`} className={inputCls}
                    placeholder={`proxploy@pve!${key}`}
                    disabled={storedCaps.includes(key)}
                    value={capTokens[key]?.id ?? ''}
                    onChange={e => setCapToken(key, 'id', e.target.value)} />
                </div>
                <div>
                  <label htmlFor={`cap-${key}-secret`}
                    className="mb-1 block text-[11px] uppercase tracking-wide text-text-3">
                    {label} token secret
                  </label>
                  <input id={`cap-${key}-secret`} type="password" className={inputCls}
                    disabled={storedCaps.includes(key)}
                    value={capTokens[key]?.secret ?? ''}
                    onChange={e => setCapToken(key, 'secret', e.target.value)} />
                </div>
                {storedCaps.includes(key) && (
                  <p className="text-[11.5px] text-green sm:col-span-2">{label} token stored.</p>
                )}
                {capErrors[key] && (
                  <p className="text-[12px] text-red sm:col-span-2">{capErrors[key]}</p>
                )}
              </div>
            ))}
            </>
          )}
        </div>
        {/* Independent of the capability row above: Sys.PowerMgmt gets its own
                  role and token, not a widening of Lifecycle's, and Reboot/Power
                  off is offered on every host regardless of which capabilities
                  were chosen. */}
        <label className="mt-1.5 flex items-start gap-1.5 text-[11.5px] text-text-2">
          <input type="checkbox" checked={nodePower} className="mt-0.5"
            onChange={e => setNodePower(e.target.checked)} />
          <span>Node power (reboot/power off this host).
            <span className="block text-[11px] text-text-3">
              Can take down every guest it runs, and Proxploy itself if it runs here.
            </span>
          </span>
        </label>
      </div>

      {probe && (
        <p className={`font-mono text-[12px] ${missing ? 'text-text-2' : 'text-green'}`}>{probe}</p>
      )}
      {missing && (
        <div className="rounded-ctl border border-amber/30 bg-amber-dim p-3">
          <p className="text-[12.5px] text-amber">
            Connected, but this token cannot read everything Proxploy needs.
          </p>
          <p className="mt-1 font-mono text-[11.5px] text-text-2">missing: {missing.join(', ')}</p>
          <p className="mt-1.5 text-[11.5px] text-text-3">
            Monitoring will report the host as unreachable until these are granted.{' '}
            <a href={TOKEN_DOCS} target="_blank" rel="noopener noreferrer"
              className="text-amber underline underline-offset-2">How to grant them</a>
          </p>
        </div>
      )}
      {error && <p className="text-[12.5px] text-red">{error}</p>}
      {created && Object.keys(capErrors).length > 0 && (
        <div className="rounded-ctl border border-amber/30 bg-amber-dim p-3">
          <p className="text-[12.5px] text-amber">
            {created.name} was added and is working. Proxmox rejected the token for{' '}
            {Object.keys(capErrors).map(labelOf).join(', ')}, so that capability is
            not configured yet. Everything else was stored.
          </p>
          <p className="mt-1.5 text-[11.5px] text-text-3">
            Correct the token above and retry just that one, or continue and add it
            later from the host's Edit dialog.
          </p>
          <div className="mt-2 flex gap-2">
            <Button type="button" variant="ghost"
              onClick={() => onCreated(created)}>Continue without it</Button>
          </div>
        </div>
      )}
      {/* The host exists and its tokens are stored by now, so the form's own
              controls are done: the panel owns the rest of the flow. It renders
              nothing for a standalone host, so that case ends here. */}
      {peerStage && created ? (
        <PeerEnrolmentPanel hostId={created.id} node={created.node_name ?? created.name}
          cluster={created.cluster_name} onDone={() => onCreated(created)} />
      ) : (
        <div className="flex items-center gap-2">
          {/* Neither call has a progress signal: connecting either succeeds or
              it doesn't, and adding the host is one POST. Ring, not a number. */}
          {(testing || busy) && (
            <Loading label={testing ? 'Testing the connection' : 'Adding the host'} size={18} />
          )}
          <Button type="button" variant="ghost" onClick={testConnection} disabled={testing}>
            Test connection
          </Button>
          <Button type="submit" disabled={busy}>
            {busy ? (created ? 'Retrying…' : 'Adding…')
                  : (created ? 'Retry rejected token' : 'Add host')}
          </Button>
        </div>
      )}
    </form>
  )
}
