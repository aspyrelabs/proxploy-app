import { useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, ApiError } from '../api/client'
import { inputCls } from './LoginForm'
import { Button } from './ui/button'
import { ButtonGroup, ButtonGroupSeparator } from './ui/button-group'
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
  const idRef = useRef<HTMLInputElement>(null)

  // What the row's two buttons do, and it is the same thing for both: show
  // the fields and put the caret in the first one.
  //
  // WHY THEY SHARE A HANDLER. Only one of the pair is ever enabled (see the
  // group below), so the enabled one IS the row's action, and the fields it
  // opens submit as Add or Rotate accordingly. There is no third behaviour
  // for a second handler to carry.
  //
  // WHY IT FOCUSES. An unconfigured row is already open (`open` starts at
  // `!stored`), so its Add button would otherwise be a control that visibly
  // does nothing when clicked, which is the same trap as a live-looking
  // Rotate with no token to rotate. Moving the caret into the token id field
  // is a real answer to "I clicked Add", and in a dialog listing four
  // capabilities, eight inputs deep, it is a useful one. When the fields are
  // closed the ref is null and the click just opens them, which is feedback
  // enough on its own.
  const reveal = () => { setOpen(true); idRef.current?.focus() }

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
        {/*
          * Add and Rotate as one welded pair, one per capability. Exactly one
          * of them is live at a time, and WHICH one is how the row reports
          * its state: there is no separate "stored" / "not configured" label
          * any more, because it said the same thing twice as soon as Add
          * started reading "Stored".
          *
          * ROTATE IS DISABLED WITH NOTHING STORED. There is no credential to
          * replace on an unconfigured capability, so a live Rotate could only
          * open the very fields Add already opens: two buttons, one outcome,
          * and the operator left guessing which was meant for them. Disabled
          * is also what the backend does, POST /credentials on an unknown
          * capability is the same route either way, so the difference is
          * purely which word describes it honestly. Mirrors Stored disabling
          * Add from the other side, so the pair always reads as "this one, not
          * that one".
          *
          * STORED IS NOT DIMMED. Everything else disabled here goes to
          * `disabled:opacity-50`; this one holds `text-green` at full
          * strength, because it is not a control being withheld, it is the
          * row's status readout that happens to sit in the control's place,
          * and it is the same green the status text used before it.
          */}
        <ButtonGroup>
          <Button type="button" variant="ghost" size="xs" disabled={stored}
            /* `text-green!`, with the important modifier, and it is not
             * belt-and-braces. Button composes `${variants[variant]}
             * ${className}`, so this lands after ghost's `text-text` in the
             * class ATTRIBUTE, but two utilities of equal specificity are
             * resolved by their order in the generated stylesheet, not by
             * attribute order, and `text-text` was winning. The button
             * rendered the same near-white as Add, while a test asserting the
             * class was present passed, because the class WAS present. */
            className={stored ? 'text-green! disabled:opacity-100' : ''}
            aria-label={stored
              ? `${label} token already stored`
              : `Add ${label} token, show fields`}
            onClick={reveal}>{stored ? 'Stored' : 'Add'}</Button>
          <ButtonGroupSeparator />
          <Button type="button" variant="ghost" size="xs" disabled={!stored}
            aria-label={`Rotate ${label} token, show fields`}
            onClick={reveal}>Rotate</Button>
        </ButtonGroup>
      </div>
      {open && (
        <div className="mt-2 space-y-2">
          <div>
            <label htmlFor={idFieldId}
              className="mb-1 block text-[11px] uppercase tracking-wide text-text-3">
              {label} token id
            </label>
            <input id={idFieldId} ref={idRef} className={inputCls} value={tokenId}
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
          {/*
            * `size="xs"`, not the default md, is the "make the Add button 30%
            * smaller" ask. This submit is the only Add button that existed
            * before the group above, so it is the one that shrank.
            *
            * xs is the size the scale already had (the App Store card's
            * Install button) and it lands where the ask does without a
            * bespoke class: text 13px -> 9px is -30.8%, and text size is what
            * reads as "how big is this button". Padding comes along at -35.7%
            * horizontal and -25% vertical. Whole pixels throughout, because
            * ui/button.tsx's own note is that a fractional font size renders
            * blurry, and a literal 30% of 13px would be 9.1px.
            *
            * Cancel goes with it. The two are one pair at the foot of the
            * fields, and a full-height Cancel beside a 25px Add would read as
            * the primary action, which is backwards.
            */}
          <div className="flex justify-end gap-2">
            {stored && (
              <Button type="button" variant="ghost" size="xs"
                onClick={() => { setOpen(false); setError('') }}>Cancel</Button>
            )}
            <Button type="button" size="xs"
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
              // so it is rotate-only and never shown as a gap. Forcing `stored`
              // is still the whole mechanism under the button group: its Add
              // reads Stored and is disabled, its Rotate is the live one, and
              // its fields stay closed until asked for. That is the correct
              // reading even in the case the flag exists for, a backend that
              // reports monitoring: false for a host that demonstrably
              // connected, where offering Add would invite a second token for
              // a capability that already has one.
              stored={stored || name === 'monitoring'} />
          ))}
        </div>
      )}
    </QueryState>
  )
}
