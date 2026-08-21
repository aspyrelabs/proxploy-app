import { useId, useState } from 'react'
import { Button } from './ui/button'
import { useCreateRule, useGroups, useMacros, useRefs, useUpdateRule } from '../api/firewall'
import type { Rule, RulePatch, Scope } from '../api/firewall'

const label = 'mb-1 block text-[11px] uppercase tracking-wide text-text-3'
const input = 'w-full rounded-ctl border border-line-soft bg-elev px-2 py-1.5 text-[13px]'

const DIRECTIONS = [
  { value: 'in', label: 'Incoming' },
  { value: 'out', label: 'Outgoing' },
  // PVE 8.2 added forward, and 9.2.11 has it. Listed because a rule PVE stored
  // as forward has to be editable, not only because it can be created.
  { value: 'forward', label: 'Forwarded' },
  { value: 'group', label: 'Security group' },
]

const LOG_LEVELS = ['nolog', 'emerg', 'alert', 'crit', 'err', 'warning',
                    'notice', 'info', 'debug']

export function FirewallRuleForm({ scope, hostId, rule, onClose }: {
  scope: Scope
  hostId: number
  rule: Rule | null
  onClose: () => void
}) {
  const create = useCreateRule(scope)
  const update = useUpdateRule(scope)
  const refs = useRefs(scope)
  const macros = useMacros(hostId)
  const groups = useGroups(hostId)
  const [advanced, setAdvanced] = useState(
    // Open on an existing rule that uses one of these, so editing it does not
    // hide the field that is set.
    () => Boolean(rule?.macro || rule?.iface || rule?.log || rule?.['icmp-type']),
  )
  const listId = useId()

  const [form, setForm] = useState<RulePatch>(() => ({
    type: rule?.type ?? 'in',
    action: rule?.action ?? 'ACCEPT',
    enable: rule?.enable ?? 1,
    proto: rule?.proto ?? '',
    source: rule?.source ?? '',
    dest: rule?.dest ?? '',
    sport: rule?.sport ?? '',
    dport: rule?.dport ?? '',
    comment: rule?.comment ?? '',
    macro: rule?.macro ?? '',
    iface: rule?.iface ?? '',
    log: rule?.log ?? '',
    'icmp-type': rule?.['icmp-type'] ?? '',
  }))

  const set = (k: keyof RulePatch, v: string | number) =>
    setForm(f => ({ ...f, [k]: v }))

  function submit(e: React.FormEvent) {
    e.preventDefault()
    // Empty string means "the operator left it blank", which is not a value
    // PVE has. Dropping them here is what keeps a create from sending
    // source="" and a PVE 400 back.
    const body: RulePatch = {}
    for (const [k, v] of Object.entries(form)) {
      if (v === '' || v == null) continue
      ;(body as Record<string, unknown>)[k] = v
    }
    if (rule) {
      update.mutate({ pos: rule.pos, patch: { ...body, digest: rule.digest } },
        { onSuccess: onClose })
    } else {
      create.mutate(body, { onSuccess: onClose })
    }
  }

  const pending = create.isPending || update.isPending
  const err = create.error ?? update.error

  return (
    <form onSubmit={submit} className="flex flex-col gap-3">
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className={label} htmlFor="fw-direction">Direction</label>
          <select id="fw-direction" className={input} value={form.type}
            onChange={e => set('type', e.target.value)}>
            {DIRECTIONS.map(d => (
              <option key={d.value} value={d.value}>{d.label}</option>
            ))}
          </select>
        </div>
        <div>
          <label className={label} htmlFor="fw-action">Action</label>
          {/* A security group name is a legal action, which is why this is not
              a three-value enum. PVE accepts ACCEPT, DROP, REJECT or the name
              of a group. */}
          <select id="fw-action" className={input} value={form.action}
            onChange={e => set('action', e.target.value)}>
            <option value="ACCEPT">ACCEPT</option>
            <option value="DROP">DROP</option>
            <option value="REJECT">REJECT</option>
            {(groups.data?.groups ?? []).map(g => (
              <option key={g.group} value={g.group}>{g.group}</option>
            ))}
          </select>
        </div>
        <div>
          <label className={label} htmlFor="fw-proto">Protocol</label>
          <input id="fw-proto" className={input} value={String(form.proto ?? '')}
            placeholder="any" onChange={e => set('proto', e.target.value)} />
        </div>
        <div>
          <label className={label} htmlFor="fw-dport">Destination port</label>
          <input id="fw-dport" className={input} value={String(form.dport ?? '')}
            placeholder="any" onChange={e => set('dport', e.target.value)} />
        </div>
        <div>
          <label className={label} htmlFor="fw-source">Source</label>
          <input id="fw-source" className={input} list={listId}
            value={String(form.source ?? '')} placeholder="any"
            onChange={e => set('source', e.target.value)} />
        </div>
        <div>
          <label className={label} htmlFor="fw-dest">Destination</label>
          <input id="fw-dest" className={input} list={listId}
            value={String(form.dest ?? '')} placeholder="any"
            onChange={e => set('dest', e.target.value)} />
        </div>
      </div>

      {/* One datalist serving both address fields. An IP set is offered as
          "+name", which is the form a rule actually stores, not as the bare
          name: typing the name without the plus matches an alias instead. */}
      <datalist id={listId}>
        {(refs.data?.refs ?? []).map(r => (
          <option key={`${r.type}:${r.name}`} value={r.ref}>
            {r.ref}
          </option>
        ))}
      </datalist>

      <div>
        <label className={label} htmlFor="fw-comment">Comment</label>
        <input id="fw-comment" className={input} value={String(form.comment ?? '')}
          onChange={e => set('comment', e.target.value)} />
      </div>

      <button type="button" onClick={() => setAdvanced(a => !a)}
        className="self-start text-[12px] text-text-3 hover:text-text">
        {advanced ? 'Hide advanced' : 'Advanced'}
      </button>

      {advanced && (
        <div className="grid grid-cols-2 gap-3 rounded-ctl border border-line-soft bg-elev p-3">
          <div className="col-span-2">
            <label className={label} htmlFor="fw-macro">Macro</label>
            <select id="fw-macro" className={input} value={String(form.macro ?? '')}
              onChange={e => set('macro', e.target.value)}>
              <option value="">None</option>
              {(macros.data?.macros ?? []).map(m => (
                <option key={m.macro} value={m.macro}>{m.macro}</option>
              ))}
            </select>
            {/* Only when a macro is actually chosen. Proxmox gives a macro's name
                and description and does not say which ports it opens, so this
                shows exactly what Proxmox said about the macro in the box above
                and nothing more. A description shown under a select reading
                "None" describes a macro the operator did not pick, whatever its
                text says. */}
            {form.macro && (
              <p className="mt-1 text-[12px] text-text-3">
                {(macros.data?.macros ?? []).find(m => m.macro === form.macro)?.descr}
              </p>
            )}
          </div>
          <div>
            <label className={label} htmlFor="fw-iface">Interface</label>
            <input id="fw-iface" className={input} value={String(form.iface ?? '')}
              placeholder="net0" onChange={e => set('iface', e.target.value)} />
          </div>
          <div>
            <label className={label} htmlFor="fw-sport">Source port</label>
            <input id="fw-sport" className={input} value={String(form.sport ?? '')}
              placeholder="any" onChange={e => set('sport', e.target.value)} />
          </div>
          <div>
            <label className={label} htmlFor="fw-log">Log level</label>
            <select id="fw-log" className={input} value={String(form.log ?? '')}
              onChange={e => set('log', e.target.value)}>
              <option value="">Use the firewall&apos;s setting</option>
              {LOG_LEVELS.map(l => <option key={l} value={l}>{l}</option>)}
            </select>
          </div>
          <div>
            {/* The field name keeps PVE's hyphen all the way through. Renaming
                it to icmp_type anywhere on this path drops it silently. */}
            <label className={label} htmlFor="fw-icmp">ICMP type</label>
            <input id="fw-icmp" className={input}
              value={String(form['icmp-type'] ?? '')}
              placeholder="echo-request"
              onChange={e => set('icmp-type', e.target.value)} />
          </div>
        </div>
      )}

      {err && <p className="text-[12.5px] text-red">
        Could not save that rule. {String((err.body as { detail?: string })?.detail ?? '')}
      </p>}

      {/* Measured on pve-manager 9.2.11: PVE prepends a new rule, so it lands
          at position 0 and outranks every rule below it. Rule order IS
          precedence, so a create silently overrides the rest of the list
          unless the operator is told and moves it. */}
      {!rule && (
        <p className="text-[12px] text-text-3">
          A new rule goes to the top of the list, so it is checked before every rule
          below it. Move it down after saving if that is not what you want.
        </p>
      )}

      <div className="flex justify-end gap-2 pt-1">
        <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
        <Button type="submit" disabled={pending}>
          {pending ? 'Saving...' : 'Save rule'}
        </Button>
      </div>
    </form>
  )
}
