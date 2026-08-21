# Firewall management

Design, 2026-08-21. Every PVE fact below was measured on the lab cluster
(node1/node2, pve-manager 9.2.11) on the day of writing, not recalled. The probe
created one rule at each of three scopes and deleted all three; the cluster was
left with empty rule, group, alias and IPSet lists and unchanged option digests.

## Why this exists, and what it reverses

On 2026-08-18 the per-NIC firewall toggle was removed and no firewall feature was
built. The reasoning, recorded in `api/network.py:155` and `NicForm.tsx:148`, was
that a single boolean could turn filtering ON for a guest while this product had
no way to then permit any traffic. The note said making it safe means rule
management, and that rule management was a feature to scope deliberately.

This is that feature. The toggle comes back as part of it, because it has to: a
guest's rules do nothing unless both the guest's `enable` option and the NIC's
`firewall=1` flag are set, so shipping rule editing while the flag stays
unmanageable would ship a rule table that silently has no effect.

Those two code comments state a rule the code will contradict once this lands.
Rewriting them is part of the work, not follow-up. Files under `docs/` are not
touched.

## What PVE actually offers

The rule schema is identical at every scope:

`type` (in, out, forward, group), `action` (ACCEPT, DROP, REJECT, or a security
group name), `macro`, `iface`, `source`, `dest`, `sport`, `dport`, `proto`,
`enable` (integer, not boolean), `log`, `icmp-type`, `comment`, `pos`, `digest`.

| Object | Cluster | Node | Guest |
|---|:--:|:--:|:--:|
| rules, reorder via `moveto` | yes | yes | yes |
| options | yes | yes | yes |
| aliases | yes | no | yes |
| IPSets and their members | yes | no | yes |
| security groups | yes | no | no |
| macros, read only, about 90 with descriptions | yes | no | no |
| refs, alias and IPSet names for pickers | yes | no | yes |
| log | no | yes | yes |

Options differ by scope. Cluster carries `enable`, `policy_in`, `policy_out`,
`policy_forward`, `ebtables`, `log_ratelimit`. Node carries `enable`, log levels,
conntrack tuning, `nosmurfs`, `tcpflags`, and `nftables`. Guest carries `enable`,
`policy_in`, `policy_out`, `dhcp`, `ndp`, `radv`, `macfilter`, `ipfilter` and log
levels.

**A security group is a rule list.** `GET /cluster/firewall/groups/{group}` is
documented by PVE itself as "List rules", and POST to the same path is "Create
new rule" with the schema above. So groups are a fourth rule scope rather than a
new kind of object, and the rule table and rule form serve all four.

**What PVE does not offer.** There is no dry run: nothing can tell an operator in
advance that a rule will lock them out. Macros expose a name and a description
but not the ports they expand to. There is no cluster level log.

## Credentials

The narrow `lifecycle` token wrote rules at guest, node and cluster scope
successfully, and returned 403 on every read: `(/vms/100, VM.Audit)`,
`(/nodes/node1, Sys.Audit)`, `(/, Sys.Audit)`.

That is the split `api/network.py:239` already records for guest NIC edits. Reads
go through the `monitoring` client, writes through `lifecycle`. No new capability,
no new PVE role, no host re-enrolment, and no change to `services/pveum.py`.

## API surface

One router, `api/firewall.py`, mounted at `/api/v1/firewall`, with the scope as a
path segment so one set of handlers serves all four.

```
GET/POST/PUT/DELETE  /firewall/{scope}/rules[/{pos}]
PUT                  /firewall/{scope}/rules/{pos}/move
GET/PUT              /firewall/{scope}/options
GET/POST             /firewall/{scope}/aliases                 cluster, guest
GET/PUT/DELETE       /firewall/{scope}/aliases/{name}
GET/POST             /firewall/{scope}/ipsets                  cluster, guest
DELETE               /firewall/{scope}/ipsets/{name}           ?force= drops members
GET/POST             /firewall/{scope}/ipsets/{name}/members
PUT/DELETE           /firewall/{scope}/ipsets/{name}/members/{cidr}
GET/POST             /firewall/groups                          cluster only
DELETE               /firewall/groups/{group}
GET                  /firewall/{scope}/log                     node, guest
GET                  /firewall/refs
```

`scope` is one of `cluster`, `node`, `guest`, `group`. The target arrives as a
query parameter, the way `/network/bridges` already takes `host`: `?host=` for
cluster, `?host=&node=` for node, `?target=app:12` or `?target=vm:108` for guest,
`?host=&group=web` for a security group. Guest scope resolves its node through
`guest_node()`, which exists because a guest does not always run on its host's own
node.

## Architecture decisions

**Live passthrough. No model, no migration, no poller.** Same as
`/network/bridges`, whose docstring already describes this shape. Firewall rules
are configuration rather than telemetry, they change rarely, and reading them per
guest on a schedule would break the O(nodes) call budget the poller works to.
Rules load when a page asks for them.

**Direct calls, not jobs.** Every firewall write in the probe returned `null`
rather than a UPID, so there is no PVE task to follow. This is the same call shape
as `set_guest_nic`, which is already documented as deliberately not a job.

**`digest` is round-tripped on every write.** PVE returns one on every read of
every object and accepts one on every write. The frontend carries it back, so two
operators editing one ruleset get a clean conflict instead of one silently
overwriting the other. This is the only place the feature could quietly lose
someone's work, and PVE hands us the fix for free.

**Cluster scope dedupes by `cluster_name`.** Two Host rows can be the same
physical cluster, which is why `dedupe_vms` exists. One cluster's firewall appears
once, not once per enrolled host.

**Reorder through `moveto`.** PVE models rule order as an integer and takes
`moveto` on the rule PUT. Move up and move down, no drag and drop dependency.

**The log is a line cursor, not a stream.** `GET .../firewall/log` takes `start`
and `limit` for paging and `since` and `until` as UNIX epoch bounds, and returns
`{n, t}` rows where `n` is the line number and `t` the text. That is the same
shape `ProxmoxClient.task_log` already reads and `JobLog` already renders, so the
log tab reuses both rather than introducing a second way to page remote output.

### Two traps, recorded before they are hit

`icmp-type` contains a hyphen, so it cannot be passed as a Python keyword
argument. It has to go through `**{"icmp-type": value}`. This fails at runtime,
not at type check.

An IPSet member's CIDR sits in the URL path, so its `/` must be percent encoded
(`10.0.0.0%2F8`, confirmed in the path schema). Missing this is a 404 on every
member read, update and delete.

## Frontend

An eleventh sidebar entry, Firewall, in the Infrastructure group after Network.
`nav.test.tsx` asserts exactly ten pages today; it guards the rule that the nav is
never reshaped by tier, config or entitlement, which a permanent new page does not
violate, but the edit is deliberate and belongs in this change.

Child routes, the pattern `nodeDetailTree` already uses:

- `/firewall` cluster: Rules, Security groups, Aliases, IPSets, Options
- `/firewall/node/$node`: Rules, Options, Log
- `/firewall/guest/$target`: Rules, Aliases, IPSets, Options, Log

A scope switcher sits above the tabs. Routes are deep linkable because the guest
view is reached by a link from another page.

One rule table and one rule form serve all four scopes. The form mirrors the split
Proxmox uses: direction, action, protocol, source, destination, ports and comment
visible, with macro, interface, log level and icmp-type behind Advanced. Source,
destination and action offer pickers fed by `/firewall/refs` and the security group
list.

The guest surface is a route rather than a dialog because it carries five tabs.
`AppDetailPanel` also carries a measured warning that widening it pushes the Apps
table's own columns off the right edge, so a rule table does not belong inline
there either.

Apps and VMs gain a Firewall action on the row action bar that opens the guest
route, and one line of effective state in the expanded panel saying whether
filtering is on and how many rules there are.

`NicForm` gets its firewall toggle back, replacing the paragraph that currently
explains its absence.

### Enabling a firewall

Proxploy warns and never blocks, matching what Proxmox itself allows.

The warning is shown in place at the moment of enabling and says what will
actually happen: which default input and output policy will apply, and how many
enabled allow rules would survive it. A generic confirmation prompt would not
carry that, and the whole objection in the 2026-08-18 note was that nobody could
state what the control would do without going to check the default policy first.

## Plumbing

Entitlement keys, added to `FLAG_KEYS`: `firewall.view`, `firewall.rules`,
`firewall.options`, `firewall.objects`, `firewall.log`.

RBAC: `authorize("firewall", "read")` and `authorize("firewall", "manage")`, with
`scope_host()` where a host id is in the path. The read singleton goes first in
`dependencies=[...]` and is reused as the parameter dependency, per the `deps.py`
idiom that `test_route_auth_invariant.py` enforces.

Audit: `write_audit` on every mutation, with a target named the way a person would
say it, following `set_guest_nic`'s example of naming both the object and the
thing it belongs to.

## Testing

Backend, against a faked client: rule create, read, update, delete and reorder at
all four scopes; alias, IPSet, IPSet member and security group lifecycles; the
digest conflict path; the monitoring and lifecycle client split; and both traps
above.

Frontend: the rule table, the rule form including the Advanced section, the refs
pickers, the effective state line, and the nav test moving to eleven pages.

Hardware: one rule at each of the four scopes on the lab, plus one alias, one
IPSet with a member, and one security group. The 403 read and write split is
exactly the class of problem a fake hides, so it has to be checked against real
tokens.

## Deferred

`nftables`, which PVE 9.2.11 still labels a tech preview.
