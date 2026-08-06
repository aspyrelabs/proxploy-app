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
# repeated uses into one call per request. Only the actions this router's
# routes actually gate get a singleton here — host.sync/credentials/remove/
# console have no route in this file yet (doc 05 lists them; no task in the
# Phase 8 plan adds them), so no dead singleton for them either.
_read = authorize("host", "read")
_manage = authorize("host", "manage", scope_of=scope_host())
_manage_global = authorize("host", "manage")          # no host id yet (probe, create)

CONSENT_NOTE = ("This key gives Proxploy a root shell on the node, used only for "
                "App Store install/update/migration scripts — exactly as if you ran "
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


@router.post("/probe")
def probe(request: Request, body: ProbeIn,
          user: User = Depends(_manage_global)):
    try:
        v = _client(request, body).version()
    except ProxmoxError as e:
        raise HTTPException(502, {"error": e.kind, "detail": str(e)})
    return {"ok": True, "version": v.get("version"), "release": v.get("release")}


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
    try:
        v = _client(request, body).version()
    except ProxmoxError as e:
        write_audit(db, actor_type="user", actor_id=user.id, action="host.create",
                    params=audit_params, result="error",
                    ip=request.client.host if request.client else None)
        raise HTTPException(502, {"error": e.kind, "detail": str(e)})

    host = Host(name=body.name, address=body.address, verify_tls=body.verify_tls,
                tls_fingerprint=body.tls_fingerprint, status="connected",
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
           "status": host.status}
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
    — does the key authenticate and can we run anything — and nothing else.
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
