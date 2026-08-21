import { useState } from 'react'
import { Button } from './ui/button'
import { effectiveWarning, useOptions, useRules, useUpdateOptions } from '../api/firewall'
import type { Options, Scope } from '../api/firewall'

const label = 'mb-1 block text-[11px] uppercase tracking-wide text-text-3'
const input = 'w-full rounded-ctl border border-line-soft bg-elev px-2 py-1.5 text-[13px]'

/** Which switches each scope actually has. A node has no policy at all, and
 *  offering one would invent a control that does nothing. Measured on
 *  pve-manager 9.2.11. */
const FIELDS: Record<string, string[]> = {
  cluster: ['enable', 'policy_in', 'policy_out', 'policy_forward', 'ebtables'],
  node: ['enable', 'nftables', 'nosmurfs', 'ndp', 'log_level_in', 'log_level_out'],
  guest: ['enable', 'policy_in', 'policy_out', 'macfilter', 'ipfilter', 'dhcp',
          'ndp', 'radv', 'log_level_in', 'log_level_out'],
}

const TITLES: Record<string, string> = {
  enable: 'Firewall enabled',
  policy_in: 'Incoming policy',
  policy_out: 'Outgoing policy',
  policy_forward: 'Forwarding policy',
  ebtables: 'Bridge filtering',
  nftables: 'Use nftables (Proxmox calls this a tech preview)',
  nosmurfs: 'Block smurf attacks',
  ndp: 'Allow IPv6 neighbor discovery',
  radv: 'Allow sending router advertisements',
  dhcp: 'Allow DHCP',
  macfilter: 'Filter by MAC address',
  ipfilter: 'Filter by IP address',
  log_level_in: 'Log level, incoming',
  log_level_out: 'Log level, outgoing',
}

const POLICY_FIELDS = new Set(['policy_in', 'policy_out', 'policy_forward'])
const LOG_FIELDS = new Set(['log_level_in', 'log_level_out'])
const LOG_LEVELS = ['nolog', 'emerg', 'alert', 'crit', 'err', 'warning',
                    'notice', 'info', 'debug']

export function FirewallOptionsPanel({ scope, canEdit }: {
  scope: Scope; canEdit: boolean
}) {
  const q = useOptions(scope)
  const rulesQ = useRules(scope)
  const save = useUpdateOptions(scope)
  const [patch, setPatch] = useState<Options>({})

  if (q.isLoading || !q.data) {
    return <p className="text-[13px] text-text-3">Reading the firewall settings...</p>
  }

  const { options, defaults, digest } = q.data
  const kind = scope.kind === 'group' ? 'cluster' : scope.kind
  const fields = FIELDS[kind] ?? []

  /** The value in force right now: what was typed, else what PVE stored, else
   *  what PVE does when the key is absent. That last fallback is the whole
   *  point: an empty options object is not an inert firewall. */
  const current = (k: string) => patch[k] ?? options[k] ?? defaults[k] ?? ''

  const merged: Options = { ...options, ...patch }
  // Saved state decides the tense, pending state decides whether to speak at all.
  const savedOn = Number(options.enable ?? defaults.enable ?? 0) !== 0
  const willBeOn = Number(current('enable')) !== 0
  const warning = effectiveWarning(merged, defaults, rulesQ.data?.rules ?? [], savedOn)

  const set = (k: string, v: string | number) => setPatch(p => ({ ...p, [k]: v }))

  return (
    <div className="flex flex-col gap-3">
      <div className="grid grid-cols-2 gap-3">
        {fields.map(f => {
          const id = `fw-opt-${f}`
          if (POLICY_FIELDS.has(f)) {
            return (
              <div key={f}>
                <label className={label} htmlFor={id}>{TITLES[f]}</label>
                <select id={id} className={input} disabled={!canEdit}
                  value={String(current(f))}
                  onChange={e => set(f, e.target.value)}>
                  <option value="ACCEPT">ACCEPT</option>
                  <option value="DROP">DROP</option>
                  {f !== 'policy_forward' && <option value="REJECT">REJECT</option>}
                </select>
              </div>
            )
          }
          if (LOG_FIELDS.has(f)) {
            return (
              <div key={f}>
                <label className={label} htmlFor={id}>{TITLES[f]}</label>
                <select id={id} className={input} disabled={!canEdit}
                  value={String(current(f))}
                  onChange={e => set(f, e.target.value)}>
                  <option value="">Not set</option>
                  {LOG_LEVELS.map(l => <option key={l} value={l}>{l}</option>)}
                </select>
              </div>
            )
          }
          return (
            <div key={f} className="flex items-center gap-2 pt-5">
              {/* PVE stores these as 1 and 0, not true and false. */}
              <input id={id} type="checkbox" disabled={!canEdit}
                checked={Number(current(f)) !== 0}
                onChange={e => set(f, e.target.checked ? 1 : 0)} />
              <label htmlFor={id} className="text-[13px] text-text-2">
                {TITLES[f]}
              </label>
            </div>
          )
        })}
      </div>

      {/* Warn, never block. Proxmox itself lets an operator do this, and a
          refusal here would be a control Proxploy invented. What it owes them
          is an accurate sentence about what happens next, which is why the
          backend sends PVE's defaults alongside the stored values.

          Gated on the PENDING state (willBeOn), not shown unconditionally:
          an untouched, already-off scope resolves to DROP by Proxmox's own
          default, so an always-on warning here would fire on every visit to
          every scope nobody has asked to change, and a warning nobody can
          turn off is a warning nobody reads. It shows once the operator
          ticks the box, or whenever the firewall is already on and this is
          describing something actually happening. */}
      {willBeOn && warning && (
        <p className="rounded-ctl border border-amber/40 bg-amber/10 p-2.5 text-[12.5px] text-text-2">
          {warning}
        </p>
      )}

      {save.error && (
        <p className="text-[12.5px] text-red">
          Could not save those settings.{' '}
          {String((save.error.body as { detail?: string })?.detail ?? '')}
        </p>
      )}

      {canEdit && (
        <div className="flex justify-end">
          <Button disabled={save.isPending || Object.keys(patch).length === 0}
            onClick={() => save.mutate({ ...patch, digest: digest ?? undefined },
              { onSuccess: () => setPatch({}) })}>
            {save.isPending ? 'Saving...' : 'Save settings'}
          </Button>
        </div>
      )}
    </div>
  )
}
