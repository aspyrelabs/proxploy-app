import { Icon } from './ui/icon'
import { Button } from './ui/button'
import { QueryState } from './QueryState'
import { useDeleteRule, useMoveRule, useRules, useUpdateRule } from '../api/firewall'
import type { Rule, Scope } from '../api/firewall'

const th = 'pb-2 text-[11px] font-medium uppercase tracking-wide text-text-3'
const td = 'py-2.5 text-[13px] text-text-2'

/** PVE stores nothing for "match anything", and an empty cell reads as a
 *  missing value rather than a deliberate one. */
function any(v: string | null | undefined) {
  return v == null || v === '' ? 'any' : v
}

/** Protocol and port as one phrase, because that is how an operator says it.
 *  "tcp/22", "tcp/80:85", "tcp" with no port, or "any" with neither. */
function portLabel(rule: Rule) {
  const proto = rule.proto ?? null
  const port = rule.dport ?? null
  if (!proto && !port) return 'any'
  if (!port) return proto as string
  if (!proto) return port
  return `${proto}/${port}`
}

export function FirewallRuleTable({ scope, canEdit, onEdit, onAdd }: {
  scope: Scope
  canEdit: boolean
  onEdit: (rule: Rule) => void
  onAdd: () => void
}) {
  const q = useRules(scope)
  const move = useMoveRule(scope)
  const update = useUpdateRule(scope)
  const remove = useDeleteRule(scope)

  // QueryState keeps "no rules" and "could not read" apart — opposite
  // answers, never the same screen.
  return (
    <QueryState query={q}
      empty={(d) => (d.rules ?? []).length === 0}
      emptyTitle="No rules here yet"
      emptyNote={"Proxmox applies this firewall's default policy to everything "
        + 'until you add one.'}
      emptyAction={canEdit ? <Button onClick={onAdd}>Add rule</Button> : undefined}
      errorTitle="Could not read these rules"
      errorNote={"Proxploy could not read this firewall's rules, so it cannot say "
        + 'what is allowed here or whether any rules exist at all.'}>
      {(data) => {
        const rules = data.rules ?? []
        const digest = data.digest ?? null
        return (
          <div>
            <table aria-label="Firewall rules" className="w-full text-left text-[13px]">
              <thead>
                <tr className="border-b border-line-soft">
                  <th scope="col" className={th}>#</th>
                  <th scope="col" className={th}>On</th>
                  <th scope="col" className={th}>Direction</th>
                  <th scope="col" className={th}>Action</th>
                  <th scope="col" className={th}>Source</th>
                  <th scope="col" className={th}>Destination</th>
                  <th scope="col" className={th}>Protocol and port</th>
                  <th scope="col" className={th}>Comment</th>
                  <th scope="col" className={th} />
                </tr>
              </thead>
              <tbody>
                {rules.map((r, i) => {
                  const on = (r.enable ?? 0) !== 0
                  return (
                    <tr key={r.pos} className="border-b border-line-soft/60">
                      <td className={`${td} font-mono text-text-3`}>{r.pos}</td>
                      <td className={td}>
                        <div className="flex items-center gap-1.5">
                          {/* The state is its own element with its own accessible
                              name, always rendered: it says what is currently true,
                              which is not the same thing the toggle button (when
                              present) says clicking it will do. */}
                          <span role="img" aria-label={`Rule ${r.pos} is ${on ? 'on' : 'off'}`}
                            className={on ? 'text-green' : 'text-text-3'}>
                            <Icon name={on ? 'toggle_on' : 'toggle_off'} />
                          </span>
                          {canEdit && (
                            <Button type="button" variant="icon" size="icon-xs"
                              aria-label={`Turn rule ${r.pos} ${on ? 'off' : 'on'}`}
                              onClick={() => update.mutate({
                                pos: r.pos,
                                // RulePatch's digest is `string | undefined`, unlike
                                // move/delete's `string | null`: null becomes
                                // undefined here rather than widening that type.
                                patch: { enable: on ? 0 : 1, digest: digest ?? undefined },
                              })}
                              // The only one of these that carries state rather
                              // than just an action, so it overrides the
                              // variant's resting tint when the rule is on.
                              // `!` for the same reason HostCapabilityList
                              // needs it: this and the variant's text-text-3
                              // are equal-specificity utilities, so stylesheet
                              // order decides, not the order they are written.
                              className={on ? 'text-green!' : ''}>
                              <Icon name={on ? 'toggle_on' : 'toggle_off'} size={16} />
                            </Button>
                          )}
                        </div>
                      </td>
                      <td className={`${td} font-mono text-[12px]`}>{r.type}</td>
                      <td className={`${td} font-medium`}>{r.action}</td>
                      <td className={`${td} font-mono text-[12px]`}>{any(r.source)}</td>
                      <td className={`${td} font-mono text-[12px]`}>{any(r.dest)}</td>
                      <td className={`${td} font-mono text-[12px]`}>{portLabel(r)}</td>
                      <td className={`${td} text-text-3`}>{r.comment ?? ''}</td>
                      <td className={td}>
                        {canEdit && (
                          <div className="flex items-center justify-end gap-1">
                            {i > 0 && (
                              /* PVE's pos is a dense array index, not a stable id: renumbered on
                                 every delete (pve-manager 9.2.11: deleting the middle of three
                                 renumbered 0,1,2 to 0,1). The guard is index-based because the array
                                 is what tells us there's a neighbour. New rules are PREPENDED, so an
                                 added rule lands at pos 0. */
                              <Button type="button" variant="icon" size="icon-xs"
                                aria-label={`Move rule ${r.pos} up`}
                                onClick={() => move.mutate({
                                  pos: r.pos, moveto: r.pos - 1, digest,
                                })}>
                                <Icon name="arrow_upward" size={16} />
                              </Button>
                            )}
                            {i < rules.length - 1 && (
                              <Button type="button" variant="icon" size="icon-xs"
                                aria-label={`Move rule ${r.pos} down`}
                                /* +2, not +1. PVE inserts at moveto and THEN removes the old row, so
                                   moving down lands the rule at moveto-1 and moveto === pos+1 is a
                                   silent no-op. Measured on pve-manager 9.2.11, 2026-08-21. Moving up
                                   needs no such correction: the removal is below the insert, so the
                                   rule lands at moveto exactly. */
                                onClick={() => move.mutate({
                                  pos: r.pos, moveto: r.pos + 2, digest,
                                })}>
                                <Icon name="arrow_downward" size={16} />
                              </Button>
                            )}
                            <Button type="button" variant="icon" size="icon-xs"
                              aria-label={`Edit rule ${r.pos}`}
                              onClick={() => onEdit(r)}>
                              <Icon name="edit" size={16} />
                            </Button>
                            <Button type="button" variant="icon-danger" size="icon-xs"
                              aria-label={`Delete rule ${r.pos}`}
                              onClick={() => remove.mutate({ pos: r.pos, digest })}>
                              <Icon name="delete" size={16} />
                            </Button>
                          </div>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
            {canEdit && <Button className="mt-3" onClick={onAdd}>Add rule</Button>}
          </div>
        )
      }}
    </QueryState>
  )
}
