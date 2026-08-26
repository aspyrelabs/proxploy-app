"""The one decrypt-then-construct helper: a Host row -> a ProxmoxClient.

Raises ProxmoxError, never HTTPException, never JobFailed: a route turns it
into a 409, a job handler into a JobFailed. That translation stays at each
call site, keeping this module free of both FastAPI and the job engine.

Storage is `host_credentials.kind = "api_token:<capability>"`
(monitoring/lifecycle/console/backup), never a WHERE clause threaded through
every caller, and `UniqueConstraint(host_id, kind)` enforces one token per
capability. `capability` defaults to "monitoring" because every host has one
(it is mandatory at enrolment); other call sites name the capability they
actually need.
"""
from __future__ import annotations

import json as jsonlib

from proxploy.models import Host, HostCredential
from proxploy.services.proxmox import ProxmoxClient, ProxmoxError
from proxploy.services.pveum import CAPABILITIES


class CapabilityNotConfigured(ProxmoxError):
    """Raised when a call site asks for a capability this host has no token for,
    before any network call is made.

    A `ProxmoxError` subclass on purpose: every existing `except ProxmoxError`
    block (routes turning it into an HTTPException, job handlers into a JobFailed)
    catches this unchanged, while `kind == "capability_missing"` and the
    `.capability` attribute let a caller that wants a more specific message (e.g.
    a structured 400) do so.
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
    dedupe/lookup keyed on a node name or a ctid: both are unique only WITHIN a
    cluster, not across two registered clusters (or two standalone hosts).

    `cluster_name` is None for a standalone host, and None is a real value meaning
    "not clustered" (pollers/__init__.py's UNREAD comment), not "unknown cluster":
    two standalone hosts must never merge just because they share that None. Keyed
    by host.id in that case, since a standalone host is its own one-node cluster.
    """
    return (host.cluster_name,) if host.cluster_name is not None else ("standalone", host.id)


def dedupe_vms(rows, hosts: dict) -> list:
    """One row per real guest, from a `vms` table that holds one per (host, vmid).

    `/cluster/resources` answers for the whole cluster from any member, so every
    polled host mirrors every VM in the cluster: a two-host cluster produced two
    rows for one guest, each with its own id. Observed on real hardware, where it
    also made half of every action fail before `vms.node_name` existed.

    Keyed on `cluster_scope`, not host id: a vmid is unique only within a cluster.
    The row kept is the one belonging to the host registered AT the node the guest
    runs on, falling back to the lowest id, so the choice is deterministic.

    A guest on a cluster node Proxploy has not enrolled is still returned, by
    whichever host reported it: hiding it would remove working functionality,
    since a cluster-wide token acts on any member's guest through any node.
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


def granted_privileges(client) -> set[str] | None:
    """Every privilege this token holds anywhere, or None if that could not
    be determined (some setups refuse /access/permissions to a token).

    Shared by both privilege checks below so there is exactly one place that
    reads /access/permissions and exactly one meaning for "could not tell".
    """
    try:
        granted: set[str] = set()
        for privs in (client.permissions() or {}).values():
            granted.update(p for p, on in (privs or {}).items() if on)
        return granted
    except Exception:  # noqa: BLE001  (unknown, never fatal)
        return None


def capability_gaps(app, db, host) -> dict[str, list[str] | None]:
    """Per configured capability token, which of its role's privileges it lacks.

    `api/hosts.py::_missing_privileges` only ever checked the MONITORING set,
    because that is the one a poll cycle needs. The other three tokens were never
    checked, and privilege drift is not hypothetical: privileges were added to the
    Lifecycle role (e.g. `SDN.Use` for a guest NIC on a PVE 9 bridge,
    `VM.Config.HWType` for a VM create), each found only when a real token met
    real PVE. Every token an operator generated before is short of them and
    nothing said so: the symptom is a 403 halfway through a job.

    None means "could not tell" (the token is refused `/access/permissions`),
    never "nothing missing" — the same rule `_missing_privileges` follows. A
    capability with no token configured is absent from the result, since not
    configuring one is a legitimate choice.

    Costs one `/access/permissions` per configured token; callers control the
    cadence (the test route per press, the poll loop at a slow interval).
    """
    gaps: dict[str, list[str] | None] = {}
    for key, cap in CAPABILITIES.items():
        try:
            client = client_for_host(app, db, host, capability=key)
        except ProxmoxError:
            continue                      # not configured: not a gap
        granted = granted_privileges(client)
        if granted is None:
            gaps[key] = None
            continue
        missing = [p for p in cap.privileges if p not in granted]
        if missing:
            gaps[key] = missing
    return gaps


def cluster_quorate(rows: list[dict]) -> bool | None:
    """Is this cluster quorate, per its own `/cluster/status` cluster row?

    None for a standalone node (no cluster row, the question does not apply) and
    None if the field is absent rather than guessing True.

    Exists because a real cluster was driven into actual quorum loss and NOTHING
    in the product noticed: every host still read `connected`, `POST
    /hosts/{id}/test` still returned a PVE version, and `/cluster/resources` still
    listed guests, while `/etc/pve` was read-only and every write failed with
    "cluster not ready - no quorum?". The one honest signal was `quorate: 0` on
    this row, from BOTH nodes, and no code read it.
    """
    for row in rows:
        if row.get("type") == "cluster":
            value = row.get("quorate")
            return None if value is None else bool(value)
    return None


def cluster_member_count(rows: list[dict]) -> int | None:
    """How many nodes this cluster is CONFIGURED to have, per its own
    `/cluster/status` cluster row.

    Does not move when a node goes down: it comes from corosync's config, not
    liveness, so it is the only thing that can tell "two nodes, I see one" from
    "one node". `/cluster/resources` cannot: a member that drops out during a
    split leaves no row behind to notice, which is what let a partial read pass as
    complete and halve every cluster-wide sum.

    None for a standalone node and None if the field is absent rather than
    guessing.
    """
    for row in rows:
        if row.get("type") == "cluster":
            value = row.get("nodes")
            return None if value is None else int(value)
    return None


def guest_node(host, row=None) -> str:
    """The node a GUEST runs on, which is not always its host's own node.

    `/cluster/resources` answers for the whole cluster from any member, so on a
    cluster every polled host mirrors every VM, and using the host's node reaches
    the wrong one for every row but the owning node's: PVE answers
    `500 Configuration file 'nodes/<other>/qemu-server/<id>.conf' does not
    exist`, observed on PVE 9.2.10.

    `Vm.node_name` carries the answer; `App` has no such column and does not need
    one today, because an app's row is repointed by the migration handler and
    installs choose their host. Falls back to the host's node, correct for a
    standalone host and the behaviour that predates this.
    """
    return getattr(row, "node_name", None) or host.node_name or ""


def cluster_identity(client) -> tuple[str | None, str | None]:
    """(node name, cluster name) for this address.

    `/cluster/status` is the only honest answer: on a cluster it marks the node
    you are talking to with `local: 1`, which a `/nodes` listing cannot tell you.
    A standalone node returns exactly one node row. Anything unexpected leaves it
    NULL and the poller fills it in, so a surprising cluster shape cannot block
    enrolment.

    The SAME response carries cluster membership, in its `{"type": "cluster"}`
    row (a standalone node has no such row -> None), so recording
    `hosts.cluster_name` costs no extra round trip beyond this one call.

    Lives here rather than in api/hosts.py because BOTH the enrolment route and
    the poll loop need it, and the poll loop must not import from the API layer.

    RAISES rather than swallowing, and that is load-bearing now that the poll loop
    calls it every cycle: a swallowed failure returns cluster=None, which is
    indistinguishable from "this node is standalone", so a single probe hiccup
    would clear a real cluster name. Enrolment catches this itself.
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
