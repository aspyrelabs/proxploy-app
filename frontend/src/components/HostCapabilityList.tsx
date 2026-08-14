import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, ApiError } from '../api/client'
import { inputCls } from './LoginForm'
import { Button } from './ui/button'
import { QueryState } from './QueryState'

/**
 * Every capability the backend knows about, with its state: stored (rotate)
 * or missing (paste it in). Shown in full rather than only the gaps, because
 * a capability with no token fails at the moment the operator tries to use
 * the feature, far from any explanation.
 *
 * Fetches GET /hosts/{id} itself on the ['hosts', id] key rather than taking
 * the state through props, so no call site has to thread it down. The rows
 * come from the response's own `capabilities` map, which the backend keys off
 * services/pveum.py::CAPABILITIES -- there is deliberately no capability list
 * in this file to drift from it.
 */
type HostCapabilities = { capabilities?: Record<string, boolean> }

// Title-case beats a label table, which would be exactly the second list the
// spec forbids. Ceiling: this only capitalizes the first character, so a
// future multi-word key (e.g. "node_power") would render as "Node_power".
// Fine for the four keys that exist today; revisit if one lands.
const labelOf = (key: string) => key.charAt(0).toUpperCase() + key.slice(1)

const detailOf = (e: unknown) =>
  e instanceof ApiError && typeof (e.body as { detail?: unknown })?.detail === 'string'
    ? (e.body as { detail: string }).detail
    : 'Request failed, try again.'

function CapabilityRow({ hostId, name, stored }: {
  hostId: number; name: string; stored: boolean
}) {
  const qc = useQueryClient()
  const label = labelOf(name)
  // A missing capability opens straight into its field: the gap IS the
  // prompt. A stored one stays behind Rotate so replacing a working token is
  // never one stray keystroke away.
  const [open, setOpen] = useState(!stored)
  const [tokenId, setTokenId] = useState('')
  const [tokenSecret, setTokenSecret] = useState('')
  const [error, setError] = useState('')
  const halfFilled = Boolean(tokenId) !== Boolean(tokenSecret)
  // Ids are prefixed with hostId: routes/settings.tsx can render the add-host
  // form (Task 2, unprefixed `cap-${key}-id`) alongside this per-host dialog
  // at the same time, and duplicate DOM ids silently break label/input
  // association.
  const idFieldId = `cap-${hostId}-${name}-id`
  const secretFieldId = `cap-${hostId}-${name}-secret`

  const save = useMutation({
    mutationFn: () => api(`/hosts/${hostId}/credentials`, {
      method: 'POST',
      body: JSON.stringify({ token_id: tokenId, token_secret: tokenSecret,
                            capability: name }) }),
    onSuccess: () => {
      setTokenId(''); setTokenSecret(''); setError(''); setOpen(false)
      // Patch this host's own query in place -- we already know the result,
      // no need to round-trip a GET for it. The hosts table's separate
      // ['hosts'] query is invalidated (exact, not a prefix match) so it
      // refetches next time it's active without also re-fetching this same
      // detail query out from under the row we just closed.
      qc.setQueryData<HostCapabilities>(['hosts', hostId], (old) =>
        old ? { ...old, capabilities: { ...old.capabilities, [name]: true } } : old)
      qc.invalidateQueries({ queryKey: ['hosts'], exact: true })
    },
    // The route names the address and says the old credential is still in
    // place; naming the capability is what turns it from a bare 502 into
    // something the operator can act on.
    onError: (e) => setError(`${label}: ${detailOf(e)}`),
  })

  return (
    <div className="border-t border-line-soft py-2 first:border-t-0">
      <div className="flex items-center justify-between gap-3">
        <span className="text-[13px] text-text">{label}</span>
        <div className="flex items-center gap-2">
          <span className={`text-[11.5px] ${stored ? 'text-green' : 'text-text-3'}`}>
            {stored ? 'stored' : 'not configured'}
          </span>
          {stored && !open && (
            <Button type="button" variant="ghost" className="px-2 py-1 text-[11px]"
              aria-label={`Rotate ${label} token`}
              onClick={() => setOpen(true)}>Rotate</Button>
          )}
        </div>
      </div>
      {open && (
        <div className="mt-2 space-y-2">
          <div>
            <label htmlFor={idFieldId}
              className="mb-1 block text-[11px] uppercase tracking-wide text-text-3">
              {label} token id
            </label>
            <input id={idFieldId} className={inputCls} value={tokenId}
              placeholder={`proxploy@pve!${name}`}
              onChange={(e) => setTokenId(e.target.value)} />
          </div>
          <div>
            <label htmlFor={secretFieldId}
              className="mb-1 block text-[11px] uppercase tracking-wide text-text-3">
              {label} token secret
            </label>
            <input id={secretFieldId} type="password" className={inputCls}
              value={tokenSecret} onChange={(e) => setTokenSecret(e.target.value)} />
          </div>
          {halfFilled && (
            <p className="text-[12px] text-red">
              Token id and secret must both be filled in.
            </p>
          )}
          {error && <p className="text-[12px] text-red">{error}</p>}
          <div className="flex justify-end gap-2">
            {stored && (
              <Button type="button" variant="ghost"
                onClick={() => { setOpen(false); setError('') }}>Cancel</Button>
            )}
            <Button type="button"
              aria-label={`${stored ? 'Rotate' : 'Add'} ${label} token`}
              disabled={!tokenId || !tokenSecret || save.isPending}
              onClick={() => save.mutate()}>
              {save.isPending ? 'Verifying…' : stored ? 'Rotate' : 'Add'}
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}

export function HostCapabilityList({ hostId }: { hostId: number }) {
  const host = useQuery({
    queryKey: ['hosts', hostId],
    queryFn: () => api<HostCapabilities>(`/hosts/${hostId}`),
  })
  return (
    <QueryState query={host}
                emptyTitle="No capabilities reported"
                emptyNote="This host has no capability tokens to show."
                empty={(d) => !d.capabilities || Object.keys(d.capabilities).length === 0}
                errorTitle="Capabilities not readable"
                errorNote="Proxploy could not reach the backend to check this host's tokens.">
      {(data) => (
        <div>
          <p className="mb-1 text-[11px] uppercase tracking-wide text-text-3">
            Capability tokens
          </p>
          <p className="mb-2 text-[11.5px] text-text-3">
            The setup script prints one token per capability. A capability with no
            token fails the first time you use the feature, not here.
          </p>
          {Object.entries(data.capabilities ?? {}).map(([name, stored]) => (
            <CapabilityRow key={name} hostId={hostId} name={name}
              // monitoring is required=True and the host cannot exist without it,
              // so it is rotate-only and never shown as a gap.
              stored={stored || name === 'monitoring'} />
          ))}
        </div>
      )}
    </QueryState>
  )
}
