import { Icon } from './ui/icon'
import { Button } from './ui/button'
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
  const rules = q.data?.rules ?? []
  const digest = q.data?.digest ?? null

  if (!q.isLoading && rules.length === 0) {
    return (
      <div className="rounded-ctl border border-line-soft bg-elev p-4">
        <p className="text-[13px] text-text-3">
          No rules here yet. Proxmox applies this firewall&apos;s default policy
          to everything until you add one.
        </p>
        {canEdit && (
          <Button className="mt-3" onClick={onAdd}>Add rule</Button>
        )}
      </div>
    )
  }

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
                      <button type="button"
                        aria-label={`Turn rule ${r.pos} ${on ? 'off' : 'on'}`}
                        onClick={() => update.mutate({
                          pos: r.pos,
                          // RulePatch's digest is `string | undefined`, unlike
                          // move/delete's `string | null`: null becomes
                          // undefined here rather than widening that type.
                          patch: { enable: on ? 0 : 1, digest: digest ?? undefined },
                        })}
                        className={on ? 'text-green' : 'text-text-3'}>
                        <Icon name={on ? 'toggle_on' : 'toggle_off'} size={16} />
                      </button>
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
                        <button type="button" aria-label={`Move rule ${r.pos} up`}
                          onClick={() => move.mutate({
                            pos: r.pos, moveto: r.pos - 1, digest,
                          })}
                          className="text-text-3 hover:text-text">
                          <Icon name="arrow_upward" size={16} />
                        </button>
                      )}
                      {i < rules.length - 1 && (
                        <button type="button" aria-label={`Move rule ${r.pos} down`}
                          onClick={() => move.mutate({
                            pos: r.pos, moveto: r.pos + 1, digest,
                          })}
                          className="text-text-3 hover:text-text">
                          <Icon name="arrow_downward" size={16} />
                        </button>
                      )}
                      <button type="button" aria-label={`Edit rule ${r.pos}`}
                        onClick={() => onEdit(r)}
                        className="text-text-3 hover:text-text">
                        <Icon name="edit" size={16} />
                      </button>
                      <button type="button" aria-label={`Delete rule ${r.pos}`}
                        onClick={() => remove.mutate({ pos: r.pos, digest })}
                        className="text-text-3 hover:text-red">
                        <Icon name="delete" size={16} />
                      </button>
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
}
