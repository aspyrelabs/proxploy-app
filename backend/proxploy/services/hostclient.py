# backend/proxploy/services/hostclient.py
"""The one decrypt-then-construct helper: a Host row -> a ProxmoxClient.

api/consoles.py and services/lifecycle.py each carried their own copy of these
five lines; consoles.py's copy even carried a comment naming a 4th call site as
the tip-over point for extracting it. Phase 6 adds three routers and twelve job
handlers that all need it, so it is one function now and the copies are gone.

It raises ProxmoxError, never HTTPException, never JobFailed; because both
kinds of caller live here: a route turns it into a 409, a job handler into a
JobFailed. That translation is one line at each call site and keeps this module
free of both FastAPI and the job engine.

Not used by api/hosts.py::test_host, deliberately: that route also needs the
HostCredential row itself (to stamp `last_used_at`), which this helper does not
return, so folding it in would mean widening the return type for one caller.

Step one of the per-capability host token work (host-token-privileges-
step-one-report.md) put the capability into `client_for_host` itself: storage
is `host_credentials.kind = "api_token:<capability>"` (monitoring/lifecycle/
console/backup), never a second WHERE clause threaded through every caller,
and `UniqueConstraint(host_id, kind)` already enforces one token per
capability with no schema change. `capability` defaults to "monitoring"
because that is the one every host is guaranteed to have (it is mandatory at
enrolment); every other call site names the capability it actually needs.
"""
from __future__ import annotations

import json as jsonlib

from proxploy.models import Host, HostCredential
from proxploy.services.proxmox import ProxmoxClient, ProxmoxError


class CapabilityNotConfigured(ProxmoxError):
    """Raised the moment a call site asks for a capability this host has no
    token for, before any network call is made.

    A `ProxmoxError` subclass on purpose: every existing `except
    ProxmoxError` block across the codebase (routes turning it into an
    HTTPException, job handlers turning it into a JobFailed) catches this
    without any changes, while `kind == "capability_missing"` and the
    `.capability` attribute let a caller that wants to say something more
    specific (e.g. a structured 400 naming where to add the token) do so.
    Same shape as api/catalog.py's `install_catalog_entry` checking for an
    `ssh_key` row before ever reaching the executor, generalized to four
    capabilities instead of one always-or-never credential.
    """

    def __init__(self, host_name: str, capability: str):
        self.capability = capability
        super().__init__(
            f"{host_name} has no {capability} API token configured; add one "
            f"in Settings -> Hosts before this operation can run.",
            kind="capability_missing")


def client_for_host(app, db, host: Host, capability: str = "monitoring") -> ProxmoxClient:
    cred = (db.query(HostCredential)
            .filter_by(host_id=host.id, kind=f"api_token:{capability}").one_or_none())
    if cred is None:
        raise CapabilityNotConfigured(host.name, capability)
    tok = jsonlib.loads(app.state.secretstore.decrypt(cred.encrypted_blob))
    return ProxmoxClient(host.address, tok["token_id"], tok["token_secret"],
                         verify_tls=host.verify_tls,
                         tls_fingerprint=host.tls_fingerprint,
                         factory=app.state.proxmox_factory)


def cluster_scope(host: Host) -> tuple:
    """Groups Hosts that are genuinely the same Proxmox cluster, for any
    dedupe/lookup keyed on a node name or a ctid: both are only unique WITHIN
    a cluster, not across two registered clusters (or two standalone hosts).

    `cluster_name` is None for a standalone host, and None is a real value
    meaning "not clustered" (pollers/__init__.py's UNREAD comment), not
    "unknown cluster", two standalone hosts must never merge with each
    other just because they share that None. Keyed by host.id in that case,
    since a standalone host is its own one-node cluster and nothing else
    can legitimately share its scope.
    """
    return (host.cluster_name,) if host.cluster_name is not None else ("standalone", host.id)


def dedupe_vms(rows, hosts: dict) -> list:
    """One row per real guest, from a `vms` table that holds one per (host, vmid).

    `/cluster/resources` answers for the whole cluster from any member, so every
    polled host mirrors every VM in the cluster: a two-host cluster produced two
    rows for one guest, each with its own id. Observed on real hardware, where
    it also made half of every action fail before `vms.node_name` existed (doc 12
    check 18).

    Keyed on `cluster_scope`, not on host id, for the reason that helper exists:
    a vmid is unique only within a cluster. The row kept is the one belonging to
    the host registered AT the node the guest runs on, falling back to the lowest
    id, so the choice is deterministic rather than dependent on which host's poll
    landed first.

    A guest on a cluster node Proxploy has not enrolled is still returned, by
    whichever host reported it: hiding it would remove working functionality,
    since a cluster-wide token acts on any member's guest through any node
    (proven when the node fix was verified).
    """
    def rank(v, host) -> tuple:
        owns = bool(v.node_name) and host.node_name == v.node_name
        return (0 if owns else 1, v.id)

    best: dict[tuple, tuple] = {}
    for v in rows:
        host = hosts.get(v.host_id)
        if host is None:
            continue
        key = (cluster_scope(host), v.vmid)
        r = rank(v, host)
        if key not in best or r < best[key][0]:
            best[key] = (r, v)
    return [v for _r, v in best.values()]


def cluster_quorate(rows: list[dict]) -> bool | None:
    """Is this cluster quorate, per its own `/cluster/status` cluster row?

    None for a standalone node (no cluster row, so the question does not
    apply) and None if the field is absent rather than guessing True.

    This exists because on 2026-08-18 a real cluster was driven into actual
    quorum loss (doc 12 check 12) and NOTHING in the product noticed: every
    host still read `connected`, `POST /hosts/{id}/test` still returned a PVE
    version, and `/cluster/resources` still listed guests, while `/etc/pve`
    was read-only and every write failed with "cluster not ready - no quorum?".
    The one honest signal was `quorate: 0` on this row, from BOTH nodes, and no
    code read it.
    """
    for row in rows:
        if row.get("type") == "cluster":
            value = row.get("quorate")
            return None if value is None else bool(value)
    return None


def guest_node(host, row=None) -> str:
    """The node a GUEST runs on, which is not always its host's own node.

    `/cluster/resources` answers for the whole cluster from any member, so on a
    cluster every polled host mirrors every VM, and using the host's node
    reaches the wrong one for every row but the owning node's: PVE answers
    `500 Configuration file 'nodes/<other>/qemu-server/<id>.conf' does not
    exist`, observed on PVE 9.2.10 (doc 12 check 18).

    `Vm.node_name` carries the answer; `App` has no such column and does not
    need one today, because an app's row is repointed by the migration handler
    and installs choose their host. Falls back to the host's node, which is
    both correct for a standalone host and the behaviour that predates this.
    """
    return getattr(row, "node_name", None) or host.node_name or ""


def cluster_identity(client) -> tuple[str | None, str | None]:
    """(node name, cluster name) for this address.

    `/cluster/status` is the only honest answer: on a cluster it marks the node
    you are talking to with `local: 1`, which a `/nodes` listing cannot tell
    you. A standalone node returns exactly one node row. Anything unexpected
    leaves it NULL and the poller fills it in as before, so a surprising
    cluster shape can never block enrolment.

    The SAME response carries cluster membership, in its `{"type": "cluster"}`
    row (a standalone node has no such row -> None), so recording
    `hosts.cluster_name` costs no extra round trip beyond this one call.

    Lives here rather than in api/hosts.py because BOTH the enrolment route and
    the poll loop need it, and the poll loop must not import from the API
    layer. Takes a client rather than a Host so the caller decides which
    capability's client to spend.

    RAISES rather than swallowing, and that is load-bearing now that the poll
    loop calls it every cycle. A swallowed failure returns cluster=None, which
    is indistinguishable from "this node is standalone", so a single probe
    hiccup would clear a real cluster name and every node card would claim
    standalone until something else happened to fix it. Enrolment still cannot
    fail on a probe hiccup; it catches this itself.
    """
    return cluster_identity_from(client.cluster_status())


def cluster_identity_from(rows: list[dict]) -> tuple[str | None, str | None]:
    """The rows half of `cluster_identity`, split out so a caller that needs
    more than one answer from `/cluster/status` (the poll loop also wants
    `cluster_quorate`) spends one call rather than two."""
    cluster = next((r.get("name") for r in rows
                    if r.get("type") == "cluster"), None)
    nodes = [r for r in rows if r.get("type") == "node"]
    if len(nodes) == 1:
        return nodes[0].get("name"), cluster
    for r in nodes:
        if r.get("local"):
            return r.get("name"), cluster
    return None, cluster
