import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { api, ApiError } from '../api/client'
import { useEntitlements } from '../api/hooks'
import { useApiKeys } from '../api/apikeys'
import type { ApiKeyCreated, ApiKeyRow } from '../api/apikeys'
import { QueryState } from './QueryState'
import { Button } from './ui/button'

// Mirrors backend/proxploy/services/authz.py::PERMISSIONS' resource column.
// A key's scope can only narrow its owner's role, never widen it (doc 04) --
// "read" plus one "<resource>:write" per matrix resource is the full set of
// strings apikeys.py::_validate_scopes accepts.
const SCOPE_RESOURCES = [
  'host', 'app', 'vm', 'storage', 'network', 'backup', 'catalog', 'job',
  'schedule', 'alert', 'channel', 'metric', 'audit', 'settings', 'user',
  'team', 'entitlement', 'meta',
] as const
const SCOPE_OPTIONS = ['read', ...SCOPE_RESOURCES.map((r) => `${r}:write`)]

const detailOf = (e: unknown) =>
  e instanceof ApiError && typeof (e.body as any)?.detail === 'string'
    ? (e.body as any).detail : 'Request failed, try again.'

export function ApiKeysCard() {
  const ent = useEntitlements()
  // Same wait-for-first-fetch pattern as TeamsCard/SchedulesCard: fetching
  // before api.tokens resolves true would 403 every plan during the initial
  // load, not just plans that lack it.
  const apiTokensAllowed = ent.data != null && ent.has('api.tokens')
  const qc = useQueryClient()
  const keys = useApiKeys(apiTokensAllowed)

  const [adding, setAdding] = useState(false)
  const [name, setName] = useState('')
  const [scopes, setScopes] = useState<Set<string>>(new Set())
  const [expiresAt, setExpiresAt] = useState('')
  // The raw key from the most recent creation, held ONLY in this component's
  // state -- never written to localStorage/sessionStorage, never refetched
  // (the backend never returns it again either). Dismiss or navigate away
  // and it is gone for good.
  const [justCreated, setJustCreated] = useState<ApiKeyCreated | null>(null)

  const toggleScope = (s: string) =>
    setScopes((prev) => {
      const next = new Set(prev)
      if (next.has(s)) next.delete(s); else next.add(s)
      return next
    })

  const createKey = useMutation({
    mutationFn: () => api<ApiKeyCreated>('/api-keys', {
      method: 'POST',
      body: JSON.stringify({
        name,
        scopes: [...scopes],
        ...(expiresAt ? { expires_at: expiresAt } : {}),
      }),
    }),
    onSuccess: (created) => {
      setJustCreated(created)
      setName(''); setScopes(new Set()); setExpiresAt(''); setAdding(false)
      qc.invalidateQueries({ queryKey: ['api-keys'] })
    },
    onError: (e) => toast.error(detailOf(e)),
  })

  const revokeKey = useMutation({
    mutationFn: (id: number) => api(`/api-keys/${id}`, { method: 'DELETE' }),
    onError: (e) => toast.error(detailOf(e)),
    onSettled: () => qc.invalidateQueries({ queryKey: ['api-keys'] }),
  })

  const revoke = (k: ApiKeyRow) => {
    if (window.confirm(`Revoke API key "${k.name}"? Anything using it stops working immediately.`)) {
      revokeKey.mutate(k.id)
    }
  }

  return (
    <section className="rounded-card border border-line-soft bg-panel p-5">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="font-display text-[15px] font-semibold">API keys</h2>
        {apiTokensAllowed && (
          <Button variant="ghost" onClick={() => setAdding((a) => !a)}>
            {adding ? 'Close' : 'New key'}
          </Button>
        )}
      </div>
      {!apiTokensAllowed ? (
        <p className="text-[12.5px] text-text-3">
          {ent.data == null ? 'Loading…' : 'Not included in your plan.'}
        </p>
      ) : (
        <>
          {justCreated && (
            <div className="mb-4 rounded-ctl border border-amber/40 bg-amber-dim p-3">
              <p className="text-[12.5px] font-semibold text-amber">
                Copy this key now; it will never be shown again.
              </p>
              <p className="mt-1 text-[11.5px] text-text-3">
                Proxploy stores only a hash of it, not the key itself. If you lose it, revoke
                "{justCreated.name}" below and create a new one; there is no way to recover this one.
              </p>
              <div className="mt-2 flex items-center gap-2">
                <code className="min-w-0 flex-1 truncate rounded-ctl border border-line
                                 bg-panel-2 px-2 py-1.5 font-mono text-[12px] text-text">
                  {justCreated.key}
                </code>
                <Button variant="ghost" className="px-2 py-1 text-[11px]"
                  onClick={() => { void navigator.clipboard?.writeText(justCreated.key) }}>
                  Copy
                </Button>
                <Button variant="ghost" className="px-2 py-1 text-[11px]"
                  onClick={() => setJustCreated(null)}>
                  Dismiss
                </Button>
              </div>
            </div>
          )}

          <QueryState query={keys}
                      emptyTitle="No API keys yet."
                      emptyNote=""
                      errorTitle="API keys not readable"
                      errorNote="Proxploy could not reach the backend to list your API keys.">
            {(rows) => (
              <table className="w-full text-left text-[13px]">
                <thead><tr className="text-[10.5px] uppercase tracking-wide text-text-3">
                  <th className="pb-2">Name</th><th>Key</th><th>Scopes</th>
                  <th>Last used</th><th>State</th><th /></tr></thead>
                <tbody>
                  {rows.map((k) => (
                    <tr key={k.id} className="border-t border-line-soft hover:bg-panel-2">
                      <td className="py-2">{k.name}</td>
                      <td className="font-mono text-text-2">{k.prefix}…</td>
                      <td className="font-mono text-[11.5px] text-text-3">
                        {k.scopes.length ? k.scopes.join(', ') : 'full rights of your role'}
                      </td>
                      <td className="text-text-3">
                        {k.last_used_at ? new Date(k.last_used_at).toLocaleString() : 'never'}
                      </td>
                      <td className={k.revoked_at ? 'text-text-3' : 'text-green'}>
                        {k.revoked_at ? 'revoked' : 'active'}
                      </td>
                      <td className="py-2 text-right">
                        {!k.revoked_at && (
                          <Button variant="danger" className="px-2 py-1 text-[11px]"
                            disabled={revokeKey.isPending} onClick={() => revoke(k)}>
                            Revoke
                          </Button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </QueryState>

          {adding && (
            <div className="mt-4 border-t border-line-soft pt-4">
              <div className="flex flex-wrap items-end gap-3">
                <div>
                  <label htmlFor="apikey-name"
                    className="mb-1 block text-[10.5px] uppercase tracking-wide text-text-3">
                    Name
                  </label>
                  <input id="apikey-name"
                    className="w-full rounded-ctl border border-line bg-panel-2 px-3 py-1.5 text-[13px] text-text"
                    value={name} onChange={(e) => setName(e.target.value)} placeholder="CI runner" />
                </div>
                <div>
                  <label htmlFor="apikey-expiry"
                    className="mb-1 block text-[10.5px] uppercase tracking-wide text-text-3">
                    Expires (optional)
                  </label>
                  <input id="apikey-expiry" type="date" value={expiresAt}
                    onChange={(e) => setExpiresAt(e.target.value)}
                    className="rounded-ctl border border-line bg-panel-2 px-3 py-1.5 text-[13px] text-text" />
                </div>
                <Button disabled={!name || createKey.isPending} onClick={() => createKey.mutate()}>
                  Create key
                </Button>
              </div>
              <fieldset className="mt-3">
                <legend className="mb-1 block text-[10.5px] uppercase tracking-wide text-text-3">
                  Scopes (empty = full rights of your role, a key can only narrow that, never widen it)
                </legend>
                <div className="flex flex-wrap gap-x-3 gap-y-1">
                  {SCOPE_OPTIONS.map((s) => (
                    <label key={s} className="inline-flex items-center gap-1 text-[12px] text-text-2">
                      <input type="checkbox" checked={scopes.has(s)} onChange={() => toggleScope(s)} />
                      {s}
                    </label>
                  ))}
                </div>
              </fieldset>
            </div>
          )}

          <p className="mt-4 text-[11.5px] text-text-3">
            Keys drive the{' '}
            <a href="/api/docs" target="_blank" rel="noreferrer" className="text-amber hover:underline">
              full REST API
            </a>
            {' '}, everything this UI does.
          </p>
        </>
      )}
    </section>
  )
}
