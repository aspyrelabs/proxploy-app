"""Host onboarding. ROUTE TEMPLATE: every mutation stacks auth, RBAC stub,
entitlement, work, audit. Later routes copy this shape."""
import json as jsonlib
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, field_validator

from proxploy.api.deps import authorize, entitlement_error, get_db, scope_host
from proxploy.api.jobs import enqueue_and_audit
from proxploy.models import Host, HostCredential, Team, User, to_iso, utcnow
from proxploy.services.audit import write_audit
from proxploy.executor import SSHExecutor, SSHHostKeyMismatch
from proxploy.services.proxmox import (ProxmoxClient, ProxmoxError, parse_token_id,
                                       tls_fingerprint_sha256, token_public_meta)
from proxploy.services.hostclient import (capability_gaps, client_for_host,
                                          cluster_identity, cluster_quorate,
                                          granted_privileges, privilege_repair_plan)
from proxploy.services.privrepair import (PrivilegeRepairRefused,
                                          existing_role_privileges,
                                          repair_host_privileges)
from proxploy.services.pveum import repair_commands
from proxploy.services.selfguard import is_self_host_node
from proxploy.services.sshkeys import generate_ed25519

router = APIRouter(prefix="/hosts", tags=["hosts"])

# Singletons so FastAPI's dependency cache (keyed on the callable) collapses
# repeated uses into one call per request.
_read = authorize("host", "read")                      # no host id yet (list)
_read_scoped = authorize("host", "read", scope_of=scope_host())
_manage = authorize("host", "manage", scope_of=scope_host())
_manage_global = authorize("host", "manage")          # no host id yet (probe, create)
# PUT /self writes an app setting, not a host row: ("settings", "manage") is
# the same permission api/settings.py and api/meta.py already gate their own
# setting writes on, not a host permission.
_manage_self_host = authorize("settings", "manage")

CONSENT_NOTE = ("This key gives Proxploy a root shell on the node, used only for "
                "App Store install/update/migration scripts, exactly as if you ran "
                "them yourself as root on the node. Every use is audit-logged and its "
                "full output archived. Authorize it by adding the line to "
                "/root/.ssh/authorized_keys on the node.")


class ProbeIn(BaseModel):
    address: str
    token_id: str
    token_secret: str
    verify_tls: bool = True
    tls_fingerprint: str | None = None
    name: str | None = None

    @field_validator("token_id")
    @classmethod
    def _parseable_into_known_safe_parts(cls, v: str) -> str:
        """Reject at the door with a 422 rather than letting an unparseable
        token id travel as far as _connect()'s 502. Safe to surface: the message
        never echoes the input, and main.py strips pydantic's `input` field from
        every validation error body."""
        try:
            parse_token_id(v)
        except ProxmoxError as e:
            raise ValueError(str(e)) from None
        return v


class HostIn(ProbeIn):
    name: str
    ssh_enroll: bool = False
    ssh_consent: bool = False


class HostPatchIn(BaseModel):
    """Partial update: every field is optional and only the ones supplied are
    changed. Credentials are deliberately NOT here: POST
    /{host_id}/credentials is their own flow, which verifies a new token
    against the node before replacing the old one, and the Edit dialog
    composes both calls rather than this route growing a second credential
    path."""
    node_shell_enabled: bool | None = None
    team_id: int | None = None
    name: str | None = None
    address: str | None = None
    # The re-pin path. A pin is only enforced while verify_tls is false, the
    # normal case for a stock self-signed node, so it is the only integrity
    # those connections have. Nothing could change one before this, so a
    # routine certificate renewal left a host row nobody could fix from the
    # UI. Setting it re-pins, null clears the pin (omitted and null differ
    # here, as for team_id).
    tls_fingerprint: str | None = None
    # The SSH re-pin path, same reason: nothing could change this before, so a
    # node whose host key rotated (rejoining a cluster does it) failed every
    # install with no way back but a manual database write. Omitted leaves it
    # alone, null clears the pin so the next connection re-learns it (TOFU).
    ssh_host_key_fingerprint: str | None = None

    @field_validator("name", "address")
    @classmethod
    def _not_blank(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            raise ValueError("cannot be blank")
        return v


def _api_addresses(client) -> dict[str, str]:
    """{node name: the address PVE designates for its API}, from
    /cluster/config/join, or {} if that cannot be read.

    `/cluster/status` reports only `ip`, corosync's ring0 address. PVE keeps
    `ring0_addr` and `pve_addr` separate, so where corosync runs on a
    dedicated link every peer built from `ip` would be unreachable.

    Best effort: {} means callers fall back to the `/cluster/status` address,
    correct whenever the two coincide. Failing discovery over one unreadable
    endpoint would be the worse trade.
    """
    try:
        info = client.cluster_join_info()
    except (ProxmoxError, OSError):
        return {}
    out = {}
    for n in (info or {}).get("nodelist", []) or []:
        name, addr = n.get("name"), n.get("pve_addr")
        if name and addr:
            out[name] = addr
    return out


def _fingerprint_now(address: str) -> str | None:
    """The certificate the node at `address` is presenting right now, or None
    if it could not be fetched.

    Never raises. A pin is worth having, but never worth blocking an
    enrolment or a connection test over.
    """
    url = urlparse(address)
    try:
        return tls_fingerprint_sha256(url.hostname, url.port or 8006)
    except (OSError, ProxmoxError):
        return None


def _client(request: Request, body: ProbeIn) -> ProxmoxClient:
    return ProxmoxClient(body.address, body.token_id, body.token_secret,
                         verify_tls=body.verify_tls,
                         tls_fingerprint=body.tls_fingerprint,
                         factory=request.app.state.proxmox_factory)


# The read-only monitoring set, required for the poller to complete a cycle at
# all. Only this set: lifecycle, console and backup gate optional features,
# and a token without them should still enrol. Imported from services/pveum,
# which also generates the script that creates these tokens, so what the
# wizard tells you to make always satisfies the check it then runs.
from proxploy.services.pveum import (CAPABILITIES, MONITORING_PRIVILEGES,
                                     NODE_POWER_PRIVILEGE, generate_script)


def _missing_privileges(client) -> list[str] | None:
    """Which monitoring privileges this token does not hold anywhere.

    None means "could not tell", NOT "none missing": some setups refuse
    /access/permissions to a token, and reporting unknown as a clean bill of
    health is how this failed silently before.

    A privilege granted on any path counts: Proxploy can be scoped to a pool
    by granting the roles on /pool/<name>, so requiring them at "/" would
    call a working pool-scoped install broken.
    """
    granted = granted_privileges(client)
    if granted is None:
        return None
    return [p for p in MONITORING_PRIVILEGES if p not in granted]


def _node_power_missing(client) -> bool | None:
    """Whether this token lacks Sys.PowerMgmt anywhere. None means "could not
    tell", same reasoning as _missing_privileges.

    Checked unconditionally, unlike Lifecycle/Console/Backup: the host actions
    menu offers Reboot/Power off on every host whatever capabilities were
    chosen.
    """
    granted = granted_privileges(client)
    if granted is None:
        return None
    return NODE_POWER_PRIVILEGE not in granted


def _lifecycle_power_missing(app, db, host) -> bool | None:
    try:
        client = client_for_host(app, db, host, capability="lifecycle")
    except Exception:  # noqa: BLE001  (no lifecycle token, or it will not build)
        return True
    return _node_power_missing(client)


def _capability_state(kinds) -> dict[str, bool]:
    """Which capability tokens this host holds. Presence only.

    Never the token, the token id, or any part of the blob: the UI only needs
    to know whether a capability is configured. Keyed off CAPABILITIES so a
    new capability appears here with no second list, and a host with no
    credential rows reports every capability False rather than omitting the
    field.
    """
    stored = set(kinds)
    return {c: f"api_token:{c}" in stored for c in CAPABILITIES}


def _privilege_note(missing: list[str] | None) -> str | None:
    if not missing:
        return None
    return ("the API token is missing " + ", ".join(missing)
            + ". Monitoring reads will fail until these are granted; see "
              "docs.proxploy.com/getting-started/proxmox-token")


class TokenScriptIn(BaseModel):
    """Which capabilities to provision. Monitoring is always included by the
    generator, so omitting it here is not a way to opt out of it."""
    capabilities: list[str] = []
    path: str = "/"


@router.post("/token-script")
def token_script(body: TokenScriptIn, user: User = Depends(_manage_global)):
    """The copy-paste pveum script an operator runs to create the tokens.

    POST rather than GET for the structured body; it reads and changes nothing
    here. The operator runs the result in a node shell they already own:
    Proxploy never asks for root credentials, even transiently.
    """
    try:
        script = generate_script(body.capabilities, path=body.path)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    return {"script": script,
            "capabilities": [{"key": c.key, "label": c.label, "why": c.why,
                              "required": c.required, "role": c.role}
                             for c in CAPABILITIES.values()]}


@router.post("/probe")
def probe(request: Request, body: ProbeIn,
          user: User = Depends(_manage_global)):
    client = _client(request, body)
    try:
        v = client.version()
    except ProxmoxError as e:
        raise HTTPException(502, {"error": e.kind, "detail": str(e)})
    # /version succeeds for a privsep token holding no ACLs at all, so alone
    # it proves only that the address and secret are right. The privilege diff
    # is what makes "Test connection" mean what operators read it as.
    return {"ok": True, "version": v.get("version"), "release": v.get("release"),
            "missing_privileges": _missing_privileges(client),
            "node_power_missing": _node_power_missing(client)}


@router.post("", status_code=201)
def create_host(request: Request, body: HostIn, db=Depends(get_db),
                user: User = Depends(_manage_global)):
    ent = request.app.state.entitlements
    if db.query(Host).count() >= 1 and not ent.enabled("hosts.multi"):
        raise entitlement_error("hosts.multi")
    if body.ssh_enroll and not body.ssh_consent:
        raise HTTPException(400, "SSH enrolment requires explicit consent "
                                 "(ssh_consent: true). " + CONSENT_NOTE)
    if db.query(Host).filter_by(name=body.name).one_or_none():
        raise HTTPException(409, "host name already exists")

    audit_params = body.model_dump()  # write_audit redacts token_secret
    client = _client(request, body)
    try:
        v = client.version()
    except ProxmoxError as e:
        # No Host row exists yet, the enrolment failed before one was written,
        # so the name the operator typed is what they will search for later.
        write_audit(db, actor_type="user", actor_id=user.id, action="host.create",
                    target_name=body.name, params=audit_params, result="error",
                    ip=request.client.host if request.client else None)
        raise HTTPException(502, {"error": e.kind, "detail": str(e)})

    # Checked at enrolment, not left for the poller to report minutes later as
    # a bare "unreachable". Recorded rather than refused: an under-privileged
    # token is still worth enrolling.
    missing = _missing_privileges(client)
    # None, not a probe of the monitoring token: Sys.PowerMgmt lives on
    # Lifecycle's role now, and no lifecycle token has been stored yet at
    # enrolment. The refresh below fills this in once one exists.
    node_power_missing = None
    try:
        node_name, cluster_name = cluster_identity(client)
    except ProxmoxError:  # enrolment must survive a probe hiccup
        node_name = cluster_name = None
    # Pin on first use, and first use is enrolment. Only when the request
    # supplied none: an operator who pasted a fingerprint has already said
    # which certificate is right, and probing over the top would replace their
    # answer. A failed probe leaves the host unpinned rather than blocking
    # enrolment.
    fingerprint = body.tls_fingerprint or _fingerprint_now(body.address)
    host = Host(name=body.name, address=body.address, verify_tls=body.verify_tls,
                tls_fingerprint=fingerprint, status="connected",
                node_name=node_name, cluster_name=cluster_name,
                last_error=_privilege_note(missing),
                node_power_missing=node_power_missing,
                pve_version=v.get("version"), last_seen_at=utcnow())
    db.add(host)
    # flush, not commit: this needs host.id for the credential rows below,
    # which belong to the same enrolment. Committing here left a window where
    # a crash produced a host row with no credential, enrolled in the UI,
    # unreachable, and repaired by no route.
    db.flush()

    ss = request.app.state.secretstore
    blob, ver = ss.encrypt(jsonlib.dumps(
        {"token_id": body.token_id, "token_secret": body.token_secret}).encode())
    # Enrolment always creates the "monitoring" row: the one mandatory
    # capability, and the only token pasted at this step of the wizard.
    # Lifecycle/console/backup tokens arrive later via
    # POST /hosts/{id}/credentials (CredentialRotateIn.capability).
    db.add(HostCredential(host_id=host.id, kind="api_token:monitoring",
                          encrypted_blob=blob, key_version=ver,
                          public_meta=token_public_meta(body.token_id)))

    out = {"id": host.id, "name": host.name, "address": host.address,
           "node_name": host.node_name, "cluster_name": host.cluster_name,
           "pve_version": host.pve_version,
           "status": host.status, "missing_privileges": missing,
           "node_power_missing": node_power_missing}
    if body.ssh_enroll:
        private_pem, public_line = generate_ed25519(f"proxploy@{body.name}")
        sblob, sver = ss.encrypt(private_pem)
        db.add(HostCredential(host_id=host.id, kind="ssh_key", encrypted_blob=sblob,
                              key_version=sver, public_meta=public_line))
        out |= {"ssh_public_key": public_line,
                "authorized_keys_line": public_line,
                "consent_note": CONSENT_NOTE}
    db.commit()
    write_audit(db, actor_type="user", actor_id=user.id, action="host.create",
                target_type="host", target_id=host.id, params=audit_params,
                ip=request.client.host if request.client else None)
    return out


@router.get("")
def list_hosts(db=Depends(get_db), user: User = Depends(_read)):
    # One query for every host's credential kinds, not one per host: this
    # route is the hosts table's own fetch and N+1 here is N+1 on every
    # settings page load.
    kinds: dict[int, set[str]] = {}
    for host_id, kind in db.query(HostCredential.host_id, HostCredential.kind):
        kinds.setdefault(host_id, set()).add(kind)
    return [{"id": h.id, "name": h.name, "address": h.address,
             # cluster_name so the frontend can tell which enrolled hosts are
             # nodes of the same cluster.
             "node_name": h.node_name, "cluster_name": h.cluster_name,
             "status": h.status,
             "last_error": h.last_error,
             "pve_version": h.pve_version, "node_shell_enabled": h.node_shell_enabled,
             "node_power_missing": h.node_power_missing,
             # NULL means standalone or not-yet-polled, never "quorum lost":
             # only False says PVE reported an unwritable cluster (doc 12
             # check 12).
             "quorate": h.quorate,
             # {} means probed and clean, null means never probed, and a
             # capability mapped to null means its token could not be read.
             "capability_gaps": h.capability_gaps,
             "team_id": h.team_id,
             # The install dialog asks the root-execution tick only while this
             # is null. Re-asking a host that already acknowledged surfaces no
             # new information, it is just friction.
             "install_consent_at": to_iso(h.install_consent_at),
             "capabilities": _capability_state(kinds.get(h.id, ())),
             "last_seen_at": to_iso(h.last_seen_at)}
            for h in db.query(Host).order_by(Host.id)]


@router.get("/capabilities")
def list_capabilities(user: User = Depends(_read)):
    """The static catalogue of optional capabilities the setup script can
    grant (key, label, why it matters, whether it is required).

    Registered ABOVE the /{host_id} wildcard: Starlette matches in
    registration order, and out of order this literal path is swallowed by
    GET /{host_id} with host_id="capabilities".

    Derived straight from CAPABILITIES, list not dict, so declaration order
    survives into the response. privileges/role/token are left off: the UI
    needs why a capability matters, not PVE privilege names.
    """
    return [{"key": c.key, "label": c.label, "why": c.why, "required": c.required}
            for c in CAPABILITIES.values()]


class SelfHostIn(BaseModel):
    host_id: int | None = None


@router.put("/self")
def set_self_host(request: Request, body: SelfHostIn, db=Depends(get_db),
                  user: User = Depends(_manage_self_host)):
    """Which enrolled host, if any, Proxploy itself runs on: what narrows
    selfguard.is_self_host_node() to a Host record.

    A dedicated route rather than a hole in PATCH /settings's allowlist,
    which takes free-form values: self.host_id must name an enrolled host or
    nothing, never an arbitrary string.

    `host_id: null` is "none of these", and set_setting still writes the row,
    so the wizard can tell "answered none" from "never asked". Every
    selfguard read treats absent and None alike (fail open), so it only stops
    the question being asked again.
    """
    if body.host_id is not None and db.get(Host, body.host_id) is None:
        raise HTTPException(404, "host not found")
    from proxploy.services.settings import set_setting
    set_setting(db, "self.host_id", body.host_id)
    ip = request.client.host if request.client else None
    write_audit(db, actor_type="user", actor_id=user.id, action="settings.self_host",
                target_type="host", target_id=body.host_id,
                params={"host_id": body.host_id}, ip=ip)
    return {"host_id": body.host_id}


@router.get("/{host_id}")
def host_detail(host_id: int, db=Depends(get_db),
                user: User = Depends(_read_scoped)):
    h = db.get(Host, host_id)
    if not h:
        raise HTTPException(404, "no such host")
    creds = db.query(HostCredential).filter_by(host_id=h.id).all()
    return {"id": h.id, "name": h.name, "address": h.address,
            "node_name": h.node_name, "status": h.status,
            "last_error": h.last_error,
            "pve_version": h.pve_version, "verify_tls": h.verify_tls,
            "node_shell_enabled": h.node_shell_enabled,
            "node_power_missing": h.node_power_missing, "quorate": h.quorate,
            "capability_gaps": h.capability_gaps, "team_id": h.team_id,
            "capabilities": _capability_state(c.kind for c in creds),
            "credentials": [{"kind": c.kind, "public_meta": c.public_meta,
                             "last_used_at": to_iso(c.last_used_at)} for c in creds]}


@router.get("/{host_id}/peers")
def list_peers(request: Request, host_id: int, db=Depends(get_db),
               user: User = Depends(_manage)):
    """The other nodes of this host's cluster, and whether each can be added.

    Read only: nothing here writes a host, a credential or an audit row, and
    it reveals only what POST /hosts/probe already returns to an admin.

    Every peer is probed before this answers, so no row is rendered with
    reachability unknown. A failure is recorded on that peer's row and never
    raised: one dead node must not hide the live ones.

    The peer address comes from the node, not the operator, so the guard that
    matters is resolve_target() inside tls_fingerprint_sha256 and
    ProxmoxClient._connect. No new guard is needed here.
    """
    h = db.get(Host, host_id)
    if h is None:
        raise HTTPException(404, "host not found")
    try:
        client = client_for_host(request.app, db, h)
        rows = client.cluster_status()
    except ProxmoxError as e:
        raise HTTPException(502, {"error": e.kind, "detail": str(e)}) from e

    kinds = {c.kind for c in db.query(HostCredential).filter_by(host_id=h.id)}
    team = db.get(Team, h.team_id) if h.team_id is not None else None
    cluster = next((r.get("name") for r in rows if r.get("type") == "cluster"), None)
    out = {"cluster": cluster,
           "team": {"id": team.id, "name": team.name} if team else None,
           # The origin's own api_token:* kinds, so the caller can say what
           # would be copied. ssh_key is not here and never will be: it is a
           # root shell, a different trust decision from an API token.
           "capabilities_to_copy": [c for c in CAPABILITIES
                                    if f"api_token:{c}" in kinds],
           # A peer is never the first host, so the entitlement is always
           # required for one.
           "multi_host_entitled": request.app.state.entitlements.enabled("hosts.multi"),
           "peers": []}
    if cluster is None:
        # No cluster row means standalone. Its single node row is this host
        # itself and carries no `local` flag on some versions, so returning here
        # is what stops it being offered as its own peer.
        return out

    enrolled = db.query(Host).filter(Host.id != h.id).all()
    api_addresses = _api_addresses(client)
    for r in rows:
        if r.get("type") != "node" or r.get("local"):
            continue
        node = r.get("name")
        # pve_addr when PVE gives one, else the corosync address it reports
        # here. See _api_addresses: these differ on a split-network cluster.
        ip = api_addresses.get(node) or r.get("ip")
        peer = {"node": node, "address": f"https://{ip}:8006",
                "online": bool(r.get("online")), "reachable": False,
                "tls_fingerprint": None, "already_enrolled_as": None,
                "error": None}
        # Matched on cluster plus node name, never on address, so a peer
        # enrolled under a second address or a DNS name is still recognised. A
        # NULL cluster_name counts too: adding the same machine twice is the
        # worse failure.
        peer["already_enrolled_as"] = next(
            (e.name for e in enrolled if e.node_name == node
             and e.cluster_name in (cluster, None)), None)
        # An already enrolled peer cannot be added again, so it is not probed.
        if peer["already_enrolled_as"] is None:
            try:
                # Assigned only once both probes pass, so an errored row never
                # carries a fingerprint the operator might act on.
                fingerprint = tls_fingerprint_sha256(ip)
                ProxmoxClient(peer["address"], client.token_id, client.token_secret,
                              verify_tls=h.verify_tls,
                              factory=request.app.state.proxmox_factory).version()
            except (OSError, ProxmoxError) as e:
                peer["error"] = {
                    "kind": getattr(e, "kind", "unreachable"),
                    "detail": (f"Proxploy could not reach {node} at {ip} on port "
                               f"8006: {e}. It cannot be added until it answers "
                               f"there.")}
            else:
                peer["reachable"], peer["tls_fingerprint"] = True, fingerprint
        out["peers"].append(peer)
    return out


@router.patch("/{host_id}")
def patch_host(host_id: int, body: HostPatchIn, db=Depends(get_db),
              user: User = Depends(_manage)):
    h = db.get(Host, host_id)
    if h is None:
        raise HTTPException(404, "host not found")
    audit_params: dict = {}
    if body.node_shell_enabled is not None:
        h.node_shell_enabled = body.node_shell_enabled
        audit_params["node_shell_enabled"] = h.node_shell_enabled
    # model_fields_set, not `is not None`: null is the only way to say "no
    # team" and this is a partial update, so an omitted field and an explicit
    # null have to mean different things.
    if "team_id" in body.model_fields_set:
        if body.team_id is not None and not db.get(Team, body.team_id):
            raise HTTPException(404, "team not found")
        h.team_id = body.team_id
        audit_params["team_id"] = body.team_id
    if body.name is not None and body.name != h.name:
        clash = db.query(Host).filter(Host.name == body.name,
                                      Host.id != h.id).one_or_none()
        if clash:
            raise HTTPException(409, "a host with that name already exists")
        h.name = body.name
        audit_params["name"] = body.name
    if body.address is not None and body.address != h.address:
        # Deliberately no probe here: verifying a changed address is
        # POST /{host_id}/test's job (already built, already used by the host
        # page), not a second implementation of the same check.
        h.address = body.address
        audit_params["address"] = body.address
    # model_fields_set again: null means "stop pinning this host", and an
    # omitted field must leave the pin alone rather than clearing it on every
    # rename.
    if "tls_fingerprint" in body.model_fields_set:
        h.tls_fingerprint = body.tls_fingerprint
        audit_params["tls_fingerprint"] = body.tls_fingerprint
    if "ssh_host_key_fingerprint" in body.model_fields_set:
        h.ssh_host_key_fingerprint = body.ssh_host_key_fingerprint
        audit_params["ssh_host_key_fingerprint"] = body.ssh_host_key_fingerprint
    db.commit()
    # The node-shell toggle keeps its historic action name, which the audit
    # filters depend on. A name or address change is different enough in kind
    # (identity, not a feature flag) to get its own name.
    action = ("host.update"
              if {"name", "address", "tls_fingerprint",
                  "ssh_host_key_fingerprint"} & audit_params.keys()
              else "host.node_shell_toggle")
    write_audit(db, actor_type="user", actor_id=user.id,
                action=action, target_type="host",
                target_id=h.id, params=audit_params)
    return {"id": h.id, "node_shell_enabled": h.node_shell_enabled}


@router.post("/{host_id}/test")
def test_host(request: Request, host_id: int, db=Depends(get_db),
              user: User = Depends(_manage)):
    h = db.get(Host, host_id)
    if not h:
        raise HTTPException(404, "no such host")
    cred = db.query(HostCredential).filter_by(
        host_id=h.id, kind="api_token:monitoring").one()
    tok = jsonlib.loads(request.app.state.secretstore.decrypt(cred.encrypted_blob))
    seen = None
    # Empty, not None, when the host never connected: "no gaps found" and "could
    # not look" are different, and an unreachable host is the latter for every
    # capability at once, which the status field already says.
    gaps: dict[str, list[str] | None] = {}
    try:
        client = ProxmoxClient(h.address, tok["token_id"], tok["token_secret"],
                               verify_tls=h.verify_tls, tls_fingerprint=h.tls_fingerprint,
                               factory=request.app.state.proxmox_factory)
        v = client.version()
        h.status, h.pve_version, h.last_seen_at = "connected", v.get("version"), utcnow()
        # Probed on the LIFECYCLE token, which is where Sys.PowerMgmt lives.
        # A host with no lifecycle token cannot power the node either way, and
        # says so rather than leaving the last answer standing.
        h.node_power_missing = _lifecycle_power_missing(request.app, db, h)
        # A host that answers /version perfectly can still be unable to accept
        # a single write, which is what quorum loss looks like from here. Best
        # effort: a token that cannot read /cluster/status leaves the previous
        # answer alone rather than claiming standalone.
        try:
            h.quorate = cluster_quorate(client.cluster_status())
        except ProxmoxError:
            pass
        # Every configured token against its own role, not just monitoring
        # against MONITORING_PRIVILEGES: this is where an operator learns a
        # token predating a privilege the product now needs is short of it,
        # instead of learning it from a 403 mid-job.
        gaps = capability_gaps(request.app, db, h)
        # Stored, not just returned: an operator who presses Test connection
        # should not be the only one who ever sees this.
        h.capability_gaps = gaps
        cred.last_used_at = utcnow()
        result = "ok"
    except ProxmoxError as e:
        h.status, result = "unreachable", "error"
        # Only when the pin is what refused the connection: _connect raises
        # that kind before it sends anything, and it is the one case the Edit
        # dialog's compare and accept control fires on. A node that is simply
        # dead answers with a different kind and gets no probe, which could
        # only sit out a second connect timeout.
        #
        # Known gap, deliberate: with verify_tls true the pin is not enforced,
        # so a changed certificate never raises here and the control never
        # appears. CA validation is the trust anchor in that mode.
        if e.kind == "tls_fingerprint":
            seen = _fingerprint_now(h.address)
    db.commit()
    write_audit(db, actor_type="user", actor_id=user.id, action="host.test",
                target_type="host", target_id=h.id, result=result)
    return {"id": h.id, "status": h.status, "pve_version": h.pve_version,
            "node_power_missing": h.node_power_missing, "quorate": h.quorate,
            "capability_gaps": gaps,
            "tls_fingerprint": h.tls_fingerprint, "tls_fingerprint_seen": seen}


@router.post("/{host_id}/ssh/verify")
async def verify_ssh(host_id: int, request: Request, db=Depends(get_db),
                     user: User = Depends(_manage)):
    """Prove the enrolled key actually opens a root shell on the node.

    Without it a mis-pasted authorized_keys line surfaces at the first app
    install, far from its cause. `true` is the whole command: does the key
    authenticate, and can anything be run.
    """
    host = db.query(Host).filter_by(id=host_id).one_or_none()
    if host is None:
        raise HTTPException(404, "host not found")
    cred = db.query(HostCredential).filter_by(host_id=host_id,
                                              kind="ssh_key").one_or_none()
    if cred is None:
        raise HTTPException(502, {"error": "no_key",
                                  "detail": "this host has no enrolled SSH key"})

    def on_new_fingerprint(fp: str) -> None:
        host.ssh_host_key_fingerprint = fp

    executor = SSHExecutor(connect_factory=request.app.state.ssh_connect_factory)
    try:
        code = await executor.run_for_host(
            request.app.state.sessionmaker, request.app.state.secretstore,
            host_id, host.address, "true",
            pinned_fingerprint=host.ssh_host_key_fingerprint,
            on_new_fingerprint=on_new_fingerprint, timeout_s=20.0)
    except SSHHostKeyMismatch as e:
        # `seen` is what the node is presenting right now. Handing it back
        # makes a re-pin possible without the operator reading it off a
        # message. None means no key could be read, which is not a mismatch
        # and must not be offered as one.
        raise HTTPException(502, {"error": "host_key_mismatch", "detail": str(e),
                                  "ssh_host_key_fingerprint": e.pinned,
                                  "ssh_host_key_fingerprint_seen": e.seen})
    except LookupError as e:
        raise HTTPException(502, {"error": "no_key", "detail": str(e)})
    except TimeoutError as e:
        raise HTTPException(502, {"error": "timeout", "detail": str(e)})
    except OSError as e:
        raise HTTPException(502, {"error": "unreachable", "detail": str(e)})

    if code != 0:
        raise HTTPException(502, {"error": "command_failed",
                                  "detail": f"the key authenticated but `true` exited {code}"})
    cred.ssh_verified_at = utcnow()
    db.commit()
    write_audit(db, actor_type="user", actor_id=user.id, action="host.ssh_verify",
                target_type="host", target_id=host_id,
                ip=request.client.host if request.client else None)
    return {"verified": True, "verified_at": to_iso(cred.ssh_verified_at)}


@router.get("/{host_id}/privileges")
def host_privileges(host_id: int, request: Request, db=Depends(get_db),
                    user: User = Depends(_manage)):
    host = db.get(Host, host_id)
    if not host:
        raise HTTPException(404, "no such host")
    plan = privilege_repair_plan(request.app, db, host)
    existing = existing_role_privileges(request.app, db, host, plan)
    commands = repair_commands(plan, existing)
    has_key = db.query(HostCredential).filter_by(
        host_id=host.id, kind="ssh_key").one_or_none() is not None
    return {"host_id": host.id, "missing": plan,
            "can_auto_repair": has_key, "commands": commands}


@router.post("/{host_id}/privileges/repair")
async def repair_privileges(host_id: int, request: Request, db=Depends(get_db),
                            user: User = Depends(_manage)):
    host = db.get(Host, host_id)
    if not host:
        raise HTTPException(404, "no such host")
    try:
        repaired = await repair_host_privileges(
            request.app, db, host, actor_type="user", actor_id=user.id)
    except PrivilegeRepairRefused as e:
        raise HTTPException(409, {"error": "no_ssh_key", "commands": e.commands,
                                  "detail": str(e)})
    except ProxmoxError as e:
        raise HTTPException(502, {"error": e.kind, "detail": str(e)})
    return {"repaired": repaired, "method": "ssh" if repaired else "none"}


_sync = authorize("host", "sync", scope_of=scope_host())
_credentials = authorize("host", "credentials", scope_of=scope_host())
_remove = authorize("host", "remove", scope_of=scope_host())
_power = authorize("host", "power", scope_of=scope_host())


class HostRemoveIn(BaseModel):
    confirm: str | None = None
    # apps.host_id is ON DELETE RESTRICT, so a host with apps cannot simply be
    # dropped. This forgets those app rows; the containers keep running.
    # Destroying one is app uninstall's job, never a side effect of removing a
    # host.
    forget_apps: bool = False


class CredentialRotateIn(BaseModel):
    # Rotate the API token: supply the new one, Proxploy never mints PVE
    # credentials for you.
    token_id: str | None = None
    token_secret: str | None = None
    # Which capability's token this is. Left out entirely, it falls back to
    # "monitoring" ONLY while the host has no monitoring credential, so a
    # pre-capability-era caller's first write still lands where it always did.
    # After that an omitted capability is refused, not guessed: guessing
    # silently overwrote monitoring and convinced operators they had
    # configured lifecycle or backup. Validated against CAPABILITIES
    # (ValueError -> 422), never a hand-kept list that could drift.
    capability: str | None = None
    # Regenerate the SSH keypair in-process. The new public key has to be
    # authorized on the node before installs work again, which is why the
    # response hands it back with the same consent note onboarding uses.
    rotate_ssh: bool = False

    @field_validator("capability")
    @classmethod
    def _known_capability(cls, v: str | None) -> str | None:
        if v is not None and v not in CAPABILITIES:
            raise ValueError(f"capability must be one of "
                             f"{', '.join(sorted(CAPABILITIES))}")
        return v


@router.delete("/{host_id}")
def remove_host(request: Request, host_id: int,
                body: HostRemoveIn = None, db=Depends(get_db),
                user: User = Depends(_remove)):
    """Forget a host and everything Proxploy cached about it.

    Owner-only, and gated on typing the host name back: this drops every app
    row, VM cache row and stored credential in one call, and the SSH key it
    deletes can only be re-enrolled, never recovered.
    """
    body = body or HostRemoveIn()
    h = db.get(Host, host_id)
    if h is None:
        raise HTTPException(404, "host not found")
    ip = request.client.host if request.client else None

    from proxploy.models import App
    from proxploy.services.settings import get_setting

    apps = db.query(App).filter_by(host_id=h.id).all()
    if apps and not body.forget_apps:
        # Refuse with the list rather than a bare constraint error: the operator
        # needs to know WHICH apps stand in the way, and whether they wanted to
        # uninstall them first.
        raise HTTPException(409, {
            "error": "host_has_apps",
            "apps": [{"id": a.id, "name": a.name, "ctid": a.ctid} for a in apps],
            "detail": (f"{h.name} still has {len(apps)} app(s). Uninstall them "
                       f"first, or pass forget_apps to drop Proxploy's records "
                       f"and leave the containers running."),
        })

    if (body.confirm or "") != h.name:
        write_audit(db, actor_type="user", actor_id=user.id, action="host.remove",
                    target_type="host", target_id=h.id, result="denied", ip=ip)
        raise HTTPException(409, {
            "error": "confirm_required", "confirm_phrase": h.name,
            "detail": (f"Removing {h.name} deletes its stored API token and SSH "
                       f"key and everything Proxploy has cached about it. The "
                       f"node itself is not touched. Type the name to confirm."),
        })

    self_host = get_setting(db, "self.host_id")
    is_own_host = False
    try:
        is_own_host = self_host is not None and int(self_host) == h.id
    except (TypeError, ValueError):
        is_own_host = False  # malformed setting fails open, as in selfguard

    # One query before the delete: credentials only ever disappear via a host
    # removal (CASCADE: no route deletes a single credential), so this is the
    # only place "my token vanished" can ever be answered from.
    kinds_removed = sorted(c.kind for c in
                           db.query(HostCredential).filter_by(host_id=h.id).all())
    write_audit(db, actor_type="user", actor_id=user.id, action="host.remove",
                target_type="host", target_id=h.id,
                params={"name": h.name, "forgot_apps": len(apps),
                        "was_own_host": is_own_host,
                        "kinds_removed": kinds_removed}, ip=ip)
    for a in apps:
        db.delete(a)          # RESTRICT: must go before the host
    db.flush()
    db.delete(h)              # vms + host_credentials + metrics CASCADE
    db.commit()
    request.app.state.poller.snapshots.pop(host_id, None)
    request.app.state.bus.publish("resource", {"type": "host", "id": host_id,
                                               "change": "removed"})
    return {"removed": True, "forgot_apps": len(apps),
            "was_own_host": is_own_host}


def _loadavg(raw) -> list[float]:
    """PVE sends loadavg as strings. A UI should not have to parse them, and a
    surprising entry must not cost the whole payload."""
    out: list[float] = []
    for v in (raw or [])[:3]:
        try:
            out.append(float(v))
        except (TypeError, ValueError):
            out.append(0.0)
    while len(out) < 3:
        out.append(0.0)
    return out


@router.get("/{host_id}/nodes/{node}/status")
def node_status(host_id: int, node: str, request: Request, db=Depends(get_db),
                user: User = Depends(_read_scoped)):
    """The node's own view of itself, for the host page.

    On demand, never from the poll loop: a cycle is capped at O(nodes), and
    model/cores/kernel/boot mode do not change between polls. The volatile
    figures here (load, wait, memory) are already recorded as metric samples
    every cycle.
    """
    h = db.get(Host, host_id)
    if h is None:
        raise HTTPException(404, "no such host")
    try:
        st = client_for_host(request.app, db, h).node_status(node)
    except ProxmoxError as e:
        # 502, not 500: a token too narrow to read /nodes/{n}/status is the
        # node refusing, not Proxploy breaking, and the page degrades to
        # everything it already had from the poller's snapshot.
        raise HTTPException(502, {"error": e.kind, "detail": str(e)}) from e

    cpu = st.get("cpuinfo") or {}
    kernel = st.get("current-kernel") or {}
    boot = st.get("boot-info") or {}
    return {
        "node": node,
        # Read off the SAME query the identity rail already fetches, so the
        # confirm dialog can warn BEFORE the operator types anything, not only
        # after a rejected call.
        "is_self": is_self_host_node(db, h, node),
        "uptime_s": st.get("uptime"),
        "pve_version": st.get("pveversion"),
        "kernel": kernel.get("release") or st.get("kversion"),
        "arch": kernel.get("machine"),
        "boot_mode": boot.get("mode"),
        "secure_boot": bool(boot.get("secureboot")),
        "cpu": {
            "model": cpu.get("model"), "vendor": cpu.get("vendor"),
            "sockets": cpu.get("sockets"), "cores": cpu.get("cores"),
            # PVE's `cpus` is the logical processor count. Renamed to
            # `threads` so the UI never has to guess which of the two numbers
            # is which.
            "threads": cpu.get("cpus"), "mhz": cpu.get("mhz"),
        },
        "load": _loadavg(st.get("loadavg")),
        "io_delay": st.get("wait"),
        "memory": st.get("memory") or {},
        "swap": st.get("swap") or {},
        "rootfs": st.get("rootfs") or {},
        "ksm_shared": (st.get("ksm") or {}).get("shared"),
    }


class NodePowerIn(BaseModel):
    command: str  # "reboot" | "shutdown", Proxmox's own node-status verbs
    # Always required, self or not: detection can miss (a relocated install,
    # an ambiguous hostname), so the typed prompt is the backstop. The
    # frontend gates Confirm on it too; this is the server-side half, not a
    # UI nicety.
    confirm: str | None = None

    @field_validator("command")
    @classmethod
    def _known_command(cls, v: str) -> str:
        from proxploy.services.proxmox import NODE_POWER_COMMANDS
        if v not in NODE_POWER_COMMANDS:
            raise ValueError(f"command must be one of {sorted(NODE_POWER_COMMANDS)}")
        return v


@router.post("/{host_id}/nodes/{node}/power", status_code=202)
def power_node(host_id: int, node: str, body: NodePowerIn, request: Request,
               db=Depends(get_db), user: User = Depends(_power)):
    """Reboot or power off a Proxmox NODE, not a guest.

    Owner-gated, same severity as host.remove: this takes the node and every
    guest on it down. The node's name must be typed back, self or not,
    because self-detection can miss. GET .../status's `is_self` only lets the
    dialog warn earlier, it does not replace the gate.

    The PVE call runs as a job (services/guestjobs.py::run_host_power) so it
    leaves a transcript in `job_events`, like every other destructive action.
    The gate runs before anything is enqueued.
    """
    h = db.get(Host, host_id)
    if h is None:
        raise HTTPException(404, "host not found")
    ip = request.client.host if request.client else None
    self_node = is_self_host_node(db, h, node)
    action = f"host.{body.command}"

    if (body.confirm or "") != node:
        write_audit(db, actor_type="user", actor_id=user.id, action=action,
                    target_type="host", target_id=h.id, result="denied",
                    params={"node": node, "is_self": self_node}, ip=ip)
        verb = "Rebooting" if body.command == "reboot" else "Powering off"
        detail = f"{verb} {node} cannot be undone once it starts. "
        if self_node:
            detail += (f"{node} is the node Proxploy itself runs on: this can end "
                       "Proxploy with no in-band way back, recovery would need "
                       "physical or IPMI access to the machine. ")
        detail += f"Type the node's name, {node}, to confirm."
        raise HTTPException(409, {"error": "confirm_required",
                                  "confirm_phrase": node, "is_self": self_node,
                                  "detail": detail})

    out = enqueue_and_audit(request, db, user, kind=action, target_type="host",
                            target_id=h.id,
                            params={"host_id": h.id, "node": node,
                                    "command": body.command, "is_self": self_node},
                            action=action)
    out["is_self"] = self_node
    return out


# The high byte of PVE's raw PCI class code is the PCI-SIG base class, the
# heading `lspci` prints. Named here, not in the UI, because it belongs to
# the protocol. An unrecognised byte falls back to the raw code rather than
# "Other", which would hide a class we have not listed yet.
_PCI_BASE_CLASS = {
    0x00: "Unclassified device", 0x01: "Mass storage controller",
    0x02: "Network controller", 0x03: "Display controller",
    0x04: "Multimedia controller", 0x05: "Memory controller",
    0x06: "Bridge", 0x07: "Communication controller",
    0x08: "Generic system peripheral", 0x09: "Input device controller",
    0x0A: "Docking station", 0x0B: "Processor",
    0x0C: "Serial bus controller", 0x0D: "Wireless controller",
    0x0E: "Intelligent controller", 0x0F: "Satellite communications controller",
    0x10: "Encryption controller", 0x11: "Signal processing controller",
    0x12: "Processing accelerator", 0x13: "Non-essential instrumentation",
}


def _pci_class_name(raw) -> str | None:
    if raw in (None, ""):
        return None
    try:
        code = int(str(raw), 16)
    except ValueError:
        return str(raw)
    # 0x030000 -> 0x03. A two-digit code (0x03) is already the base class.
    base = code >> 16 if code > 0xFF else code
    return _PCI_BASE_CLASS.get(base, str(raw))


def _disk_row(d: dict) -> dict:
    return {
        "devpath": d.get("devpath"), "model": d.get("model"),
        "serial": d.get("serial"), "size": d.get("size"), "type": d.get("type"),
        "health": d.get("health"), "wearout": d.get("wearout"),
        "used": d.get("used"),
        # PVE uses -1 for "not a Ceph OSD"; passed through, that reads as an
        # OSD id of minus one.
        "osd_id": None if d.get("osdid") in (None, -1) else d.get("osdid"),
    }


def _pci_row(p: dict) -> dict:
    return {
        "id": p.get("id"), "class_id": p.get("class"),
        "class_name": _pci_class_name(p.get("class")),
        "device_id": p.get("device"), "device_name": p.get("device_name"),
        "vendor_id": p.get("vendor"), "vendor_name": p.get("vendor_name"),
        "subsystem_vendor_name": p.get("subsystem_vendor_name"),
        # The group that decides whether this device can be handed to a guest
        # on its own. PVE spells it as one word.
        "iommu_group": p.get("iommugroup"),
    }


def _service_row(s: dict) -> dict:
    # systemd's keys are hyphenated, which no JS caller can address without
    # bracket syntax. Renamed once, here.
    return {
        "name": s.get("name") or s.get("service"), "desc": s.get("desc"),
        "state": s.get("state"), "active_state": s.get("active-state"),
        "unit_state": s.get("unit-state"),
    }


def _iface_row(n: dict) -> dict:
    # NOTE: /nodes/{n}/network carries no link speed. There is no field to
    # surface one from, so the tab does not claim one.
    return {
        "iface": n.get("iface"), "type": n.get("type"),
        "method": n.get("method"), "method6": n.get("method6"),
        "families": n.get("families") or [],
        "active": bool(n.get("active")), "exists": bool(n.get("exists")),
        "autostart": bool(n.get("autostart")),
        "cidr": n.get("cidr"), "gateway": n.get("gateway"),
        "bridge_ports": n.get("bridge_ports"),
        "altnames": n.get("altnames") or [],
    }


def _dns_row(d: dict) -> dict:
    # dns2/dns3 are ABSENT, not null, when unset. A fixed three-slot shape
    # would put two "unknown"s on the page for an ordinary resolver config.
    return {
        "servers": [d[k] for k in ("dns1", "dns2", "dns3") if d.get(k)],
        "search": d.get("search"),
    }


@router.get("/{host_id}/nodes/{node}/hardware")
def node_hardware(host_id: int, node: str, request: Request, db=Depends(get_db),
                  user: User = Depends(_read_scoped)):
    """Everything the node says about itself that is not on the Overview
    strip: disks, network, PCI devices, systemd services, subscription, DNS,
    time.

    Gathered INDEPENDENTLY, on purpose: each is separately refusable on a
    real node, a narrow token answers some and rejects others, and a PVE
    without a path 501s. One refusal returns that section as null and names
    it in `unreadable` rather than costing the tab its other six. The 502 is
    for nothing at all being readable: the node is down.
    """
    h = db.get(Host, host_id)
    if h is None:
        raise HTTPException(404, "no such host")
    try:
        cl = client_for_host(request.app, db, h)
    except ProxmoxError as e:
        raise HTTPException(502, {"error": e.kind, "detail": str(e)}) from e

    out: dict = {}
    unreadable: dict[str, dict] = {}

    def gather(name, call, shape):
        try:
            out[name] = shape(call())
        except ProxmoxError as e:
            out[name] = None
            unreadable[name] = {"error": e.kind, "detail": str(e)}

    def rows(shape):
        return lambda raw: [shape(x) for x in (raw or [])]

    gather("disks", lambda: cl.node_disks(node), rows(_disk_row))
    gather("network", lambda: cl.node_networks(node), rows(_iface_row))
    gather("pci", lambda: cl.node_pci(node), rows(_pci_row))
    gather("services", lambda: cl.node_services(node), rows(_service_row))
    gather("subscription", lambda: cl.node_subscription(node), lambda s: {
        # "notfound" is the ordinary state of an unsubscribed install. It is
        # passed through verbatim and the UI words it neutrally; nothing here
        # calls it an error.
        "status": (s or {}).get("status"), "message": (s or {}).get("message"),
        "level": (s or {}).get("level"), "server_id": (s or {}).get("serverid"),
    })
    gather("dns", lambda: cl.node_dns(node), lambda d: _dns_row(d or {}))
    gather("time", lambda: cl.node_time(node), lambda t: {
        "timezone": (t or {}).get("timezone"), "localtime": (t or {}).get("localtime"),
        "utc": (t or {}).get("time"),
    })

    if len(unreadable) == len(out):
        # Not one section came back. That is the node being unreachable, not a
        # narrow token, and seven "could not be read" cards would bury it.
        first = next(iter(unreadable.values()))
        raise HTTPException(502, first)

    out["unreadable"] = unreadable
    return out


@router.post("/{host_id}/credentials")
def rotate_credentials(request: Request, host_id: int, body: CredentialRotateIn,
                       db=Depends(get_db), user: User = Depends(_credentials)):
    """Replace a host's stored API token and/or SSH key.

    Owner-only. The new API token is verified against the node BEFORE it
    replaces the old one: storing an unusable credential would take the host
    offline with no way back except editing the database.
    """
    h = db.get(Host, host_id)
    if h is None:
        raise HTTPException(404, "host not found")
    ip = request.client.host if request.client else None
    rotated = []
    out: dict = {"id": h.id}

    if bool(body.token_id) != bool(body.token_secret):
        raise HTTPException(422, "token_id and token_secret must be given together")

    capability = body.capability
    if body.token_id and body.token_secret:
        try:
            ProxmoxClient(h.address, body.token_id, body.token_secret,
                          verify_tls=h.verify_tls,
                          tls_fingerprint=h.tls_fingerprint,
                          factory=request.app.state.proxmox_factory).version()
        except ProxmoxError as e:
            raise HTTPException(502, {
                "error": "token_rejected",
                "detail": f"the new token did not work against {h.address}, "
                          f"the old one is still in place: {e}"}) from e
        if capability is None:
            # Once a monitoring credential exists, guessing "monitoring" for
            # an unlabelled write is how a lifecycle/console/backup token
            # silently overwrote it, so the caller has to say which slot.
            has_monitoring = (db.query(HostCredential)
                              .filter_by(host_id=h.id, kind="api_token:monitoring")
                              .one_or_none() is not None)
            if has_monitoring:
                raise HTTPException(422, {
                    "error": "capability_required",
                    "detail": (f"{h.name} already has a monitoring token stored. "
                               f"Say which capability this new token is for "
                               f"(one of {', '.join(sorted(CAPABILITIES))}), so it "
                               f"cannot overwrite monitoring by accident."),
                })
            capability = "monitoring"
        blob, ver = request.app.state.secretstore.encrypt(jsonlib.dumps(
            {"token_id": body.token_id, "token_secret": body.token_secret}).encode())
        kind = f"api_token:{capability}"
        cred = (db.query(HostCredential)
                .filter_by(host_id=h.id, kind=kind).one_or_none())
        if cred is None:
            cred = HostCredential(host_id=h.id, kind=kind)
            db.add(cred)
        cred.encrypted_blob, cred.key_version = blob, ver
        cred.public_meta = token_public_meta(body.token_id)
        cred.last_used_at = utcnow()
        if capability == "monitoring":
            # Only monitoring's own connectivity/last_seen bookkeeping: a
            # lifecycle/console/backup rotation proves that ONE capability's
            # token works (the version() check above), not that the host's
            # overall reachability (what h.status reports) has changed.
            h.status, h.last_seen_at = "connected", utcnow()
        rotated.append(kind)

    if body.rotate_ssh:
        # generate_ed25519 returns bytes and the secretstore takes bytes, so
        # there is nothing to encode here.
        priv, pub = generate_ed25519(f"proxploy@{h.name}")
        blob, ver = request.app.state.secretstore.encrypt(priv)
        cred = (db.query(HostCredential)
                .filter_by(host_id=h.id, kind="ssh_key").one_or_none())
        if cred is None:
            cred = HostCredential(host_id=h.id, kind="ssh_key")
            db.add(cred)
        cred.encrypted_blob, cred.key_version = blob, ver
        cred.public_meta = pub
        # The new key is NOT authorized on the node yet, so enrolment starts
        # over: leaving the old verified_at would claim a working root shell
        # Proxploy no longer has.
        cred.ssh_verified_at = None
        rotated.append("ssh_key")
        out["public_key"] = pub
        out["consent_note"] = CONSENT_NOTE

    if not rotated:
        raise HTTPException(422, "nothing to rotate")

    db.commit()
    audit_params: dict = {"rotated": rotated}
    if body.token_id and body.token_secret:
        # Name the slot explicitly rather than making a reader parse it out of
        # the "api_token:<capability>" string in `rotated`.
        audit_params["capability"] = capability
    write_audit(db, actor_type="user", actor_id=user.id, action="host.credentials",
                target_type="host", target_id=h.id,
                params=audit_params, ip=ip)
    out["rotated"] = rotated
    return out


class PeerEnrolIn(BaseModel):
    """Node names, never an address.

    The addresses come from a fresh /cluster/status read inside the handler,
    so a hostile caller cannot aim an enrolment at a machine the cluster never
    named. There is deliberately no address field.

    `tls_fingerprints` can aim nothing anywhere, so it is allowed: node name
    to the fingerprint discovery displayed, used ONLY to refuse a node
    presenting something else by the time the operator confirms. Never
    pinned, never a fallback when the probe fails, never stored.
    """
    nodes: list[str]
    tls_fingerprints: dict[str, str] = {}

    @field_validator("nodes")
    @classmethod
    def _at_least_one(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("name at least one node to add")
        return v


@router.post("/{host_id}/peers")
def enrol_peers(request: Request, host_id: int, body: PeerEnrolIn,
                db=Depends(get_db), user: User = Depends(_credentials)):
    """Add the named nodes of this host's cluster as hosts of their own, each
    with its own copy of every API token this host holds.

    The write half of GET /{host_id}/peers, owner-scoped rather than admin
    because copying stored secrets into new rows is as severe as rotating
    them.

    One row per requested node, always 200: the flow is inherently partial,
    and a 502 would throw away the record of the peers that did work.

    Never copied: the ssh_key credential, install consent, the node shell
    opt-in. The SSH key is a root shell, a different trust decision from an
    API token, and keeping them separate is why this route exists at all.
    """
    h = db.get(Host, host_id)
    if h is None:
        raise HTTPException(404, "host not found")
    # A peer is never the first host, so unlike create_host the entitlement is
    # always required. Same body, so a caller has one shape to handle.
    if not request.app.state.entitlements.enabled("hosts.multi"):
        raise entitlement_error("hosts.multi")

    ss = request.app.state.secretstore
    ip = request.client.host if request.client else None
    results = [{"node": n, "status": "failed", "host_id": None, "address": None,
                "capabilities_stored": [], "capabilities_failed": [],
                "detail": None} for n in body.nodes]
    try:
        client = client_for_host(request.app, db, h)
        rows = client.cluster_status()
    except ProxmoxError as e:
        # Still 200 with a row per node: the caller asked about these nodes and
        # deserves an answer per node. Nothing was reached, so nothing is
        # written, and every row says the same true thing.
        for row in results:
            row["detail"] = (f"Proxploy could not read the cluster from {h.name}: "
                             f"{e}. Nothing was added and nothing was stored.")
        return {"results": results}

    cluster = next((r.get("name") for r in rows if r.get("type") == "cluster"), None)
    # Re-read once for the whole request: discovery and this call can be
    # minutes apart. The `cluster and` guard is list_peers's, for the same
    # reason: a standalone node's row carries no `local` flag on some versions.
    peers = {r.get("name"): r for r in rows
             if cluster and r.get("type") == "node" and not r.get("local")}
    # Pin the origin on the same code path its peers use, so two nodes of one
    # cluster never disagree about whether they are pinned. Only hosts enrolled
    # before pinning existed still have no pin.
    if not h.tls_fingerprint:
        h.tls_fingerprint = _fingerprint_now(h.address)
        db.commit()
    creds = {c.kind: c for c in db.query(HostCredential).filter_by(host_id=h.id)}
    api_addresses = _api_addresses(client)

    for row in results:
        node = row["node"]
        r = peers.get(node)
        if r is None:
            row["detail"] = (f"{node} is not one of the nodes {h.name} reports in "
                             f"its cluster right now, so it was not added. "
                             f"Nothing was stored.")
            continue
        # Same source and same fallback as discovery, so the address an
        # operator was shown is the address that gets enrolled.
        ip = api_addresses.get(node) or r.get("ip")
        row["address"] = address = f"https://{ip}:8006"
        # The skip rules, re-applied here rather than trusted from discovery:
        # cluster plus node name, never address. A NULL cluster_name counts
        # too, since adding the same machine twice is the worse failure.
        already = next((e for e in db.query(Host).filter(Host.id != h.id)
                        if e.node_name == node and e.cluster_name in (cluster, None)),
                       None)
        if already:
            row["status"] = "skipped"
            row["detail"] = (f"{node} is already in Proxploy as {already.name}. "
                             f"Nothing was stored.")
            continue
        # The skip rules already excluded the same machine, so a clash on
        # hosts.name is a different machine wearing the name. That peer fails
        # and the rest still enrol; no generated suffix, because a host wearing
        # a name that is not its node name is worse.
        clash = db.query(Host).filter_by(name=node).one_or_none()
        if clash:
            row["detail"] = (f"{node} was not added: Proxploy already has a "
                             f"different host called {node}, at {clash.address}. "
                             f"Nothing was stored. Rename that host, then add this "
                             f"node again. Any other nodes you ticked were still "
                             f"added.")
            continue

        # This peer's own certificate, never the origin's: cluster nodes serve
        # distinct ones, so an inherited pin would refuse every connection.
        # The pin always comes from this probe, never from what the caller
        # echoed back, which is only ever compared against it.
        fingerprint = _fingerprint_now(address)
        shown = body.tls_fingerprints.get(node)
        # Case-insensitively, the way _connect compares a stored pin. A probe
        # that could not read the certificate counts as a mismatch: the
        # operator approved a specific one and Proxploy cannot say this is it.
        if shown and (fingerprint or "").upper() != shown.upper():
            row["detail"] = (
                f"{node} is presenting a different TLS certificate than the one "
                f"shown a moment ago, so it was not added. Nothing was stored. "
                f"If you did not just replace its certificate, stop and "
                f"investigate. Shown then: {shown}. Presenting now: "
                f"{fingerprint or 'nothing Proxploy could read'}.")
            continue
        tok = jsonlib.loads(ss.decrypt(creds["api_token:monitoring"].encrypted_blob))
        peer_client = ProxmoxClient(address, tok["token_id"], tok["token_secret"],
                                    verify_tls=h.verify_tls,
                                    tls_fingerprint=fingerprint,
                                    factory=request.app.state.proxmox_factory)
        try:
            v = peer_client.version()
        except ProxmoxError as e:
            # Nothing is written either way: a host with no monitoring
            # credential cannot poll, and monitoring is the mandatory
            # capability.
            row["detail"] = (
                f"{node} at {ip} did not answer on port 8006, so it was "
                f"not added. Nothing was stored."
                if e.kind == "unreachable" else
                f"{node} refused the monitoring token, so it was not added. "
                f"Nothing was stored. Check that the token exists on that node "
                f"and that its permissions cover it.")
            continue

        peer = Host(name=node, address=address, verify_tls=h.verify_tls,
                    tls_fingerprint=fingerprint, status="connected",
                    node_name=node, cluster_name=cluster,
                    # Copied so a cluster is never half inside a team and half
                    # outside it. A teamless origin leaves the peer teamless.
                    team_id=h.team_id,
                    last_error=_privilege_note(_missing_privileges(peer_client)),
                    node_power_missing=None,
                    pve_version=v.get("version"), last_seen_at=utcnow())
        db.add(peer)
        db.commit()

        for cap in CAPABILITIES:
            cred = creds.get(f"api_token:{cap}")
            if cred is None:
                continue
            if cap != "monitoring":  # monitoring was verified just above
                t = jsonlib.loads(ss.decrypt(cred.encrypted_blob))
                try:
                    ProxmoxClient(address, t["token_id"], t["token_secret"],
                                  verify_tls=h.verify_tls,
                                  tls_fingerprint=fingerprint,
                                  factory=request.app.state.proxmox_factory).version()
                except ProxmoxError:
                    # The host stays enrolled and works for everything that did
                    # verify. A node that has left the cluster shows up exactly
                    # here, its copy of the token having drifted.
                    row["capabilities_failed"].append(cap)
                    continue
            # Same secret store and same key version, so the blob is copied as
            # it is: a decrypt and re-encrypt round trip would change nothing
            # except the number of places a plaintext secret exists.
            db.add(HostCredential(host_id=peer.id, kind=cred.kind,
                                  encrypted_blob=cred.encrypted_blob,
                                  key_version=cred.key_version,
                                  public_meta=cred.public_meta))
            row["capabilities_stored"].append(cap)
        db.commit()

        row["status"], row["host_id"] = "enrolled", peer.id
        if row["capabilities_failed"]:
            row["detail"] = " ".join(
                [f"{node} was added, and everything else was stored."]
                + [f"Proxmox on {node} refused the {cap} token, so "
                   f"{CAPABILITIES[cap].label} is not configured there. Add it "
                   f"from {node}'s Edit dialog once the token works on that node."
                   for cap in row["capabilities_failed"]])
        # The two existing action names, so the audit filters and the activity
        # feed's labels keep working with nothing new to register.
        write_audit(db, actor_type="user", actor_id=user.id, action="host.create",
                    target_type="host", target_id=peer.id,
                    params={"name": peer.name, "address": address, "node": node,
                            "via_host_id": h.id, "via_node": h.node_name}, ip=ip)
        for cap in row["capabilities_stored"]:
            write_audit(db, actor_type="user", actor_id=user.id,
                        action="host.credentials", target_type="host",
                        target_id=peer.id,
                        params={"capability": cap, "copied_from_host_id": h.id},
                        ip=ip)
    return {"results": results}


@router.post("/{host_id}/sync")
async def sync_host(request: Request, host_id: int, db=Depends(get_db),
                    user: User = Depends(_sync)):
    """Poll this host now instead of waiting out the interval.

    Runs the poller's own cycle rather than a parallel implementation, so a
    forced sync and a scheduled one cannot disagree about what they ingest.
    Operator-level: it changes no configuration, only cache.
    """
    import asyncio

    h = db.get(Host, host_id)
    if h is None:
        raise HTTPException(404, "host not found")
    poller = request.app.state.poller
    try:
        events = await asyncio.wait_for(
            asyncio.to_thread(poller._poll_once, host_id),
            timeout=request.app.state.settings.poll_timeout_s)
    except TimeoutError as e:
        raise HTTPException(504, {"error": "timeout",
                                  "detail": f"{h.name} did not answer in time"}) from e
    except ProxmoxError as e:
        raise HTTPException(502, {"error": "pve_error", "detail": str(e)}) from e
    for name, data in events:
        request.app.state.bus.publish(name, data)

    write_audit(db, actor_type="user", actor_id=user.id, action="host.sync",
                target_type="host", target_id=host_id,
                ip=request.client.host if request.client else None)
    with request.app.state.sessionmaker() as fresh:
        row = fresh.get(Host, host_id)
        return {"id": host_id, "status": row.status if row else None,
                "last_seen_at": to_iso(row.last_seen_at) if row else None,
                "events": len(events)}


@router.get("/{host_id}/tasks")
def host_tasks(request: Request, host_id: int, limit: int = 50,
               db=Depends(get_db), user: User = Depends(_read_scoped)):
    """The node's own task list, including work Proxploy did not start.

    Read-level on purpose: this is what the Proxmox UI shows anyone who can
    log in, and an operator debugging "why did my container restart at 3am"
    needs the tasks Proxploy did not cause.
    """
    h = db.get(Host, host_id)
    if h is None:
        raise HTTPException(404, "host not found")
    if limit < 1 or limit > 500:
        raise HTTPException(422, "limit must be between 1 and 500")
    from proxploy.services.hostclient import client_for_host
    try:
        client = client_for_host(request.app, db, h)
        rows = client.node_tasks(h.node_name or "", limit=limit)
    except ProxmoxError as e:
        raise HTTPException(502, {"error": "pve_error", "detail": str(e)}) from e
    return [{"upid": r.get("upid"), "type": r.get("type"), "id": r.get("id"),
             "node": r.get("node"), "user": r.get("user"),
             "status": r.get("status"), "exitstatus": r.get("exitstatus"),
             "starttime": r.get("starttime"), "endtime": r.get("endtime")}
            for r in rows]


@router.get("/{host_id}/tasks/{upid}/log")
def host_task_log(request: Request, host_id: int, upid: str, start: int = 0,
                  limit: int = 500, db=Depends(get_db),
                  user: User = Depends(_read_scoped)):
    """Passthrough of one PVE task log, the missing half of the task feature.

    Proxploy already archives the logs of tasks IT started, in job_events.
    This is for the ones it did not.
    """
    h = db.get(Host, host_id)
    if h is None:
        raise HTTPException(404, "host not found")
    from proxploy.services.hostclient import client_for_host
    try:
        client = client_for_host(request.app, db, h)
        rows = client.task_log(h.node_name or "", upid, start=start, limit=limit)
    except ProxmoxError as e:
        raise HTTPException(502, {"error": "pve_error", "detail": str(e)}) from e
    return {"upid": upid, "lines": [r.get("t", "") for r in rows]}
