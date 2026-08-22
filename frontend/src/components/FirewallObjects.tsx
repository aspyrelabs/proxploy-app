import { useId, useState } from 'react'
import { Button, segment } from './ui/button'
import { Icon } from './ui/icon'
import { QueryState } from './QueryState'
import {
  useAddIpSetMember, useAliases, useCreateAlias, useCreateGroup, useCreateIpSet,
  useDeleteAlias, useDeleteGroup, useDeleteIpSet, useDeleteIpSetMember, useGroups,
  useIpSetMembers, useIpSets, useUpdateAlias,
} from '../api/firewall'
import type { Alias, ObjectScope } from '../api/firewall'

const label = 'mb-1 block text-[11px] uppercase tracking-wide text-text-3'
const input = 'w-full rounded-ctl border border-line-soft bg-elev px-2 py-1.5 text-[13px]'

const th = 'pb-2 text-[11px] font-medium uppercase tracking-wide text-text-3'
const td = 'py-2.5 text-[13px] text-text-2'

/** The alias create/edit form. Shared between "Add alias" and editing a row,
 *  because the two only differ in whether `alias` carries a digest to PUT
 *  with. */
function AliasForm({ scope, alias, onClose }: {
  scope: ObjectScope
  alias: Alias | null
  onClose: () => void
}) {
  const create = useCreateAlias(scope)
  const update = useUpdateAlias(scope)
  const nameId = useId()
  const cidrId = useId()
  const commentId = useId()
  const [name, setName] = useState(alias?.name ?? '')
  const [cidr, setCidr] = useState(alias?.cidr ?? '')
  const [comment, setComment] = useState(alias?.comment ?? '')
  const pending = create.isPending || update.isPending

  function submit(e: React.FormEvent) {
    e.preventDefault()
    if (alias) {
      // Comment is sent even when blank here, unlike create below: editing
      // is the only way to clear one that was already set.
      update.mutate({
        name: alias.name,
        patch: { cidr, comment, digest: alias.digest },
      }, { onSuccess: onClose })
    } else {
      const body: Alias = comment ? { name, cidr, comment } : { name, cidr }
      create.mutate(body, { onSuccess: onClose })
    }
  }

  return (
    <form onSubmit={submit} className="mt-3 flex flex-col gap-3 rounded-ctl border border-line-soft bg-elev p-3">
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className={label} htmlFor={nameId}>Name</label>
          <input id={nameId} className={input} value={name} disabled={Boolean(alias)}
            onChange={e => setName(e.target.value)} />
        </div>
        <div>
          <label className={label} htmlFor={cidrId}>Address or range</label>
          <input id={cidrId} className={input} value={cidr}
            onChange={e => setCidr(e.target.value)} />
        </div>
      </div>
      <div>
        <label className={label} htmlFor={commentId}>Comment</label>
        <input id={commentId} className={input} value={comment}
          onChange={e => setComment(e.target.value)} />
      </div>
      <div className="flex justify-end gap-2">
        <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
        <Button type="submit" disabled={pending}>
          {pending ? 'Saving...' : 'Save alias'}
        </Button>
      </div>
    </form>
  )
}

/** Alias, address or range, comment. Aliases are cluster- or guest-scoped
 *  names for a CIDR, so a rule can reference "office" instead of repeating
 *  10.0.0.0/24 everywhere it applies. */
export function AliasTable({ scope, canEdit }: { scope: ObjectScope; canEdit: boolean }) {
  const q = useAliases(scope)
  const remove = useDeleteAlias(scope)
  const [editing, setEditing] = useState<Alias | null | 'new'>(null)

  return (
    <div>
      <QueryState query={q}
        empty={(d) => (d.aliases ?? []).length === 0}
        emptyTitle="No aliases here yet"
        emptyNote={'An alias gives an address or range a name, so a rule can say '
          + '"office" instead of repeating the range.'}
        errorTitle="Could not read these aliases"
        errorNote={'Proxploy could not read the aliases for this scope, so it '
          + 'cannot say which names your rules can use, or whether any exist.'}>
        {(d) => (
          <table aria-label="Aliases" className="w-full text-left text-[13px]">
            <thead>
              <tr className="border-b border-line-soft">
                <th scope="col" className={th}>Name</th>
                <th scope="col" className={th}>Address or range</th>
                <th scope="col" className={th}>Comment</th>
                <th scope="col" className={th} />
              </tr>
            </thead>
            <tbody>
              {d.aliases.map(a => (
                <tr key={a.name} className="border-b border-line-soft/60">
                  <td className={`${td} font-mono`}>{a.name}</td>
                  <td className={`${td} font-mono`}>{a.cidr}</td>
                  <td className={`${td} text-text-3`}>{a.comment ?? ''}</td>
                  <td className={td}>
                    {canEdit && (
                      <div className="flex items-center justify-end gap-1">
                        <Button type="button" variant="icon" size="icon-xs"
                          aria-label={`Edit alias ${a.name}`}
                          onClick={() => setEditing(a)}>
                          <Icon name="edit" size={16} />
                        </Button>
                        <Button type="button" variant="icon-danger" size="icon-xs"
                          aria-label={`Delete alias ${a.name}`}
                          onClick={() => remove.mutate({ name: a.name })}>
                          <Icon name="delete" size={16} />
                        </Button>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </QueryState>

      {canEdit && editing == null && (
        <Button className="mt-3" onClick={() => setEditing('new')}>Add alias</Button>
      )}
      {canEdit && editing != null && (
        <AliasForm scope={scope} alias={editing === 'new' ? null : editing}
          onClose={() => setEditing(null)} />
      )}
    </div>
  )
}

/** One set's members, shown once its "Open" button has been clicked. Deleting
 *  the set itself is a separate two-step control below the member list, not
 *  here, because it acts on the set as a whole rather than on one member. */
function IpSetMembers({ scope, name, canEdit }: {
  scope: ObjectScope; name: string; canEdit: boolean
}) {
  const q = useIpSetMembers(scope, name)
  const add = useAddIpSetMember(scope)
  const remove = useDeleteIpSetMember(scope)
  const [adding, setAdding] = useState(false)
  const cidrId = useId()
  const commentId = useId()
  const [cidr, setCidr] = useState('')
  const [comment, setComment] = useState('')

  function submit(e: React.FormEvent) {
    e.preventDefault()
    add.mutate({ name, member: comment ? { cidr, comment } : { cidr } }, {
      onSuccess: () => { setCidr(''); setComment(''); setAdding(false) },
    })
  }

  return (
    <div className="mt-2 border-t border-line-soft pt-2">
      <QueryState query={q}
        empty={(d) => (d.members ?? []).length === 0}
        emptyTitle="No addresses in this set"
        emptyNote={'A rule pointing at an empty set matches nothing. Add an '
          + 'address to give it something to match.'}
        errorTitle="Could not read this set"
        errorNote={'Proxploy could not read what is in this set, so it cannot '
          + 'say which addresses a rule using it would match.'}>
        {(d) => (
          <ul className="flex flex-col gap-1">
            {d.members.map(m => {
              const excluded = Boolean(m.nomatch)
              return (
                <li key={m.cidr} className="flex items-center justify-between text-[13px]">
                  {/* A nomatch member means "everything in this set except this
                      address". Drawing it the same as an ordinary entry would
                      claim the set includes exactly what it excludes. */}
                  {excluded ? (
                    <span aria-label={`${m.cidr} is excluded from this set`}
                      className="flex items-center gap-2">
                      <span className="rounded-full border border-red/30 bg-red-dim px-2 py-0.5 text-[11px] text-red">
                        Excluded
                      </span>
                      <span className="font-mono">{m.cidr}</span>
                      {m.comment && <span className="text-text-3">{m.comment}</span>}
                    </span>
                  ) : (
                    <span className="flex items-center gap-2">
                      <span className="font-mono">{m.cidr}</span>
                      {m.comment && <span className="text-text-3">{m.comment}</span>}
                    </span>
                  )}
                  {canEdit && (
                    <Button type="button" variant="icon-danger" size="icon-xs"
                      aria-label={`Remove ${m.cidr} from ${name}`}
                      onClick={() => remove.mutate({ name, cidr: m.cidr })}>
                      <Icon name="delete" size={16} />
                    </Button>
                  )}
                </li>
              )
            })}
          </ul>
        )}
      </QueryState>

      {canEdit && !adding && (
        <Button size="sm" variant="ghost" className="mt-2" onClick={() => setAdding(true)}>
          Add member
        </Button>
      )}
      {canEdit && adding && (
        <form onSubmit={submit} className="mt-2 flex flex-col gap-2">
          <div>
            <label className={label} htmlFor={cidrId}>Address or range</label>
            <input id={cidrId} className={input} value={cidr}
              onChange={e => setCidr(e.target.value)} />
          </div>
          <div>
            <label className={label} htmlFor={commentId}>Comment</label>
            <input id={commentId} className={input} value={comment}
              onChange={e => setComment(e.target.value)} />
          </div>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" onClick={() => setAdding(false)}>Cancel</Button>
            <Button type="submit" disabled={add.isPending}>
              {add.isPending ? 'Saving...' : 'Save member'}
            </Button>
          </div>
        </form>
      )}
    </div>
  )
}

/** List of IP sets, each expandable to its members. Deleting a set is a
 *  two-step confirm rather than an immediate delete, because Proxmox refuses
 *  a populated set without `force`, and sending that unasked would discard
 *  entries the operator never looked at. */
export function IpSetPanel({ scope, canEdit }: { scope: ObjectScope; canEdit: boolean }) {
  const q = useIpSets(scope)
  const create = useCreateIpSet(scope)
  const remove = useDeleteIpSet(scope)
  const [open, setOpen] = useState<string | null>(null)
  const [confirming, setConfirming] = useState<string | null>(null)
  const [adding, setAdding] = useState(false)
  const nameId = useId()
  const [name, setName] = useState('')

  // Only fetched when its set is open and its delete is being confirmed, so
  // the "how many addresses" figure below is the real member list, not a guess.
  const openMembers = useIpSetMembers(scope, confirming)

  function submitCreate(e: React.FormEvent) {
    e.preventDefault()
    create.mutate({ name }, { onSuccess: () => { setName(''); setAdding(false) } })
  }

  return (
    <div>
      <QueryState query={q}
        empty={(d) => (d.ipsets ?? []).length === 0}
        emptyTitle="No IP sets here yet"
        emptyNote={'An IP set is a named group of addresses a rule can match in '
          + 'one go, instead of one rule per address.'}
        errorTitle="Could not read these IP sets"
        errorNote={'Proxploy could not read the IP sets for this scope, so it '
          + 'cannot say which ones your rules can use, or whether any exist.'}>
        {(d) => (
        <ul className="flex flex-col gap-2">
          {d.ipsets.map(s => (
            <li key={s.name} className="rounded-ctl border border-line-soft bg-elev p-3">
              <div className="flex items-center justify-between">
                <button type="button" aria-label={`Open IP set ${s.name}`}
                  onClick={() => setOpen(o => o === s.name ? null : s.name)}
                  className="flex items-center gap-2 text-left text-[13px] font-medium">
                  <Icon name={open === s.name ? 'expand_less' : 'expand_more'} size={16} />
                  {s.name}
                  {s.comment && <span className="font-normal text-text-3">{s.comment}</span>}
                </button>
                {canEdit && (
                  <Button type="button" variant="icon-danger" size="icon-xs"
                    aria-label={`Delete IP set ${s.name}`}
                    onClick={() => setConfirming(s.name)}>
                    <Icon name="delete" size={16} />
                  </Button>
                )}
              </div>

              {confirming === s.name && (
                <div className="mt-2 rounded-ctl border border-red/30 bg-red-dim p-2.5 text-[12.5px]">
                  {/* The count is a fetched fact, so a failed read must not be
                      spelled as "holds 0 addresses": that reads as a safe
                      delete when nobody knows what is about to go. The buttons
                      sit outside, so Cancel is available in every state. */}
                  <QueryState query={openMembers}
                    loading={<p>Checking what is in this set...</p>}
                    empty={(d) => (d.members ?? []).length === 0}
                    emptyTitle="Nothing in this set"
                    emptyNote="Deleting it removes the set and no addresses."
                    errorTitle="Could not read this set"
                    errorNote={'Proxploy could not read what is in this set, so '
                      + 'it cannot say what deleting it would take with it.'}>
                    {(d) => (
                      <p>
                        This set holds {d.members.length} addresses.
                        Deleting it removes them too.
                      </p>
                    )}
                  </QueryState>
                  <div className="mt-2 flex justify-end gap-2">
                    <Button type="button" size="sm" variant="ghost"
                      onClick={() => setConfirming(null)}>Cancel</Button>
                    <Button type="button" size="sm" variant="danger"
                      onClick={() => remove.mutate({ name: s.name, force: true },
                        { onSuccess: () => setConfirming(null) })}>
                      Delete it and its members
                    </Button>
                  </div>
                </div>
              )}

              {open === s.name && (
                <IpSetMembers scope={scope} name={s.name} canEdit={canEdit} />
              )}
            </li>
          ))}
        </ul>
        )}
      </QueryState>

      {canEdit && !adding && (
        <Button className="mt-3" onClick={() => setAdding(true)}>Add IP set</Button>
      )}
      {canEdit && adding && (
        <form onSubmit={submitCreate} className="mt-3 flex flex-col gap-3 rounded-ctl border border-line-soft bg-elev p-3">
          <div>
            <label className={label} htmlFor={nameId}>Name</label>
            <input id={nameId} className={input} value={name}
              onChange={e => setName(e.target.value)} />
          </div>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" onClick={() => setAdding(false)}>Cancel</Button>
            <Button type="submit" disabled={create.isPending}>
              {create.isPending ? 'Saving...' : 'Save IP set'}
            </Button>
          </div>
        </form>
      )}
    </div>
  )
}

/** Security groups are cluster-wide named rule bundles, listed here so a
 *  rule form's "action" can offer one and a page can edit a group's own
 *  rules once selected. Deleting one is a plain delete: Proxmox itself
 *  refuses if some other rule still references it, which is the right
 *  place for that check, not a guess made here. */
export function SecurityGroupList({ hostId, canEdit, selected, onSelect }: {
  hostId: number
  canEdit: boolean
  selected: string | null
  onSelect: (g: string | null) => void
}) {
  const q = useGroups(hostId)
  const create = useCreateGroup(hostId)
  const remove = useDeleteGroup(hostId)
  const [adding, setAdding] = useState(false)
  const nameId = useId()
  const [name, setName] = useState('')

  function submit(e: React.FormEvent) {
    e.preventDefault()
    create.mutate({ group: name }, { onSuccess: () => { setName(''); setAdding(false) } })
  }

  return (
    <div>
      <QueryState query={q}
        empty={(d) => (d.groups ?? []).length === 0}
        emptyTitle="No security groups here yet"
        emptyNote={'A security group is a named bundle of rules a rule can call '
          + 'by name, so the same set can apply in several places.'}
        errorTitle="Could not read these security groups"
        errorNote={"Proxploy could not read this cluster's security groups, so it "
          + 'cannot say which ones a rule can call, or whether any exist.'}>
        {(d) => (
        <ul className="flex flex-col gap-1">
          {d.groups.map(g => (
            <li key={g.group} className="flex items-center justify-between">
              <button type="button" aria-label={`Open security group ${g.group}`}
                aria-pressed={selected === g.group}
                onClick={() => onSelect(g.group)}
                className={`flex-1 rounded-ctl px-2 py-1.5 text-left text-[13px]
                             ${selected === g.group ? 'font-medium' : ''}
                             ${segment(selected === g.group)}`}>
                {g.group}
                {g.comment && <span className="ml-2 font-normal text-text-3">{g.comment}</span>}
              </button>
              {canEdit && (
                <Button type="button" variant="icon-danger" size="icon-xs"
                  aria-label={`Delete security group ${g.group}`}
                  onClick={() => {
                    remove.mutate({ group: g.group })
                    if (selected === g.group) onSelect(null)
                  }}
                  className="ml-1">
                  <Icon name="delete" size={16} />
                </Button>
              )}
            </li>
          ))}
        </ul>
        )}
      </QueryState>

      {canEdit && !adding && (
        <Button className="mt-3" onClick={() => setAdding(true)}>Add group</Button>
      )}
      {canEdit && adding && (
        <form onSubmit={submit} className="mt-3 flex flex-col gap-3 rounded-ctl border border-line-soft bg-elev p-3">
          <div>
            <label className={label} htmlFor={nameId}>Name</label>
            <input id={nameId} className={input} value={name}
              onChange={e => setName(e.target.value)} />
          </div>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" onClick={() => setAdding(false)}>Cancel</Button>
            <Button type="submit" disabled={create.isPending}>
              {create.isPending ? 'Saving...' : 'Save group'}
            </Button>
          </div>
        </form>
      )}
    </div>
  )
}
