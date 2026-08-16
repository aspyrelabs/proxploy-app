# Cluster peer auto enrolment: implementation plan

> Status: plan only, nothing is built yet. Written 2026-08-16 for review
> before any code is written, because this touches host enrolment and where
> stored credentials are copied to. The five questions this plan opened have
> since been answered, and the answers are folded in throughout. Section 11
> records them.
>
> Background reading, already done: `docs/drafts/cluster-wide-api-tokens.md`
> (a Proxmox API token is cluster wide because `/etc/pve` is replicated, while
> Proxploy stores credentials per host), commit `1e86dd7` (cluster membership
> shown on the node overview), commit `72dd212` (a token could land in the
> wrong capability slot).

## 1. The problem, in one paragraph

A Proxmox API token created on one node of a cluster already exists on every
node of that cluster. Proxploy stores credentials per host row, so enrolling
the second node of a cluster leaves it reporting every capability as not
configured, and the operator goes looking for a bug that is not there. Today
the operator adds each node by hand and pastes the same four token pairs
again on each. The goal is that adding one node of a cluster offers to add
its peers, and that a token stored on one host can reach the others, so the
work is once per cluster instead of once per node.

## 2. What exists today

### 2.1 Enrolment

`backend/proxploy/api/hosts.py`:

- `POST /hosts/probe` (`probe`, admin, no host id yet). Builds a
  `ProxmoxClient` from the request body and calls `version()`, then reports
  `missing_privileges` and `node_power_missing`.
- `POST /hosts` (`create_host`, admin). Gates on the `hosts.multi`
  entitlement once one host exists, refuses a duplicate name, calls
  `version()`, records the privilege gaps, calls `cluster_identity(client)`
  for `(node_name, cluster_name)`, writes the `Host` row, then always writes
  one `HostCredential` with `kind="api_token:monitoring"`. SSH enrolment is
  an explicit opt in on the same call and needs `ssh_consent: true`.
- `POST /hosts/{id}/credentials` (`rotate_credentials`, owner). Verifies the
  new token against `h.address` with `version()` **before** it replaces
  anything, refuses an unnamed capability once a monitoring token exists
  (the `72dd212` fix), writes `api_token:<capability>`, and audits
  `host.credentials` with the capability named.
- `PATCH /hosts/{id}` can change name and address. `POST /hosts/{id}/test`
  re-probes. `DELETE /hosts/{id}` audits which credential kinds went away.

Capabilities are `monitoring`, `lifecycle`, `console`, `backup`, declared
once in `backend/proxploy/services/pveum.py::CAPABILITIES` and surfaced by
`GET /hosts/capabilities`. `_capability_state()` reports presence only.

### 2.2 Cluster membership detection

`backend/proxploy/services/hostclient.py::cluster_identity(client)` calls
`client.cluster_status()` and returns `(node_name, cluster_name)`. It is the
only honest source: `/cluster/status` marks the node you are talking to with
`local: 1`, and carries the cluster name in its `{"type": "cluster"}` row. A
standalone node returns one node row and no cluster row, so `cluster_name`
is `None`, which means standalone and not unknown.

Callers: `create_host` (wrapped in `try/except ProxmoxError` so a probe
hiccup cannot block enrolment), and the poll loop
(`backend/proxploy/pollers/__init__.py` around line 544), which refreshes
`cluster_name` every cycle. Commit `1e86dd7` added the frontend side, reading
the cluster off the poller snapshot in
`frontend/src/components/NodeIdentityRail.tsx`.

Note the gap the poll loop leaves: it writes `cluster_name` and throws the
node name away (`_, cluster_name = cluster_identity(client)`), so
`hosts.node_name` is only ever written at enrolment. A node renamed in PVE
keeps its old name in Proxploy forever. Phase 1 below fixes that, because
the skip rule depends on `node_name` being current.

### 2.3 What Proxmox gives us about peers

`GET /cluster/status` returns one row per node:

```json
{"type": "node", "name": "node2", "nodeid": 2, "ip": "10.0.0.6",
 "level": "", "local": 0, "online": 1, "id": "node/node2"}
```

`ip` is the corosync link address. It is the only address Proxmox hands us
for a peer, and on every normal install it is also the address the API
answers on. `GET /nodes` lists node names with no addresses at all, so
`/cluster/status` is the only usable discovery source, and the codebase
already calls it (`ProxmoxClient.cluster_status`, used by
`cluster_identity` and by `services/migrate.py::preflight`).

A peer address is therefore built as `https://{ip}:8006`, matching the
`https://10.0.0.5:8006` shape `Host.address` already holds.

### 2.4 TLS and the SSRF guard

`Host.tls_fingerprint` exists and `ProxmoxClient._connect` checks it, but
only when `verify_tls` is false. `HostForm` never collects a fingerprint and
defaults `verify_tls` to false, so in practice hosts today are enrolled with
neither verification nor a pin. `tls_fingerprint_sha256(host, port)` in
`services/proxmox.py` fetches a peer's own fingerprint over a validated
socket.

Two facts that decision 1 below depends on. First, a stored pin is only
enforced while `verify_tls` is false, which is the normal case for a stock
Proxmox node serving a self signed certificate, so pinning is what actually
gives these connections any integrity at all today. Second, nothing in the
product can currently change a stored pin: `HostPatchIn` does not accept
`tls_fingerprint` and no dialog offers it. Pinning without a way to re-pin
would turn a routine certificate renewal into a host row nobody can fix from
the UI, so the recovery path ships in the same phase as the pinning.

Every outbound connection already passes `resolve_target()`, which refuses
link local, loopback (unless opted in), unspecified, multicast and reserved
addresses. That guard matters more here than anywhere else, because the peer
address comes from the node rather than from the operator. It runs
unchanged, so a node reporting `169.254.169.254` as a peer is refused by the
code that already exists. No new guard is needed.

### 2.5 Frontend

- `frontend/src/components/HostForm.tsx`: name, address, verify TLS, SSH
  enrolment, the setup script panel, the monitoring token pair plus one pair
  per ticked capability. On submit it creates the host, then posts each
  capability token to `POST /hosts/{id}/credentials` one at a time, and
  holds `onCreated` back while any capability was rejected so the operator
  can retry or continue. Rendered by `frontend/src/routes/settings.tsx`
  (Add host) and `frontend/src/routes/onboarding.tsx` (the wizard advances
  on `onCreated`).
- `frontend/src/components/HostEditDialog.tsx`: name, address, capability
  tokens (via `HostCapabilityList`), the script panel and SSH key
  regeneration. Opened from the Settings hosts row and from
  `HostActionsMenu` on the node page.
- `frontend/src/components/HostCapabilityList.tsx`: one row per capability,
  Add or Rotate, posting to `POST /hosts/{id}/credentials` with the
  capability always named.
- `frontend/src/api/hosts.ts`: the shared query hooks and types.
  `GET /hosts` currently returns `node_name` but not `cluster_name`.

## 3. The end to end flow

1. The operator adds a host exactly as today. Nothing about that step
   changes.
2. `POST /hosts` returns, capability tokens are stored as today.
3. `HostForm` calls `GET /hosts/{id}/peers`. That one call probes every peer
   before it answers, so while it is in flight the panel shows a single
   loading ring reading "Checking the other nodes of cluster lab-cluster" (the
   existing `Loading` component `HostForm` already uses for its own two
   calls). There is no half filled list and no row that changes state under
   the operator's cursor. On a standalone node the call returns an empty
   list and the flow ends exactly where it ends today.
4. On a cluster, a panel appears below the form:

   > node1 is part of cluster lab-cluster. Proxploy found 2 other nodes in it.
   > A Proxmox API token is shared across the whole cluster, so the tokens
   > you just entered will work on these nodes too. Each node you tick is
   > added as its own host and gets its own copy of the tokens.

   Directly under that, before the checkboxes, the team the peers will land
   in, so it is read before anything is ticked rather than discovered in
   the hosts table afterwards:

   > These nodes will join the same team as node1: Platform.

   and when the origin host has no team:

   > node1 is not in a team, so these nodes will not be in one either. You
   > can assign them in Settings afterwards.

   One checkbox per peer, all pre ticked, each showing the node name, the
   address Proxmox reported, and the TLS fingerprint that node presented.
   A peer already in Proxploy is shown unticked and disabled with the host
   name it is already known by. A peer that did not answer is shown unticked
   and disabled with the reason and no fingerprint, for example:

   > node3, 10.0.0.7. Did not answer on port 8006, so it cannot be added
   > yet. Add it from its own Edit dialog once it is back.

   When the `hosts.multi` entitlement is off, the panel names the peers it
   found and says adding more than one host needs a paid tier, with no
   checkboxes at all, rather than offering ticks that would every one of
   them fail on confirm.
5. The operator unticks anything they do not want and presses **Add these
   nodes**, or presses **Skip**. Nothing is added by either the discovery
   call or by leaving the page.
6. `POST /hosts/{id}/peers` with the ticked node names. Each peer is
   fingerprinted, has each token verified against it, and is then added as
   its own host, carrying the origin's `team_id` and its own copy of every
   capability token that verified.
7. The panel reports one line per peer: added with which tokens and into
   which team, added but with a named token rejected, or not added and why.
8. `onCreated` fires once the operator presses Continue, so onboarding
   advances after the peer step rather than before it.

For hosts enrolled before this ships, the same panel appears in
`HostEditDialog`, so no one has to remove and re-add a host to get the
offer.

## 4. Backend changes

Two new routes on the existing router, both scoped to the origin host. No
new module, no new service, no new table.

### 4.1 `GET /hosts/{host_id}/peers`

Dependency: `_manage` (admin, host scoped). It reveals node names, addresses
and fingerprints, which is the same class of information `POST /hosts/probe`
already returns to an admin, and it stores nothing.

```json
{
  "cluster": "lab-cluster",
  "capabilities_to_copy": ["monitoring", "lifecycle"],
  "multi_host_entitled": true,
  "team": {"id": 2, "name": "Platform"},
  "peers": [
    {"node": "node2", "address": "https://10.0.0.6:8006", "online": true,
     "reachable": true, "tls_fingerprint": "AB:CD:...:9F",
     "already_enrolled_as": null, "error": null},
    {"node": "node3", "address": "https://10.0.0.7:8006", "online": true,
     "reachable": false, "tls_fingerprint": null,
     "already_enrolled_as": null,
     "error": {"kind": "unreachable",
               "detail": "node3 at 10.0.0.7 did not answer on port 8006."}}
  ]
}
```

Work:

1. `client_for_host(request.app, db, h)` for the monitoring client. That
   helper already exists and already defaults to monitoring, which is the
   one capability every host is guaranteed to have.
2. `client.cluster_status()`. Anything other than a clean read is a 502 with
   the usual `{"error": kind, "detail": ...}` body, the same shape every
   other route here returns.
3. Rows with `type == "node"` and no `local` flag are the peers. No cluster
   row means standalone, and the response is `{"cluster": null, "peers": []}`.
4. For each peer: build the address, apply the skip rules (section 6.4),
   then call `tls_fingerprint_sha256(hostname, port)` and
   `ProxmoxClient(address, <origin monitoring token>, ...).version()`. A
   failure of either is recorded on the row and never raised, because one
   dead node must not hide the two live ones.
5. `capabilities_to_copy` is the origin host's own `api_token:*` credential
   kinds, so the panel can say what will be copied. `ssh_key` is not in that
   list and never will be.
6. `multi_host_entitled` mirrors the `hosts.multi` check `create_host` makes,
   so the panel can say that adding more hosts needs a paid tier instead of
   offering checkboxes that would all fail.
7. `team` is the origin host's team, id and name, or `null` when the origin
   is in no team. It is here so the panel can name the team the peers will
   join before anything is ticked, rather than leaving inheritance to be
   inferred. The name comes from the `Team` row the origin's `team_id`
   already points at, one `db.get(Team, ...)`, not a second request from
   the frontend.

Every peer is probed before the response returns (decision 5), so the
frontend never has to render a row whose reachability or fingerprint is
still unknown. The cost is one TLS handshake and one `/version` per peer on
a click, which is a handful of calls, not a poll loop, so it runs in request
like `POST /hosts/{id}/test` already does. A three node cluster costs four
short calls. If a cluster ever gets big enough for that to feel slow, the
row by row alternative is a later change to this one route and its hook, not
a different design.

### 4.2 `POST /hosts/{host_id}/peers`

Dependency: `_credentials` (owner, host scoped). This copies stored secrets
into new rows, which is the same severity class as rotating them.

Body: `{"nodes": ["node2", "node3"]}`. Node names only. The caller never
supplies an address, so a compromised or confused client cannot aim the
enrolment at a machine the cluster did not name.

Response, always `200` when the origin host exists and the body parses:

```json
{"results": [
  {"node": "node2", "status": "enrolled", "host_id": 4,
   "address": "https://10.0.0.6:8006",
   "capabilities_stored": ["monitoring", "lifecycle"],
   "capabilities_failed": [],
   "detail": null},
  {"node": "node3", "status": "failed", "host_id": null,
   "address": "https://10.0.0.7:8006",
   "capabilities_stored": [], "capabilities_failed": [],
   "detail": "node3 at 10.0.0.7 did not answer on port 8006, so it was not added. Nothing was stored."}
]}
```

Failures are rows, not status codes, for the same reason `HostForm` already
treats one rejected capability token as that capability's failure and not
the enrolment's: a 502 for the whole request would throw away the record of
the peers that did work. The only whole request failures are `404` (origin
host gone), `403` (`hosts.multi` not entitled, same body shape
`create_host` uses) and `422` (empty `nodes` list).

Per peer, in order:

1. Re-read `/cluster/status` from the origin host once for the whole
   request. A requested node that is not in it now is a per peer failure,
   not a 500.
2. Re-apply the skip rules. Discovery and confirm can be minutes apart.
3. `tls_fingerprint_sha256(hostname, port)` for this peer's own
   fingerprint, which is stored as that peer's pin. Never the origin's.
   Before the loop, the origin host is pinned the same way if it has no pin
   yet: same helper, same code path, so two hosts in one cluster never
   disagree about whether they are pinned (decision 1).
4. Verify the monitoring token against the peer with
   `ProxmoxClient(peer_address, ...).version()`. A failure here ends this
   peer with nothing written, because a host with no monitoring credential
   cannot poll and monitoring is the mandatory capability.
5. Create the `Host` row: `name` = the Proxmox node name, `address` = the
   peer address, `verify_tls` copied from the origin, `tls_fingerprint` =
   the fingerprint probed in step 3, `node_name` = the peer node name,
   `cluster_name` = the
   origin's cluster name, `status="connected"`, `pve_version` from the
   `version()` call already made, plus `_missing_privileges` and
   `_node_power_missing` through the existing `_privilege_note` helper, so a
   peer with a narrower token reports the same sentence a hand added host
   would. `team_id` copied from the origin (decision 3), so a cluster is
   never half inside a team and half outside it.
6. Copy the monitoring credential. The origin's `encrypted_blob`,
   `key_version` and `public_meta` are copied as they are. Same secret
   store, same key version, so there is nothing to decrypt and re-encrypt.
7. For every other `api_token:<capability>` on the origin: decrypt, verify
   against the peer with `version()`, then write. A rejection records the
   capability and its reason on the result row and moves to the next one.
   The host stays enrolled and working for everything that did verify.
8. Audit. `host.create` per enrolled peer with
   `{"name", "address", "node", "via_host_id", "via_node"}`, and
   `host.credentials` per copied capability with
   `{"capability", "copied_from_host_id"}`. Reusing the two existing action
   names keeps the audit filters, the activity feed labels in
   `frontend/src/lib/activityDisplay.ts` and the existing tests working with
   no new label to register.

Nothing here is a job. It is a handful of HTTP calls on an explicit click,
the same shape as `POST /hosts/{id}/test` and `services/migrate.py`'s in
request preflight. A job queue for it would buy nothing and cost a progress
UI.

### 4.3 Small changes elsewhere

- `list_hosts` (`GET /hosts`) gains `cluster_name` in its row dict. The
  frontend needs it to work out which enrolled hosts are siblings, and it is
  already on the model and already returned by `POST /hosts`.
- `create_host` pins the fingerprint of the host being added when none was
  supplied, using the same `tls_fingerprint_sha256` call. Decision 1 is
  "always pin on first use", and first use of a host is its enrolment. One
  line, and it means a standalone host is pinned on the same terms as a
  clustered one instead of only clusters getting the protection.
- `HostPatchIn` accepts `tls_fingerprint: str | None`, and
  `POST /hosts/{id}/test` returns `tls_fingerprint_seen`, the fingerprint
  the node is presenting right now. Together those are the re-pin path a
  deliberate certificate change needs. Reusing `PATCH` and `test`, which the
  Edit dialog already calls, avoids a bespoke re-pin route. Setting it to
  null clears the pin, which is the escape hatch for an operator who wants
  out of pinning entirely.

## 5. Token propagation to peers already enrolled

The requirement is that a capability token stored on one host reaches the
others. After enrolment that needs no new backend code at all.

`POST /hosts/{id}/credentials` already does exactly the right thing for one
host: it verifies the token against that host before it stores anything, it
insists on the capability being named, and it audits which slot it wrote. To
give three peers the same token, call it three times.

So propagation is a frontend loop over sibling hosts, and it is offered
rather than automatic (decision 4), consistent with the rule that adding
trust never happens as a side effect.

**Consent before the save, not a prompt after it.** In
`HostCapabilityList`, when the host has a `cluster_name` and other enrolled
hosts share it, the open token form shows one extra checkbox above Save,
pre ticked, naming the nodes:

> Also store this on the other nodes of cluster lab-cluster: node2, node3.
> A Proxmox API token works across the whole cluster, so the same token is
> verified against each node before it is stored there.

One press of Save then writes the origin and the ticked peers together.
Nothing is asked again afterwards, and the secret is not held in component
state waiting for a second decision.

**Ordering: the origin is written first, and a peer failure never undoes
it.** Save posts to the origin host, and only if that succeeds does it post
the same body to each ticked peer, each with `capability` named (required
both by the backend and by
`frontend/src/tests/credential-post-names-capability.test.ts`, which walks
the source for exactly this mistake). If the origin write is refused,
nothing is sent to any peer, because a token the origin will not take is not
a token worth spreading. If a peer refuses it, the origin keeps what it just
stored. That ordering is the one that cannot leave the operator worse off
than before they pressed Save: every outcome either adds a working token or
changes nothing, and there is no path where a peer's refusal takes away
something that was working. It is also the only honest option, since nothing
in the product deletes a single credential.

**What the operator is told when the origin takes it and a peer does not.**
Per node, under the row:

> Lifecycle token stored on node1. node2 refused the same token, so
> Lifecycle is still not configured there. node1 keeps the token you just
> saved. Check that the token exists on node2 and that its permissions
> cover it, then add it from node2's Edit dialog.

Success is as plain: "Lifecycle token stored on node1, node2 and node3."

Deliberately not built: a `propagate_to_peers` flag on the credentials
route, a fan out endpoint, and any background reconciliation that keeps
tokens in step forever. All three are more code than a loop over hosts the
client already has in cache, and the fan out endpoint would need to
re-invent the per host verify and audit that the existing route already does
correctly.

## 6. Failure and edge cases

### 6.1 Unreachable peer

Discovery marks it `reachable: false` with the reason, unticked and
disabled. If it goes down between discovery and confirm, the confirm result
row says:

> node3 at 10.0.0.7 did not answer on port 8006, so it was not added.
> Nothing was stored.

### 6.2 TLS fingerprint

Pin on first use, always (decision 1). Each peer is fingerprinted on its own
address and stores its own pin. A peer never inherits the origin's, because
cluster nodes serve distinct certificates. The fingerprint is shown in the
checkbox list so the operator can see which certificate each machine
presents before ticking it. `verify_tls` is still copied from the origin,
and the pin is enforced while that is false, which is the normal case.

The origin host is pinned by the same code path when it has no pin yet, both
at its own enrolment (section 4.3) and again as the first step of a peer
enrolment for hosts that predate this. Without that, one cluster would hold
pinned peers and an unpinned origin, which is the sort of disagreement
nobody reasons about correctly at 3am.

**If the fingerprint changes between discovery and confirm**, the confirm
result row says:

> node2 is presenting a different TLS certificate than the one shown a
> moment ago, so it was not added. Nothing was stored. If you did not just
> replace its certificate, stop and investigate.

**If a stored pin stops matching later**, which is what a certificate
renewal looks like, `ProxmoxClient._connect` raises `ProxmoxError` with
`kind="tls_fingerprint"` before any request is sent. That is existing
behaviour and it reaches the operator through paths that already exist: the
poll loop marks the host unreachable and writes the reason into
`hosts.last_error`, `POST /hosts/{id}/test` returns the same 502 kind, and
`HostForm`'s `KIND_COPY` already has the sentence for it. What is new is the
way out, and it must be, because pinning with no way to re-pin would strand
the host row. In the Edit dialog:

> node2's TLS certificate has changed. Proxploy pinned AB:CD:...:9F when the
> host was added, and node2 is now presenting 12:34:...:EF. Proxploy will
> not connect until you say which is right. If you renewed the certificate,
> accept the new one. If you did not, do not accept it, and find out why it
> changed.

Accepting is a `PATCH /hosts/{id}` carrying the new fingerprint. The
comparison uses `tls_fingerprint_seen` from `POST /hosts/{id}/test`, which
the dialog already calls. Both fingerprints are shown in full so the
operator can compare them against the node itself. Nothing re-pins on its
own, because a pin that silently follows whatever the node presents is not a
pin.

### 6.3 Token rejected on a peer

Two different outcomes, deliberately:

- Monitoring rejected: nothing is written, the peer is not added.

  > node2 refused the monitoring token, so it was not added. Nothing was
  > stored. Check that the token exists on that node and that its
  > permissions cover it.

- Another capability rejected: the peer is added and works, that one
  capability is left unconfigured.

  > node2 was added. Proxmox on node2 refused the lifecycle token, so
  > Lifecycle is not configured there. Everything else was stored. Add it
  > later from node2's Edit dialog.

That split mirrors what `HostForm` already does per capability on a single
host, so the operator sees one behaviour, not two.

### 6.4 Peer already enrolled, including under a different address

The skip rule matches on cluster plus node name, never on address, so a peer
enrolled under a second address or a DNS name is still recognised:

- Skip when an existing host has `cluster_name == <origin cluster>` and
  `node_name == <peer name>`.
- Also skip when `node_name` matches and the existing host's `cluster_name`
  is `NULL`. Null there means a row from before cluster detection, or a
  transient probe failure the poller will fix on the next cycle. Adding the
  same machine twice is the worse failure of the two.

Two rules, and there was nearly a third: skip when an existing host's
address resolves to the same hostname as the peer's. It is cut. The two
rules above plus phase 1's refresh of `node_name` already cover the rename
case it was there for, and resolving an address inside discovery means a DNS
lookup per enrolled host on a path that has to stay fast and predictable,
plus a new way for discovery to fail or hang that has nothing to do with
Proxmox. Adding the rule back later is a few lines. Unpicking a discovery
call that has become slow, after operators have learned to expect the delay,
is not.

Skipped peers are shown, not hidden:

> node2 is already in Proxploy as pve-02.

### 6.5 Name clash with an unrelated host

The peer takes the Proxmox node name as its Proxploy host name, unchanged
(decision 2). The skip rules above have already excluded the same machine,
so a remaining clash on `hosts.name`, which is unique, is a different
machine wearing the name. That one peer fails, the rest of the ticked peers
still enrol, and the row reads:

> node2 was not added: Proxploy already has a different host called node2,
> at https://10.9.9.9:8006. Nothing was stored. Rename that host, then add
> this node again.

It names the clashing name and the host it clashed with, so the operator can
go straight to the row they need to rename. No generated `node2-2` suffix: a
host silently wearing a name that is not its node name is worse than a
sentence telling the operator what to do.

### 6.6 Single node cluster and standalone

A standalone node's `/cluster/status` has one node row and no cluster row.
A single node cluster has a cluster row and one node row, which is itself.
Both produce an empty peer list and no panel. The add host flow is then
byte for byte what it is today, which is what the frontend tests for the
existing flow will keep pinning.

### 6.7 Node renamed in PVE

Today `hosts.node_name` is written only at enrolment, so a rename makes an
already enrolled node look like a new peer forever. Phase 1 makes the poll
loop write `node_name` alongside the `cluster_name` it already writes, which
it has in hand and currently discards.

That leaves a window rather than a hole, and here is exactly what it is.
Between a node being renamed in PVE and the next poll cycle writing the new
name, discovery does not recognise the machine and offers it as a new peer.
Tick it and Proxploy gets a second host row, under the new node name,
pointing at the same address as the old one. Nothing breaks and nothing is
destroyed, but the node is polled twice and appears twice in the hosts
table until the operator removes one of the rows.

The window is one poll cycle: 30 seconds by default
(`settings.poll_interval_s`), stretching to at most 5 minutes
(`POLL_BACKOFF_CAP_S`) for a host the poller is currently backing off from
after repeated failures. Hitting it means renaming a node in PVE and opening
the peer panel inside the same half minute.

The window is accepted, decided on 2026-08-16. Two skip rules and the
poller refresh are the whole defence, and 30 seconds of exposure to a
duplicate row the operator can delete does not justify a third rule. If
someone does hit it, the cheap close is not the DNS rule cut above: it is
comparing `urlparse(existing.address).hostname` against the peer's address
as plain strings, no resolution and no lookup, which catches the normal case
where a host was enrolled by the same IP the cluster reports. That is a
couple of lines to add later, on evidence, rather than now on speculation.

### 6.8 A node that has left the cluster

Its `/etc/pve` no longer replicates from the origin, so its copy of the
token can diverge. It shows up as a token rejection with the node named,
which is the honest report. Nothing special to build.

## 7. Test plan, tests first

### Backend

New file `backend/tests/test_hosts_peers.py`. It needs one fake PVE per
address, which `make_addressed_factory` in `backend/tests/fakes/pve.py`
already provides for the two host migration tests, and the two node
`cluster_status_rows` shape is already written out in
`backend/tests/test_hosts_lifecycle.py::test_enrolment_picks_the_local_node_out_of_a_cluster`.
A new file rather than growing `test_hosts.py`, because this is a new route
group with its own fake wiring, which is the same reason
`test_hosts_capabilities.py` and `test_hosts_privileges.py` are separate.

1. discovery lists the peer and never the local node.
2. discovery on a standalone node returns no cluster and no peers.
3. discovery marks an already enrolled peer, matched on cluster plus node
   name, even when that host's address is different.
4. discovery reports an unreachable peer with a reason instead of dropping
   it or failing the whole call.
5. discovery reports the origin's team as an id and a name, and `null` when
   the origin is in no team.
6. enrolling copies every `api_token:*` the origin holds, and each one is
   verified against the peer before it is written.
7. a peer that refuses the monitoring token leaves no host row and no
   credential row.
8. a peer that refuses the lifecycle token is still enrolled, has monitoring
   stored, has no lifecycle row, and the response names lifecycle.
9. one failing peer does not stop another peer in the same request from
   enrolling.
10. the enrolled peer stores its own fingerprint and never the origin's.
11. an origin host with no pin gets one from its own address before the
    peers are enrolled, and an origin that already has a pin keeps it.
12. a peer whose name clashes with an unrelated existing host fails with the
    clash named, and the other ticked peer in the same request still
    enrols.
13. a host enrolled through `POST /hosts` with no fingerprint supplied is
    pinned from its own address.
14. a stored pin that no longer matches is a `tls_fingerprint` failure and
    never a silent connection, and `POST /hosts/{id}/test` reports the
    fingerprint currently presented.
15. `PATCH /hosts/{id}` re-pins to a supplied fingerprint and clears the pin
    when given null.
16. the enrolled peer carries the origin's `team_id`, and a peer of a
    teamless origin is left in no team rather than in some default one.
17. no `ssh_key` credential is copied, `node_shell_enabled` is false and
    `install_consent_at` is null on the new host.
18. `host.create` audit names the origin host, and one `host.credentials`
    audit per copied capability names the capability.
19. a node name that is not in the current cluster status is a per peer
    failure, and no request field can supply an address.
20. enrolment is refused with `hosts.multi` disabled, with the same body
    `create_host` returns, and discovery reports
    `multi_host_entitled: false` rather than failing.
21. discovery needs admin, enrolment needs owner.

Extend `backend/tests/test_poller_ingest.py` for phase 1: a cycle refreshes
`node_name`, so a node renamed in PVE stops looking like a new peer.

`backend/tests/test_openapi_surface.py` covers the new frontend calls
automatically once the routes exist. `docs/05-api-surface.md` gets a row per
route.

### Frontend

New file `frontend/src/tests/host-peer-enrolment.test.tsx`:

1. while the peers request is in flight the panel shows the checking
   message and no checkboxes, so nothing can be ticked before its
   reachability is known.
2. after adding a host whose peers endpoint reports two nodes, both
   checkboxes render pre ticked and `onCreated` has not fired.
3. the panel names the team the peers will join, above the checkboxes and
   before anything is ticked, and says the peers will be in no team when
   the origin is in none.
4. an unreachable peer renders unticked, disabled, with its reason and no
   fingerprint.
5. unticking one and confirming posts only the ticked node name.
6. Skip fires `onCreated` and posts nothing.
7. results render per peer, the enrolled one and the failed one with its
   reason, including the name clash wording.
8. a host with no peers renders no panel and `onCreated` fires as it does
   today.
9. with `hosts.multi` off, the panel names the peers and the tier
   requirement and renders no checkboxes.

Extend:

- `frontend/src/tests/onboarding.test.tsx`: the wizard does not advance past
  the add host step while the peer panel is open.
- `frontend/src/tests/settings-host-tokens.test.tsx`: the propagate checkbox
  is pre ticked and names the peer nodes when a sibling exists, one Save
  posts to the origin and then to each ticked peer with the capability
  named, a refused origin posts to no peer at all, and a refused peer
  leaves the origin's stored token reported as stored.
- `frontend/src/tests/host-edit-dialog.test.tsx`: the panel appears for a
  clustered host and not for a standalone one, and a host whose presented
  fingerprint differs from its pin shows both fingerprints and the accept
  control.
- `frontend/src/tests/credential-post-names-capability.test.ts` needs no
  change and must stay green. The propagation loop is a `/credentials` POST
  carrying a token, so it has to name its capability.

## 8. Phases

Each phase lands on its own and is shippable.

1. **Poller refreshes `node_name`.** Five lines in
   `backend/proxploy/pollers/__init__.py` plus the ingest signature, one
   test. Independent of everything else, and it makes the skip rule honest
   before the skip rule exists.
2. **`GET /hosts/{id}/peers`.** Discovery only, no writes. Visible in
   `/api/docs`, backend tests 1 to 5 and the discovery half of 21. Also adds
   `cluster_name` to `GET /hosts`.
3. **Pin on first use, with its way out.** `create_host` pins when no
   fingerprint was supplied, `PATCH /hosts/{id}` accepts a fingerprint,
   `POST /hosts/{id}/test` reports the one currently presented, and
   `HostEditDialog` gets the compare and accept control. Backend and that
   one control ship together, because a pin with no re-pin path strands the
   host row on the next certificate renewal. Backend tests 13 to 15, and
   the fingerprint case in `host-edit-dialog.test.tsx`. Independent of
   peers entirely: it is worth having on a standalone host.
4. **`POST /hosts/{id}/peers`.** Enrolment: pins the origin if it is still
   unpinned, pins each peer on its own address, copies and verifies each
   token, carries the origin's `team_id` across, applies the skip rules,
   reports partial failure. Backend tests 6 to 12 and 16 to 20.
5. **`PeerEnrolmentPanel` in `HostForm`.** Covers Add host in Settings and
   the onboarding wizard, since both render `HostForm`. New file
   `frontend/src/components/PeerEnrolmentPanel.tsx` and a `useHostPeers`
   hook in `frontend/src/api/hosts.ts`. A separate component rather than
   more JSX in `HostForm` because phase 6 mounts the same panel somewhere
   else.
6. **The same panel in `HostEditDialog`.** Gives hosts enrolled before this
   shipped the same offer, with no new backend work.
7. **Propagation checkbox in `HostCapabilityList`.** Frontend only, using
   the existing per host credentials route.

Phases 1 to 4 are useful on their own to anyone driving the API. Phase 5 is
the point at which an operator sees the feature. Phase 3 grew out of
decision 1: pinning is now unconditional, so the renewal path has to exist
before anything starts pinning, which is why it sits ahead of enrolment
rather than beside it.

## 9. Deliberately not in scope

- **SSH enrolment is never inherited.** The SSH key is a root shell on the
  node, a different trust decision from an API token, and the API asks for
  explicit `ssh_consent` for exactly that reason. A peer is enrolled with no
  `ssh_key` credential. Enabling App Store installs on a peer stays the
  per host flow it is today.
- **Install consent is never inherited.** `install_consent_at` stays null on
  a new peer.
- **Node shell stays per host.** `node_shell_enabled` is false on a new
  peer, same reasoning as the SSH key.
- **No silent additions.** Neither the discovery call nor navigating away
  adds anything. Only the explicit confirm writes.
- **No cluster entity.** No `clusters` table, no cluster page, no cluster
  scoped host group. `cluster_name` on `hosts` plus `cluster_scope()` in
  `backend/proxploy/api/deps.py` already carry every grouping this needs.
- **No background reconciliation.** Nothing watches for peers appearing
  later or for tokens drifting apart. The offer runs when the operator adds
  a host or opens the Edit dialog.
- **No per peer address editing in the checkbox list.** The address comes
  from what the cluster reports. If it is wrong, the address field in the
  Edit dialog already fixes it, and that path is built and tested.
- **No new propagate endpoint.** Section 5.

## 10. Things this plan deliberately kept small

Named here so a reviewer can push back on the omission rather than on the
absence:

- Discovery and enrolment are two handlers in the existing
  `backend/proxploy/api/hosts.py`, not a new `services/peers.py`. The only
  shared logic is the skip rule and the address builder, which are two small
  functions in the same file, next to `_capability_state` and
  `_privilege_note` which are the same kind of thing.
- Credential copying reuses the origin's `encrypted_blob` and `key_version`
  as they are. Same secret store, so a decrypt and re-encrypt round trip
  would change nothing except the number of places a plaintext secret exists.
- Enrolment reuses `_missing_privileges`, `_node_power_missing`,
  `_privilege_note`, `token_public_meta`, `write_audit` and
  `client_for_host` rather than writing a peer specific version of any of
  them.
- Failures are result rows and not exceptions, because the flow is inherently
  partial and the UI has to say which peer.
- Propagation is a client side loop over an existing route.
- The re-pin path is `PATCH /hosts/{id}` plus one extra field on
  `POST /hosts/{id}/test`, both of which the Edit dialog already calls, not
  a dedicated re-pin route with its own audit action.
- Nothing re-pins by itself and nothing retries a failed peer by itself. A
  pin that follows whatever the node presents is not a pin, and a retry the
  operator did not ask for is an addition they did not consent to.

## 11. Decisions taken

Settled with the user on 2026-08-16. No open questions remain, phase 1 can
start.

1. **Pin on first use, always.** Every peer is probed and its own
   fingerprint stored, whatever the origin host has. The origin is pinned
   the same way, at its own enrolment and again as the first step of a peer
   enrolment if it predates this. Consequence accepted and closed in the
   same decision: pinning needs a renewal path, so phase 3 ships the
   compare and accept flow before anything starts pinning. Sections 4.3,
   6.2, phase 3.

   Phase 3 stays ahead of enrolment, reaffirmed. Defer it and the shape of
   the failure is this: enrol three peers, one of them renews its
   certificate, and that host row is dead with no way to fix it from the
   UI, multiplied across every node of the cluster. The feature that makes
   enrolment easy would be the same feature that multiplies an unfixable
   state. Phase 3 is also not dead weight in front of the feature: pinning
   and its renewal path are worth having on a single standalone host, which
   is why it ships as its own phase rather than as a rider on enrolment.
2. **Peer naming is the Proxmox node name, unchanged.** A clash with an
   unrelated host fails that one peer with the clash named, and the other
   ticked peers still enrol. No generated suffix. Section 6.5.
3. **`team_id` is copied from the origin to each peer**, so a cluster is
   never half inside a team. Said out loud in the panel before anything is
   ticked, not left as an implication: discovery returns the origin's team
   and the panel names it. Sections 3 step 4, 4.1, 4.2 step 5.
4. **Propagation is one pre ticked checkbox shown before Save**, naming the
   peer nodes, so a single Save writes the origin and the ticked peers.
   Origin first, and a peer's refusal never undoes the origin write.
   Section 5, phase 7.
5. **Discovery probes every peer before it answers.** The panel shows a
   single checking message while that is in flight, then rows with
   reachability and fingerprint already resolved. Section 4.1, section 3
   step 3.

Also folded in: the `hosts.multi` entitlement is checked by enrolment, with
the same 403 body `create_host` returns, and reported by discovery as
`multi_host_entitled`, so the panel says what the tier requires instead of
offering ticks that would all fail.
