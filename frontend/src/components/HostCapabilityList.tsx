import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, apiErrorDetail } from '../api/client'
import { inputCls } from './LoginForm'
import { Button } from './ui/button'
import { ButtonGroup, ButtonGroupSeparator } from './ui/button-group'
import { QueryState } from './QueryState'
import { Skeleton, SkeletonGroup, SkeletonLine } from './ui/skeleton'

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

// The other enrolled hosts of this host's cluster, by the node name Proxmox
// gave them. Empty on a standalone host, which is every single-host install.
type Peer = { id: number; node: string }
type HostRow = { id: number; name: string; node_name?: string | null; cluster_name?: string | null }

// "node1", "node1 and node2", "node1, node2 and node3".
const listOf = (names: string[]) =>
  names.length < 2 ? names.join('') : `${names.slice(0, -1).join(', ')} and ${names.at(-1)}`

/**
 * What the operator is told once Save has finished writing (plan section 5).
 * `stored` starts with the origin, because the origin is written first and a
 * peer's refusal never takes it back: every outcome here either added a
 * working token or changed nothing.
 */
const outcome = (label: string, origin: string, stored: string[], refused: string[]) =>
  refused.length === 0
    ? `${label} token stored on ${listOf(stored)}.`
    : `${label} token stored on ${listOf(stored)}. ${listOf(refused)} refused the same `
      + `token, so ${label} is still not configured there. ${origin} keeps the token you `
      + `just saved. Check that the token exists on ${listOf(refused)} and that its `
      + 'permissions cover it, then add it from '
      + (refused.length > 1 ? "each of those nodes' Edit dialog." : `${refused[0]}'s Edit dialog.`)

function CapabilityRow({ hostId, name, stored, cluster, originNode, peers }: {
  hostId: number; name: string; stored: boolean
  cluster: string; originNode: string; peers: Peer[]
}) {
  const qc = useQueryClient()
  const label = labelOf(name)
  // Closed on both sides now, stored or not.
  //
  // This file used to open a missing capability straight into its fields, on
  // the reasoning that the gap IS the prompt. That held while the row's only
  // control was a Rotate that appeared once a token existed: with nothing
  // stored there was no button to press, so the fields had to be the
  // invitation. Add is that invitation now, so the open fields were saying
  // the same thing a second time, and four capabilities meant a dialog that
  // opened with eight inputs already unrolled.
  //
  // Both buttons therefore reveal, and neither state shows a field until
  // asked. Replacing a working token is still never one stray keystroke
  // away, which was the other half of the original reasoning and is
  // unchanged.
  const [open, setOpen] = useState(false)
  const [tokenId, setTokenId] = useState('')
  const [tokenSecret, setTokenSecret] = useState('')
  const [error, setError] = useState('')
  // Pre ticked: the same token already works on every node of the cluster, so
  // storing it once and leaving the peers reporting "not configured" is the
  // outcome nobody wants. Untick and it is a single-host save, exactly as
  // before. Shown only when there is a peer to name.
  const [alsoPeers, setAlsoPeers] = useState(true)
  const [result, setResult] = useState('')
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
  // Focus in an effect, not inside the click handler. `setOpen(true)` does not
  // render synchronously, so focusing on the next line reached for an input
  // that did not exist yet and silently did nothing. That went unnoticed while
  // an unstored row started open, because then the ref happened to be live
  // already, and the one state that still needed it (Rotate on a stored row)
  // was the one state nobody focus-tested.
  useEffect(() => { if (open) idRef.current?.focus() }, [open])
  const reveal = () => { setResult(''); setOpen(true) }

  const save = useMutation({
    mutationFn: async () => {
      // One host per call, capability named every time, because that is what
      // POST /hosts/{id}/credentials already does correctly: it verifies the
      // token against that host before it stores anything. Propagation to the
      // cluster is this loop and nothing more.
      const post = (id: number) => api(`/hosts/${id}/credentials`, {
        method: 'POST',
        body: JSON.stringify({ token_id: tokenId, token_secret: tokenSecret,
                              capability: name }) })
      // Origin first, and it throws on refusal, so nothing reaches a peer
      // when the origin will not take the token.
      await post(hostId)
      const written = [hostId]
      if (!alsoPeers || peers.length === 0) return { message: '', written }
      const done = [originNode]
      const refused: string[] = []
      for (const p of peers) {
        try { await post(p.id); done.push(p.node); written.push(p.id) }
        catch { refused.push(p.node) }
      }
      return { message: outcome(label, originNode, done, refused), written }
    },
    onSuccess: ({ message, written }) => {
      setTokenId(''); setTokenSecret(''); setError(''); setOpen(false); setResult(message)
      // Patch every host that took the token, this one and each peer, in
      // place -- we already know the result, no need to round-trip a GET for
      // it. The peers matter as much as the origin here: queries are fresh
      // for 15 seconds (main.tsx), so a peer's Edit dialog opened right after
      // this would otherwise show the capability it just gained as still
      // missing. A host whose detail was never fetched has no cache entry and
      // is left to fetch it when something asks. The hosts table's separate
      // ['hosts'] query is invalidated (exact, not a prefix match) so it
      // refetches next time it's active without also re-fetching these same
      // detail queries out from under the row we just closed.
      for (const id of written) {
        qc.setQueryData<HostCapabilities>(['hosts', id], (old) =>
          old ? { ...old, capabilities: { ...old.capabilities, [name]: true } } : old)
      }
      qc.invalidateQueries({ queryKey: ['hosts'], exact: true })
    },
    // The route names the address and says the old credential is still in
    // place; naming the capability is what turns it from a bare 502 into
    // something the operator can act on.
    onError: (e) => setError(`${label}: ${apiErrorDetail(e, 'Request failed, try again.')}`),
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
          * Both reveal the same fields; which one you get is decided by
          * whether a token exists, not by what the fields do.
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
          <Button type="button" variant="ghost" size="sm" disabled={stored}
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
          <Button type="button" variant="ghost" size="sm" disabled={!stored}
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
          {/* Consent before the save, not a prompt after it: one Save writes
            * the origin and the ticked peers, and the secret is never held
            * waiting for a second decision. */}
          {peers.length > 0 && (
            <label className="flex items-start gap-1.5 text-[11.5px] text-text-2">
              <input type="checkbox" className="mt-0.5" checked={alsoPeers}
                onChange={(e) => setAlsoPeers(e.target.checked)} />
              <span>
                Also store this on the other nodes of cluster {cluster}:{' '}
                {peers.map((p) => p.node).join(', ')}.
                <span className="block text-[11px] text-text-3">
                  A Proxmox API token works across the whole cluster, so the same
                  token is verified against each node before it is stored there.
                </span>
              </span>
            </label>
          )}
          {/*
            * `size="sm"`, not the default md, is the "make the Add button 30%
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
              <Button type="button" variant="ghost" size="sm"
                onClick={() => { setOpen(false); setError('') }}>Cancel</Button>
            )}
            {/* "Save", not "Add"/"Rotate" any more. Those two words now name
              * the buttons that OPEN this form, and repeating one of them on
              * the control that commits it made the same word mean "show me
              * the fields" and "write this token" in one row. This button has
              * one job either way, which is to save what was typed. The
              * aria-label keeps the capability, since several of these forms
              * can be open at once. */}
            <Button type="button" size="sm"
              aria-label={`Save ${label} token`}
              disabled={!tokenId || !tokenSecret || save.isPending}
              onClick={() => save.mutate()}>
              {save.isPending ? 'Verifying…' : 'Save'}
            </Button>
          </div>
        </div>
      )}
      {/* Under the row, not inside the form, because the form has closed by
        * the time there is anything to say. */}
      {result && <p className="mt-1 text-[11.5px] text-text-3">{result}</p>}
    </div>
  )
}

export function HostCapabilityList({ hostId }: { hostId: number }) {
  const host = useQuery({
    queryKey: ['hosts', hostId],
    queryFn: () => api<HostCapabilities>(`/hosts/${hostId}`),
  })
  // The sibling list comes from the hosts table's own query, on the ['hosts']
  // key every other page already uses, so this dedupes against whichever
  // mounted first rather than adding a request. GET /hosts carries
  // cluster_name and node_name.
  const hosts = useQuery({ queryKey: ['hosts'], queryFn: () => api<HostRow[]>('/hosts') })
  const origin = hosts.data?.find((h) => h.id === hostId)
  const cluster = origin?.cluster_name ?? ''
  const peers: Peer[] = cluster
    ? (hosts.data ?? []).filter((h) => h.id !== hostId && h.cluster_name === cluster)
        .map((h) => ({ id: h.id, node: h.node_name || h.name }))
    : []
  return (
    <QueryState query={host}
                // This list is the whole body of the Tokens dialog, so the
                // wait is the dialog appearing to be empty. Four rows,
                // because services/pveum.py::CAPABILITIES has four and the
                // count has not moved; it is a placeholder, not a promise.
                loading={<SkeletonGroup label="Loading capability tokens">
                  <SkeletonLine className="mb-1 w-32 text-[11px]" />
                  <SkeletonLine className="mb-2 w-full text-[11.5px]" />
                  {Array.from({ length: 4 }, (_, i) => (
                    <div key={i} className="border-t border-line-soft py-2 first:border-t-0">
                      <div className="flex items-center justify-between gap-3">
                        <SkeletonLine className="w-24 text-[13px]" />
                        {/* The welded Add/Rotate pair, two size="sm" buttons. */}
                        <Skeleton className="h-[30px] w-32 rounded-ctl" />
                      </div>
                    </div>
                  ))}
                </SkeletonGroup>}
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
              cluster={cluster} originNode={origin?.node_name || origin?.name || ''}
              peers={peers}
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
