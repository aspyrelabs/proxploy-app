import { useEffect, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import { useHostCapabilityCatalog, useHostPeers } from '../api/hosts'
import type { HostPeer, PeerEnrolResult } from '../api/hosts'
import { Button } from './ui/button'
import { Loading } from './ui/loading'

/**
 * The offer to add the other nodes of a cluster, once one node of it has been
 * added (docs/notes/cluster-peer-auto-enrolment-plan.md, phase 5).
 *
 * Its own component rather than more JSX in HostForm because the same panel is
 * mounted from HostEditDialog for hosts enrolled before this shipped.
 *
 * Nothing here writes anything until the operator presses Add these nodes.
 * Discovery is read-only and leaving the page adds nothing.
 */

/** Ticked only if it can actually be added: a peer already in Proxploy cannot
 *  be added again, and one that did not answer cannot be reached to verify a
 *  token against. Both still render, so neither is a peer that silently
 *  vanished. */
const addable = (p: HostPeer) => p.reachable && !p.already_enrolled_as

export function PeerEnrolmentPanel({ hostId, node, cluster, onDone }: {
  hostId: number
  /** The origin's Proxmox node name, which is what the cluster calls it. */
  node: string
  /** From POST /hosts. Only used for the checking message, because discovery
   *  is what settles whether there is a cluster at all. */
  cluster?: string | null
  /** Fires when the operator is done with the panel, whether they added
   *  nodes, skipped, or there were none to offer. Left out where the panel is
   *  not a stage in a flow: HostEditDialog has nothing to continue to, so it
   *  gets no Skip and no Continue rather than a button that continues to
   *  nothing. The dialog's own Cancel and Save close it. */
  onDone?: () => void
}) {
  const qc = useQueryClient()
  const q = useHostPeers(hostId)
  const catalog = useHostCapabilityCatalog()
  // null means "nothing touched yet", which is what makes every addable peer
  // pre-ticked without an effect that would fight the operator's own clicks.
  const [ticked, setTicked] = useState<string[] | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [results, setResults] = useState<PeerEnrolResult[] | null>(null)

  const peers = q.data?.peers ?? []
  const entitled = q.data?.multi_host_entitled !== false
  const chosen = ticked ?? peers.filter(addable).map(p => p.node)
  // A standalone node has no peers, so there is no panel and the flow ends
  // exactly where it ended before this existed. A discovery failure ends the
  // same way rather than blocking a host that was added successfully: the
  // offer is not the enrolment, and HostEditDialog makes it again.
  // Results outrank a later discovery: once peers have been added, what
  // happened to them is the panel's job to show, whatever the refetch below
  // says next.
  const nothingToOffer = !results && ((q.isSuccess && peers.length === 0) || q.isError)
  // onDone is a fresh closure on every render of the parent, so depending on
  // it would fire it again on every render rather than once.
  // eslint-disable-next-line react-hooks/exhaustive-deps -- onDone is not stable
  useEffect(() => { if (nothingToOffer) onDone?.() }, [nothingToOffer])

  const labelOf = (key: string) =>
    catalog.data?.find(c => c.key === key)?.label ?? key

  async function confirm() {
    setBusy(true); setError('')
    try {
      const r = await api<{ results: PeerEnrolResult[] }>(`/hosts/${hostId}/peers`, {
        method: 'POST',
        body: JSON.stringify({
          nodes: chosen,
          // The fingerprint this panel displayed, per node. It is only ever
          // used to refuse: a node presenting a different certificate by now
          // is not added, rather than pinned to something the operator never
          // saw.
          tls_fingerprints: Object.fromEntries(
            peers.filter(p => chosen.includes(p.node) && p.tls_fingerprint)
              .map(p => [p.node, p.tls_fingerprint])) }) })
      setResults(r.results)
      // Every enrolled peer is a new host row. HostForm's callers invalidate
      // when onCreated fires, HostEditDialog has no such moment, and the
      // hosts list is otherwise stale for 15 seconds after this wrote to it.
      qc.invalidateQueries({ queryKey: ['hosts'] })
    } catch {
      // Only 403 (the tier changed under the operator), 404 and 422 get here:
      // every per-peer failure is a result row, not a status code.
      setError('Proxploy could not add these nodes. Nothing was added and nothing '
             + 'was stored. Try again, or add them from Settings.')
    } finally { setBusy(false) }
  }

  if (nothingToOffer) return null
  if (q.isPending || busy) {
    // The Edit dialog has no cluster name to hand until discovery answers,
    // so the sentence has to still be a sentence without one.
    const named = cluster ?? q.data?.cluster
    const label = busy ? 'Adding the nodes you ticked'
      : `Checking the other nodes of ${named ? `cluster ${named}` : 'this cluster'}`
    return (
      <div className="flex items-center gap-2 rounded-ctl border border-line bg-panel-2 p-3">
        <Loading label={label} size={18} />
        <p className="text-[12.5px] text-text-2">{label}</p>
      </div>
    )
  }

  return (
    <div className="space-y-2 rounded-ctl border border-line bg-panel-2 p-3">
      {results ? (
        <>
          {results.map(r => (
            <p key={r.node} className={`text-[12.5px] ${
              r.status === 'failed' ? 'text-red'
              : r.status === 'skipped' ? 'text-text-2'
              : r.capabilities_failed.length ? 'text-amber' : 'text-green'}`}>
              {/* The backend's own detail already says what happened and what
                  to do, so it is rendered rather than wrapped in new wording.
                  It is null only when a peer enrolled with nothing rejected,
                  which is the one case with nothing to report but the tokens
                  that were copied. */}
              {r.detail ?? `${r.node} was added, with these tokens stored: `
                + `${r.capabilities_stored.map(labelOf).join(', ')}.`}
            </p>
          ))}
          {onDone && <Button type="button" onClick={onDone}>Continue</Button>}
        </>
      ) : (
        <>
          <p className="text-[12.5px] text-text-2">
            {node} is part of cluster {q.data?.cluster}. Proxploy found{' '}
            {peers.length === 1 ? '1 other node' : `${peers.length} other nodes`} in it.
          </p>
          {entitled ? (
            <>
              <p className="text-[11.5px] text-text-3">
                {/* "the tokens you just entered", which is what the plan wrote
                    for the add-host flow, is not true in the Edit dialog,
                    where nobody just entered anything. Same sentence, true at
                    both call sites. */}
                A Proxmox API token is shared across the whole cluster, so the tokens
                stored for {node} will work on these nodes too. Each node you tick is
                added as its own host and gets its own copy of the tokens.
              </p>
              {/* Said before anything is ticked, rather than discovered in the
                  hosts table afterwards. */}
              <p className="text-[11.5px] text-text-3">
                {q.data?.team
                  ? `These nodes will join the same team as ${node}: ${q.data.team.name}.`
                  : `${node} is not in a team, so these nodes will not be in one `
                    + 'either. You can assign them in Settings afterwards.'}
              </p>
            </>
          ) : (
            <p className="text-[11.5px] text-text-3">
              Adding more than one host needs a paid tier, so these nodes cannot be
              added yet.
            </p>
          )}
          <div className="space-y-1.5">
            {peers.map(p => (
              <label key={p.node} className="flex items-start gap-1.5 text-[11.5px] text-text-2">
                {/* No checkbox at all without the entitlement, rather than
                    ticks that would every one of them fail on confirm. */}
                {entitled && (
                  <input type="checkbox" className="mt-0.5" disabled={!addable(p)}
                    checked={addable(p) && chosen.includes(p.node)}
                    onChange={e => setTicked(chosen.filter(n => n !== p.node)
                      .concat(e.target.checked ? [p.node] : []))} />
                )}
                <span>
                  {p.node}, {p.address}
                  {p.already_enrolled_as && (
                    <span className="block text-[11px] text-text-3">
                      Already in Proxploy as {p.already_enrolled_as}.
                    </span>
                  )}
                  {p.error && (
                    <span className="block text-[11px] text-text-3">{p.error.detail}</span>
                  )}
                  {p.tls_fingerprint && (
                    <span className="block font-mono text-[11px] text-text-3">
                      TLS fingerprint {p.tls_fingerprint}
                    </span>
                  )}
                </span>
              </label>
            ))}
          </div>
          {error && <p className="text-[12.5px] text-red">{error}</p>}
          {(entitled || onDone) && (
            <div className="flex gap-2">
              {entitled && (
                <Button type="button" onClick={confirm} disabled={!chosen.length}>
                  Add these nodes
                </Button>
              )}
              {onDone && (
                <Button type="button" variant="ghost" onClick={onDone}>
                  {entitled ? 'Skip' : 'Continue'}
                </Button>
              )}
            </div>
          )}
        </>
      )}
    </div>
  )
}
