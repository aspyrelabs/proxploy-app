"""Host onboarding. ROUTE TEMPLATE (doc 10 Phase 1 DoD): every mutation stacks
auth -> RBAC stub -> entitlement -> work -> audit. Later phases copy this shape."""
import json as jsonlib

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, field_validator

from proxploy.api.deps import authorize, get_db, scope_host
from proxploy.api.jobs import enqueue_and_audit
from proxploy.models import Host, HostCredential, Team, User, to_iso, utcnow
from proxploy.services.audit import write_audit
from proxploy.executor import SSHExecutor, SSHHostKeyMismatch
from proxploy.services.proxmox import (ProxmoxClient, ProxmoxError, parse_token_id,
                                       token_public_meta)
from proxploy.services.hostclient import client_for_host, cluster_identity
from proxploy.services.selfguard import is_self_host_node
from proxploy.services.sshkeys import generate_ed25519

router = APIRouter(prefix="/hosts", tags=["hosts"])

# Singletons so FastAPI's dependency cache (keyed on the callable) collapses
# repeated uses into one call per request.
#
# This comment used to say host.sync/credentials/remove had no route here yet
# and that no plan added them. They exist now (see the bottom of this file,
# PXP-17); host.console is elsewhere, on the node-shell ticket route in
# api/consoles.py.
_read = authorize("host", "read")                      # no host id yet (list)
_read_scoped = authorize("host", "read", scope_of=scope_host())
_manage = authorize("host", "manage", scope_of=scope_host())
_manage_global = authorize("host", "manage")          # no host id yet (probe, create)

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
    changed. Started as just the node-shell opt-in toggle (doc 08 §9) plus
    team assignment; name/address joined for the host actions menu's Edit
    dialog. Credentials are deliberately NOT here -- POST
    /{host_id}/credentials is their own dedicated, already-existing flow
    (verifies a new token against the node before it replaces the old one),
    and the Edit dialog composes both calls rather than this route growing a
    second credential path."""
    node_shell_enabled: bool | None = None
    team_id: int | None = None
    name: str | None = None
    address: str | None = None

    @field_validator("name", "address")
    @classmethod
    def _not_blank(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            raise ValueError("cannot be blank")
        return v


def _client(request: Request, body: ProbeIn) -> ProxmoxClient:
    return ProxmoxClient(body.address, body.token_id, body.token_secret,
                         verify_tls=body.verify_tls,
                         tls_fingerprint=body.tls_fingerprint,
                         factory=request.app.state.proxmox_factory)


# Doc 08's ProxployAudit role: the read-only monitoring set, required for the
# poller to complete a cycle at all. Deliberately only this set: the lifecycle,
# console and backup roles gate optional features, and a token without them
# should still enrol.
#
# Imported from services/pveum, which is also what generates the script that
# creates these tokens. One table, so a token the wizard tells you to make
# always satisfies the check the wizard then runs against it.
from proxploy.services.pveum import (CAPABILITIES, MONITORING_PRIVILEGES,
                                     NODE_POWER_PRIVILEGE, generate_script)


def _granted_privileges(client) -> set[str] | None:
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


def _missing_privileges(client) -> list[str] | None:
    """Which monitoring privileges this token does not hold anywhere.

    None means "could not tell", which is NOT the same as "none missing": some
    setups refuse /access/permissions to a token, and reporting unknown as a
    clean bill of health is how this failed silently in the first place.

    A privilege granted on any path counts. Doc 08 supports scoping Proxploy to
    a pool by granting the roles on /pool/<name> instead of /, so requiring
    them at "/" would report a working pool-scoped install as broken.
    """
    granted = _granted_privileges(client)
    if granted is None:
        return None
    return [p for p in MONITORING_PRIVILEGES if p not in granted]


def _node_power_missing(client) -> bool | None:
    """Whether this token lacks Sys.PowerMgmt anywhere. None means "could not
    tell", same reasoning as _missing_privileges.

    Checked unconditionally, unlike Lifecycle/Console/Backup: the host
    actions menu offers Reboot/Power off on every host regardless of which
    optional capabilities were chosen, so this is checked the same way
    monitoring is, not gated behind an opt-in capability having been picked.
    """
    granted = _granted_privileges(client)
    if granted is None:
        return None
    return NODE_POWER_PRIVILEGE not in granted


def _capability_state(kinds) -> dict[str, bool]:
    """Which capability tokens this host holds. Presence only.

    Never the token, the token id, or any part of the blob: the UI needs to
    know whether a capability is configured and nothing more. Keyed off
    CAPABILITIES so a capability added to services/pveum.py appears here
    with no second list to maintain, and a host with no credential rows
    reports every capability False rather than omitting the field.
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
    node_shell: bool = False
    # Independent of `capabilities` (services/pveum.py's own docstring on
    # NODE_POWER_PRIVILEGE): Sys.PowerMgmt gets its own role and token, not an
    # augmentation of Lifecycle's, and is not conditional on Lifecycle being
    # among `capabilities`.
    node_power: bool = False


@router.post("/token-script")
def token_script(body: TokenScriptIn, user: User = Depends(_manage_global)):
    """The copy-paste pveum script from doc 08 §2.

    POST rather than GET for the structured body, following /probe: it reads
    nothing and changes nothing on this side. The operator runs the result in
    a node shell they already own, which is the whole point: Proxploy never
    asks for root credentials, even transiently.
    """
    try:
        script = generate_script(body.capabilities, path=body.path,
                                 node_shell=body.node_shell,
                                 node_power=body.node_power)
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
    # /version succeeds for a privsep token holding no ACLs at all, so on its
    # own it proves only that the address and secret are right. The privilege
    # diff is what makes "Test connection" mean the thing operators read it as.
    return {"ok": True, "version": v.get("version"), "release": v.get("release"),
            "missing_privileges": _missing_privileges(client),
            "node_power_missing": _node_power_missing(client)}


@router.post("", status_code=201)
def create_host(request: Request, body: HostIn, db=Depends(get_db),
                user: User = Depends(_manage_global)):
    ent = request.app.state.entitlements
    if db.query(Host).count() >= 1 and not ent.enabled("hosts.multi"):
        raise HTTPException(403, {"error": "entitlement_required",
                                  "feature": "hosts.multi"})
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
        write_audit(db, actor_type="user", actor_id=user.id, action="host.create",
                    params=audit_params, result="error",
                    ip=request.client.host if request.client else None)
        raise HTTPException(502, {"error": e.kind, "detail": str(e)})

    # Checked at enrolment, not left for the poller to discover minutes later
    # as a bare "unreachable". Recorded rather than refused: an under-privileged
    # token is still worth enrolling, and locking an operator out of their own
    # host at the final step is the worse failure.
    missing = _missing_privileges(client)
    node_power_missing = _node_power_missing(client)
    try:
        node_name, cluster_name = cluster_identity(client)
    except ProxmoxError:  # enrolment must survive a probe hiccup
        node_name = cluster_name = None
    host = Host(name=body.name, address=body.address, verify_tls=body.verify_tls,
                tls_fingerprint=body.tls_fingerprint, status="connected",
                node_name=node_name, cluster_name=cluster_name,
                last_error=_privilege_note(missing),
                node_power_missing=node_power_missing,
                pve_version=v.get("version"), last_seen_at=utcnow())
    db.add(host)
    db.commit()

    ss = request.app.state.secretstore
    blob, ver = ss.encrypt(jsonlib.dumps(
        {"token_id": body.token_id, "token_secret": body.token_secret}).encode())
    # Enrolment always creates the "monitoring" row: it is the one mandatory
    # capability (CAPABILITIES["monitoring"].required, services/pveum.py),
    # and there is only one token pasted at this step of the wizard.
    # Lifecycle/console/backup tokens are added later via
    # POST /hosts/{id}/credentials (CredentialRotateIn.capability), a later
    # step's UI work, not this one.
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
             "node_name": h.node_name, "status": h.status,
             "last_error": h.last_error,
             "pve_version": h.pve_version, "node_shell_enabled": h.node_shell_enabled,
             "node_power_missing": h.node_power_missing,
             "team_id": h.team_id,
             # The install dialog's Default mode reads these to decide
             # whether it has already learned this host's storage pools
             # (Task 13): a value here means the question was asked once and
             # is now shown rather than asked again.
             "default_container_storage": h.default_container_storage,
             "default_template_storage": h.default_template_storage,
             # Same reason (Task 6): the install dialog asks the root-execution
             # tick only while this is null. Re-asking a host that already
             # acknowledged surfaces no new information, it is just friction.
             "install_consent_at": to_iso(h.install_consent_at),
             "capabilities": _capability_state(kinds.get(h.id, ())),
             "last_seen_at": to_iso(h.last_seen_at)}
            for h in db.query(Host).order_by(Host.id)]


@router.get("/capabilities")
def list_capabilities(user: User = Depends(_read)):
    """The static catalogue of optional capabilities the setup script can
    grant (key, label, why it matters, whether it is required), for the
    frontend to tell an operator what they give up by unticking one.

    Registered ABOVE the /{host_id} wildcard below: Starlette matches in
    registration order, and out of order this literal path would be
    swallowed by GET /{host_id} with host_id="capabilities" (same WARNING
    as api/vms.py's /{vm_id}/{action} ordering hazard). Confirmed by
    test_capabilities_route_is_not_shadowed_by_the_host_id_wildcard.

    Derived straight from CAPABILITIES, list not dict, so declaration order
    (monitoring first) survives into the response, and a capability added
    there needs no edit here. privileges/role/token are deliberately left
    off: the UI only needs why a capability matters, not the PVE privilege
    names or the identifiers that build the script.
    """
    return [{"key": c.key, "label": c.label, "why": c.why, "required": c.required}
            for c in CAPABILITIES.values()]


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
            "node_power_missing": h.node_power_missing, "team_id": h.team_id,
            "capabilities": _capability_state(c.kind for c in creds),
            "credentials": [{"kind": c.kind, "public_meta": c.public_meta,
                             "last_used_at": to_iso(c.last_used_at)} for c in creds]}


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
    # null have to mean different things. Without it the Settings picker's
    # "Unassigned" option was unimplementable, and a host could be moved
    # between teams but never out of one.
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
    db.commit()
    # Same action name as before when only the node-shell toggle (plus,
    # historically, team assignment) changed -- test_patch_host_writes_an_
    # audit_event pins that exact string. A name/address change is different
    # enough in kind (identity, not a feature flag) to get its own name.
    action = ("host.update" if {"name", "address"} & audit_params.keys()
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
    try:
        client = ProxmoxClient(h.address, tok["token_id"], tok["token_secret"],
                               verify_tls=h.verify_tls, tls_fingerprint=h.tls_fingerprint,
                               factory=request.app.state.proxmox_factory)
        v = client.version()
        h.status, h.pve_version, h.last_seen_at = "connected", v.get("version"), utcnow()
        # Same re-check reachability already got: an operator who just ran
        # the extra pveum commands for node power should see it reflected
        # here, not only on the next full enrolment.
        h.node_power_missing = _node_power_missing(client)
        cred.last_used_at = utcnow()
        result = "ok"
    except ProxmoxError:
        h.status, result = "unreachable", "error"
    db.commit()
    write_audit(db, actor_type="user", actor_id=user.id, action="host.test",
                target_type="host", target_id=h.id, result=result)
    return {"id": h.id, "status": h.status, "pve_version": h.pve_version,
            "node_power_missing": h.node_power_missing}


@router.post("/{host_id}/ssh/verify")
async def verify_ssh(host_id: int, request: Request, db=Depends(get_db),
                     user: User = Depends(_manage)):
    """Prove the enrolled key actually opens a root shell on the node.

    The wizard used to take the operator's word for it, so a mis-pasted
    authorized_keys line surfaced at the first app install instead of here,
    far from its cause. `true` is the whole command: this asks one question
    does the key authenticate and can we run anything, and nothing else.
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
        raise HTTPException(502, {"error": "host_key_mismatch", "detail": str(e)})
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


# --- removal, credential rotation, forced sync, task passthrough (PXP-17) ---
# doc 05 lists host.sync / host.credentials / host.remove and the authz matrix
# has carried all three since Phase 1; no phase ever added the routes. The
# header comment above used to say so.

_sync = authorize("host", "sync", scope_of=scope_host())
_credentials = authorize("host", "credentials", scope_of=scope_host())
_remove = authorize("host", "remove", scope_of=scope_host())
_power = authorize("host", "power", scope_of=scope_host())


class HostRemoveIn(BaseModel):
    confirm: str | None = None
    # apps.host_id is ON DELETE RESTRICT, so a host with apps cannot simply be
    # dropped. This forgets those app rows (the containers keep running and are
    # untouched); destroying a container is app uninstall's job, never a
    # side effect of removing a host.
    forget_apps: bool = False


class CredentialRotateIn(BaseModel):
    # Rotate the API token: supply the new one, Proxploy never mints PVE
    # credentials for you.
    token_id: str | None = None
    token_secret: str | None = None
    # Which capability's token this is. Defaults to "monitoring" so every
    # caller written before per-capability tokens existed (the single-token
    # model) keeps rotating the same row it always did with no request
    # change required. Validated against CAPABILITIES the same place
    # token_script's `capabilities` list already is (ValueError -> 422),
    # not against a separate hand-kept list that could drift from it.
    capability: str = "monitoring"
    # Regenerate the SSH keypair in-process. The new public key has to be
    # authorized on the node before installs work again, which is why the
    # response hands it back with the same consent note onboarding uses.
    rotate_ssh: bool = False

    @field_validator("capability")
    @classmethod
    def _known_capability(cls, v: str) -> str:
        if v not in CAPABILITIES:
            raise ValueError(f"capability must be one of "
                             f"{', '.join(sorted(CAPABILITIES))}")
        return v


@router.delete("/{host_id}")
def remove_host(request: Request, host_id: int,
                body: HostRemoveIn = None, db=Depends(get_db),
                user: User = Depends(_remove)):
    """Forget a host and everything Proxploy cached about it.

    Owner-only (authz matrix), and gated on typing the host name back: this
    drops every app row, VM cache row and stored credential for the host in one
    call, and the SSH key it deletes cannot be recovered, only re-enrolled.
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

    write_audit(db, actor_type="user", actor_id=user.id, action="host.remove",
                target_type="host", target_id=h.id,
                params={"name": h.name, "forgot_apps": len(apps),
                        "was_own_host": is_own_host}, ip=ip)
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

    On demand, never from the poll loop: doc 02 §3 caps a cycle at O(nodes),
    and model/cores/kernel/boot mode do not change between polls. The volatile
    figures here (load, wait, memory) are already recorded as metric samples
    every cycle, so polling this would buy nothing and cost a call per node.
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
        # The host actions menu's Reboot/Power off reads this off the SAME
        # query the identity rail already fetches, so the confirm dialog can
        # warn BEFORE the operator types anything, not only after a rejected
        # call (doc 02 §9, doc 08 §1).
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
            # `threads` here so the UI never has to guess which of the two
            # numbers is which, which is exactly what "cores" vs "cpus" invites.
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
    # Always required, self or not (doc 02 §9, doc 08 §1/§9 row 14): detection
    # can miss (a relocated install, an ambiguous hostname), so the typed
    # prompt is the backstop even when self-detection would have said no.
    # The frontend already gates Confirm on this matching before it ever
    # sends the request; this is the server-side half of that gate, not
    # merely a UI nicety.
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
    """Reboot or power off a Proxmox NODE, not a guest (doc 02 §9, doc 08 §1
    and §9 row 14).

    Owner-gated, same severity class as host.remove/host.credentials: this can
    take the whole node, and every guest it hosts, down. Always requires
    typing the node's name back, self or not -- GET .../status's `is_self`
    field lets the confirm dialog say so explicitly BEFORE the operator types
    anything, but the server enforces the same gate regardless of what the
    client already showed, since detection can miss.

    The actual PVE call runs as a job (services/guestjobs.py::run_host_power),
    the same reasoning as every other destructive PVE action: a synchronous
    200 with a bare UPID left this with no transcript in `job_events` and
    nothing to show in the bell popover (GET /jobs), unlike every other
    action in the product. The confirmation gate above still runs BEFORE
    anything is enqueued and is unchanged by the move.
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


# The high byte of PVE's raw PCI class code is the PCI-SIG base class, i.e.
# the heading `lspci` prints. Eleven devices as one flat list is a wall of
# hex; grouped by this they are four or five short groups. Named here rather
# than in the UI because it is a property of the protocol, not of the page,
# and an unrecognised byte falls back to the raw code instead of "Other",
# which would hide a device class we simply have not listed yet.
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
    """Everything the node will say about itself that is not already on the
    Overview strip: disks, network interfaces, PCI devices, systemd services,
    and the subscription/DNS/time facts.

    Gathered INDEPENDENTLY, on purpose. Each of these is separately refusable
    on a real node — a token with a narrow privilege set answers some and
    rejects others, and a PVE without a given path 501s — so one refusal
    returns that section as null and names it in `unreadable` rather than
    costing the tab its other six sections. The 502 is reserved for the case
    where nothing at all could be read, which is the node being down.
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
    replaces the old one: a rotation that stores an unusable credential would
    take the host offline with no way back except editing the database.
    """
    h = db.get(Host, host_id)
    if h is None:
        raise HTTPException(404, "host not found")
    ip = request.client.host if request.client else None
    rotated = []
    out: dict = {"id": h.id}

    if bool(body.token_id) != bool(body.token_secret):
        raise HTTPException(422, "token_id and token_secret must be given together")

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
        blob, ver = request.app.state.secretstore.encrypt(jsonlib.dumps(
            {"token_id": body.token_id, "token_secret": body.token_secret}).encode())
        kind = f"api_token:{body.capability}"
        cred = (db.query(HostCredential)
                .filter_by(host_id=h.id, kind=kind).one_or_none())
        if cred is None:
            cred = HostCredential(host_id=h.id, kind=kind)
            db.add(cred)
        cred.encrypted_blob, cred.key_version = blob, ver
        cred.public_meta = token_public_meta(body.token_id)
        cred.last_used_at = utcnow()
        if body.capability == "monitoring":
            # Only monitoring's own connectivity/last_seen bookkeeping: a
            # lifecycle/console/backup rotation proves that ONE capability's
            # token works (the version() check above), not that the host's
            # overall reachability (what h.status reports) has changed.
            h.status, h.last_seen_at = "connected", utcnow()
        rotated.append(kind)

    if body.rotate_ssh:
        # generate_ed25519 returns the private half as bytes already; the
        # secretstore takes bytes, so there is nothing to encode here.
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
    write_audit(db, actor_type="user", actor_id=user.id, action="host.credentials",
                target_type="host", target_id=h.id,
                params={"rotated": rotated}, ip=ip)
    out["rotated"] = rotated
    return out


@router.post("/{host_id}/sync")
async def sync_host(request: Request, host_id: int, db=Depends(get_db),
                    user: User = Depends(_sync)):
    """Poll this host now instead of waiting out the interval.

    Runs the poller's own cycle rather than a parallel implementation, so a
    forced sync and a scheduled one cannot disagree about what they ingest.
    Operator-level: it changes no configuration, it only refreshes cache.
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

    Read-level on purpose: this is the same information the Proxmox UI shows
    anyone who can log in, and an operator debugging "why did my container
    restart at 3am" needs the tasks Proxploy did not cause.
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
