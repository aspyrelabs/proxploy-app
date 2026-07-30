"""Host onboarding. ROUTE TEMPLATE (doc 10 Phase 1 DoD): every mutation stacks
auth -> RBAC stub -> entitlement -> work -> audit. Later phases copy this shape."""
import json as jsonlib

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, field_validator

from proxploy.api.deps import get_db, require_role
from proxploy.models import Host, HostCredential, User, utcnow
from proxploy.services.audit import write_audit
from proxploy.services.proxmox import (ProxmoxClient, ProxmoxError, parse_token_id,
                                       token_public_meta)
from proxploy.services.sshkeys import generate_ed25519

router = APIRouter(prefix="/hosts", tags=["hosts"])

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
    """The only editable field, deliberately -- this is not a general
    host-update endpoint (name/address/credentials all go through their own
    dedicated flows), just the node-shell opt-in toggle (doc 08 §9)."""
    node_shell_enabled: bool


def _client(request: Request, body: ProbeIn) -> ProxmoxClient:
    return ProxmoxClient(body.address, body.token_id, body.token_secret,
                         verify_tls=body.verify_tls,
                         tls_fingerprint=body.tls_fingerprint,
                         factory=request.app.state.proxmox_factory)


@router.post("/probe")
def probe(request: Request, body: ProbeIn,
          user: User = Depends(require_role("admin"))):
    try:
        v = _client(request, body).version()
    except ProxmoxError as e:
        raise HTTPException(502, str(e))
    return {"ok": True, "version": v.get("version"), "release": v.get("release")}


@router.post("", status_code=201)
def create_host(request: Request, body: HostIn, db=Depends(get_db),
                user: User = Depends(require_role("admin"))):
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
        raise HTTPException(502, str(e))

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
def list_hosts(db=Depends(get_db), user: User = Depends(require_role("viewer"))):
    return [{"id": h.id, "name": h.name, "address": h.address,
             "node_name": h.node_name, "status": h.status,
             "pve_version": h.pve_version,
             "last_seen_at": h.last_seen_at.isoformat() if h.last_seen_at else None}
            for h in db.query(Host).order_by(Host.id)]


@router.get("/{host_id}")
def host_detail(host_id: int, db=Depends(get_db),
                user: User = Depends(require_role("viewer"))):
    h = db.get(Host, host_id)
    if not h:
        raise HTTPException(404, "no such host")
    creds = db.query(HostCredential).filter_by(host_id=h.id)
    return {"id": h.id, "name": h.name, "address": h.address,
            "node_name": h.node_name, "status": h.status,
            "pve_version": h.pve_version, "verify_tls": h.verify_tls,
            "credentials": [{"kind": c.kind, "public_meta": c.public_meta,
                             "last_used_at": c.last_used_at.isoformat()
                             if c.last_used_at else None} for c in creds]}


@router.patch("/{host_id}")
def patch_host(host_id: int, body: HostPatchIn, db=Depends(get_db),
              user: User = Depends(require_role("admin"))):
    h = db.get(Host, host_id)
    if h is None:
        raise HTTPException(404, "host not found")
    h.node_shell_enabled = body.node_shell_enabled
    db.commit()
    return {"id": h.id, "node_shell_enabled": h.node_shell_enabled}


@router.post("/{host_id}/test")
def test_host(request: Request, host_id: int, db=Depends(get_db),
              user: User = Depends(require_role("admin"))):
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
