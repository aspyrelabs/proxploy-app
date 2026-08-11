"""Host onboarding. ROUTE TEMPLATE (doc 10 Phase 1 DoD): every mutation stacks
auth -> RBAC stub -> entitlement -> work -> audit. Later phases copy this shape."""
import json as jsonlib

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, field_validator

from proxploy.api.deps import authorize, get_db, scope_host
from proxploy.models import Host, HostCredential, Team, User, utcnow
from proxploy.services.audit import write_audit
from proxploy.executor import SSHExecutor, SSHHostKeyMismatch
from proxploy.services.proxmox import (ProxmoxClient, ProxmoxError, parse_token_id,
                                       token_public_meta)
from proxploy.services.sshkeys import generate_ed25519

router = APIRouter(prefix="/hosts", tags=["hosts"])

# Singletons so FastAPI's dependency cache (keyed on the callable) collapses
# repeated uses into one call per request.
#
# This comment used to say host.sync/credentials/remove had no route here yet
# and that no plan added them. They exist now (see the bottom of this file,
# PXP-17); host.console is elsewhere, on the node-shell ticket route in
# api/consoles.py.
_read = authorize("host", "read")
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
    """Not a general host-update endpoint (name/address/credentials all go
    through their own dedicated flows) -- just the node-shell opt-in toggle
    (doc 08 §9) plus team assignment (doc 05 "team assignment")."""
    node_shell_enabled: bool
    team_id: int | None = None


def _client(request: Request, body: ProbeIn) -> ProxmoxClient:
    return ProxmoxClient(body.address, body.token_id, body.token_secret,
                         verify_tls=body.verify_tls,
                         tls_fingerprint=body.tls_fingerprint,
                         factory=request.app.state.proxmox_factory)


# Doc 08's ProxployAudit role: the read-only monitoring set, required for the
# poller to complete a cycle at all. Deliberately only this set: the lifecycle,
# console and backup roles gate optional features, and a token without them
# should still enrol.
MONITORING_PRIVILEGES = ("VM.Audit", "Datastore.Audit", "Sys.Audit",
                         "Pool.Audit", "SDN.Audit")


def _missing_privileges(client) -> list[str] | None:
    """Which monitoring privileges this token does not hold anywhere.

    None means "could not tell", which is NOT the same as "none missing": some
    setups refuse /access/permissions to a token, and reporting unknown as a
    clean bill of health is how this failed silently in the first place.

    A privilege granted on any path counts. Doc 08 supports scoping Proxploy to
    a pool by granting the roles on /pool/<name> instead of /, so requiring
    them at "/" would report a working pool-scoped install as broken.
    """
    try:
        granted: set[str] = set()
        for privs in (client.permissions() or {}).values():
            granted.update(p for p, on in (privs or {}).items() if on)
    except Exception:  # noqa: BLE001  (unknown, never fatal)
        return None
    return [p for p in MONITORING_PRIVILEGES if p not in granted]


def _privilege_note(missing: list[str] | None) -> str | None:
    if not missing:
        return None
    return ("the API token is missing " + ", ".join(missing)
            + ". Monitoring reads will fail until these are granted; see "
              "docs.proxploy.com/getting-started/proxmox-token")


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
            "missing_privileges": _missing_privileges(client)}


def _local_node_name(client) -> str | None:
    """Which node this address actually is, asked at enrolment time.

    Without this the column stayed NULL until the poller's first cycle landed,
    and every job handler reads `host.node_name or ""`, so anything started in
    that window sent an EMPTY node name to PVE and failed for a reason the
    operator could not act on. Enrolling a host and immediately installing
    something is not an exotic sequence; it is the obvious one.

    `/cluster/status` is the only honest answer: on a cluster it marks the node
    you are talking to with `local: 1`, which a `/nodes` listing cannot tell
    you. A standalone node returns exactly one node row. Anything unexpected
    leaves it NULL and the poller fills it in as before, so a surprising
    cluster shape can never block enrolment.
    """
    try:
        rows = [r for r in client.cluster_status() if r.get("type") == "node"]
    except Exception:  # noqa: BLE001  (enrolment must survive a probe hiccup)
        return None
    if len(rows) == 1:
        return rows[0].get("name")
    for r in rows:
        if r.get("local"):
            return r.get("name")
    return None


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
    host = Host(name=body.name, address=body.address, verify_tls=body.verify_tls,
                tls_fingerprint=body.tls_fingerprint, status="connected",
                node_name=_local_node_name(client),
                last_error=_privilege_note(missing),
                pve_version=v.get("version"), last_seen_at=utcnow())
    db.add(host)
    db.commit()

    ss = request.app.state.secretstore
    blob, ver = ss.encrypt(jsonlib.dumps(
        {"token_id": body.token_id, "token_secret": body.token_secret}).encode())
    db.add(HostCredential(host_id=host.id, kind="api_token", encrypted_blob=blob,
                          key_version=ver,
                          public_meta=token_public_meta(body.token_id)))

    out = {"id": host.id, "name": host.name, "address": host.address,
           "node_name": host.node_name, "pve_version": host.pve_version,
           "status": host.status, "missing_privileges": missing}
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
    return [{"id": h.id, "name": h.name, "address": h.address,
             "node_name": h.node_name, "status": h.status,
             "last_error": h.last_error,
             "pve_version": h.pve_version, "node_shell_enabled": h.node_shell_enabled,
             "team_id": h.team_id,
             "last_seen_at": h.last_seen_at.isoformat() if h.last_seen_at else None}
            for h in db.query(Host).order_by(Host.id)]


@router.get("/{host_id}")
def host_detail(host_id: int, db=Depends(get_db),
                user: User = Depends(_read)):
    h = db.get(Host, host_id)
    if not h:
        raise HTTPException(404, "no such host")
    creds = db.query(HostCredential).filter_by(host_id=h.id)
    return {"id": h.id, "name": h.name, "address": h.address,
            "node_name": h.node_name, "status": h.status,
            "last_error": h.last_error,
            "pve_version": h.pve_version, "verify_tls": h.verify_tls,
            "node_shell_enabled": h.node_shell_enabled, "team_id": h.team_id,
            "credentials": [{"kind": c.kind, "public_meta": c.public_meta,
                             "last_used_at": c.last_used_at.isoformat()
                             if c.last_used_at else None} for c in creds]}


@router.patch("/{host_id}")
def patch_host(host_id: int, body: HostPatchIn, db=Depends(get_db),
              user: User = Depends(_manage)):
    h = db.get(Host, host_id)
    if h is None:
        raise HTTPException(404, "host not found")
    h.node_shell_enabled = body.node_shell_enabled
    audit_params = {"node_shell_enabled": h.node_shell_enabled}
    if body.team_id is not None:
        if not db.get(Team, body.team_id):
            raise HTTPException(404, "team not found")
        h.team_id = body.team_id
        audit_params["team_id"] = body.team_id
    db.commit()
    write_audit(db, actor_type="user", actor_id=user.id,
                action="host.node_shell_toggle", target_type="host",
                target_id=h.id, params=audit_params)
    return {"id": h.id, "node_shell_enabled": h.node_shell_enabled}


@router.post("/{host_id}/test")
def test_host(request: Request, host_id: int, db=Depends(get_db),
              user: User = Depends(_manage)):
    h = db.get(Host, host_id)
    if not h:
        raise HTTPException(404, "no such host")
    cred = db.query(HostCredential).filter_by(host_id=h.id, kind="api_token").one()
    tok = jsonlib.loads(request.app.state.secretstore.decrypt(cred.encrypted_blob))
    try:
        v = ProxmoxClient(h.address, tok["token_id"], tok["token_secret"],
                          verify_tls=h.verify_tls, tls_fingerprint=h.tls_fingerprint,
                          factory=request.app.state.proxmox_factory).version()
        h.status, h.pve_version, h.last_seen_at = "connected", v.get("version"), utcnow()
        cred.last_used_at = utcnow()
        result = "ok"
    except ProxmoxError:
        h.status, result = "unreachable", "error"
    db.commit()
    write_audit(db, actor_type="user", actor_id=user.id, action="host.test",
                target_type="host", target_id=h.id, result=result)
    return {"id": h.id, "status": h.status, "pve_version": h.pve_version}


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
    return {"verified": True, "verified_at": cred.ssh_verified_at.isoformat()}


# --- removal, credential rotation, forced sync, task passthrough (PXP-17) ---
# doc 05 lists host.sync / host.credentials / host.remove and the authz matrix
# has carried all three since Phase 1; no phase ever added the routes. The
# header comment above used to say so.

_sync = authorize("host", "sync", scope_of=scope_host())
_credentials = authorize("host", "credentials", scope_of=scope_host())
_remove = authorize("host", "remove", scope_of=scope_host())


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
    # Regenerate the SSH keypair in-process. The new public key has to be
    # authorized on the node before installs work again, which is why the
    # response hands it back with the same consent note onboarding uses.
    rotate_ssh: bool = False


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
        cred = (db.query(HostCredential)
                .filter_by(host_id=h.id, kind="api_token").one_or_none())
        if cred is None:
            cred = HostCredential(host_id=h.id, kind="api_token")
            db.add(cred)
        cred.encrypted_blob, cred.key_version = blob, ver
        cred.public_meta = token_public_meta(body.token_id)
        cred.last_used_at = utcnow()
        h.status, h.last_seen_at = "connected", utcnow()
        rotated.append("api_token")

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
                "last_seen_at": row.last_seen_at.isoformat()
                if row and row.last_seen_at else None,
                "events": len(events)}


@router.get("/{host_id}/tasks")
def host_tasks(request: Request, host_id: int, limit: int = 50,
               db=Depends(get_db), user: User = Depends(_read)):
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
                  user: User = Depends(_read)):
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
