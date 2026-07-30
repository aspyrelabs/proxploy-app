"""Console ticket + websocket routes (doc 05 §2/§3, doc 02 §5 PtyBridge/
ConsoleProxy). Every ticket-issuing POST is a normal cookie+CSRF+entitlement
route; every WS route below takes NO cookie — the one-time ticket already
proves auth (doc 05 "Auth model for streams"), so these follow jobs.py's
"manual auth inside the handler" idiom only where the SSE precedent doesn't
apply (session auth is not needed at all on the WS side)."""
from __future__ import annotations

import json as jsonlib

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket
from fastapi.websockets import WebSocketDisconnect

from proxploy.api.deps import get_db, require_entitlement, require_role
from proxploy.models import App, Host, HostCredential, User, Vm
from proxploy.services import ptybridge
from proxploy.services.audit import write_audit
from proxploy.services.consoleproxy import bridge_binary, connect_upstream_vnc
from proxploy.services.consoletickets import mint_ticket, redeem_ticket
from proxploy.services.ptybridge import PtyBridgeError, bridge_pty
from proxploy.services.proxmox import ProxmoxClient

router = APIRouter(tags=["consoles"])


def _proxmox_client_for_host(app_state, db, host: Host) -> ProxmoxClient:
    """Same three-line decrypt-then-construct pattern as services/lifecycle.py's
    _resolve and api/hosts.py's test_host — kept inline rather than extracted,
    matching this codebase's existing (already 3x-duplicated) style; a 4th
    call site is the tip-over point a future pass could extract, not this one."""
    cred = db.query(HostCredential).filter_by(host_id=host.id, kind="api_token").one_or_none()
    if cred is None:
        raise HTTPException(409, f"host {host.name} has no API token credential")
    tok = jsonlib.loads(app_state.secretstore.decrypt(cred.encrypted_blob))
    return ProxmoxClient(host.address, tok["token_id"], tok["token_secret"],
                         verify_tls=host.verify_tls, tls_fingerprint=host.tls_fingerprint,
                         factory=app_state.proxmox_factory)


_require_operator = require_role("operator")


@router.post("/apps/{app_id}/console/tickets",
             dependencies=[Depends(_require_operator), Depends(require_entitlement("apps.console"))])
def app_console_ticket(request: Request, app_id: int, db=Depends(get_db),
                       user: User = Depends(_require_operator)):
    a = db.get(App, app_id)
    if a is None:
        raise HTTPException(404, "app not found")
    host = db.get(Host, a.host_id)
    if host is None:
        raise HTTPException(404, "host not found")
    client = _proxmox_client_for_host(request.app.state, db, host)
    node = host.node_name or ""
    upstream = client.termproxy("lxc", node, a.ctid)
    raw, expires_at = mint_ticket(
        db, user_id=user.id, kind="app_console", target_id=a.id, node=node,
        guest_kind="lxc", vmid=a.ctid, upstream_user=upstream["user"],
        upstream_ticket=upstream["ticket"], upstream_port=str(upstream["port"]),
        ttl_s=request.app.state.settings.console_ticket_ttl_s)
    write_audit(db, actor_type="user", actor_id=user.id, action="console.open",
               target_type="app", target_id=a.id,
               ip=request.client.host if request.client else None)
    return {"ticket": raw, "expires_at": expires_at.isoformat() + "Z"}


# row.kind -> callable resolving the Host.id the ticket's node/guest lives on.
# "node_shell" is Task 6's kind (a ticket minted directly against a host), kept
# here so _run_pty_ws already dispatches on it without Task 6 touching this
# function at all -- it only needs to add the POST/WS routes that mint that kind.
_HOST_ID_RESOLVERS = {
    "app_console": lambda db, row: db.get(App, row.target_id).host_id,
    "node_shell": lambda db, row: row.target_id,
}


async def _run_pty_ws(websocket: WebSocket, ticket: str | None):
    if ticket is None:
        await websocket.close(code=4401)
        return
    db = websocket.app.state.sessionmaker()
    try:
        row = redeem_ticket(db, ticket)
        resolver = _HOST_ID_RESOLVERS.get(row.kind) if row is not None else None
        if resolver is None:
            # No row, or a ticket minted for a different kind of console (e.g. a
            # vm_vnc ticket replayed here) -- reject the same way an absent/expired
            # ticket does, rather than KeyError-ing on the dict lookup below.
            await websocket.close(code=4401)
            return
        host = db.get(Host, resolver(db, row))
    finally:
        db.close()
    await websocket.accept()
    try:
        # Module-qualified call (not a bare name from a `from-import`) so that
        # tests can monkeypatch `ptybridge.connect_upstream_pty` in place --
        # an early-bound `from ... import connect_upstream_pty` name here would
        # keep pointing at the original function no matter what the test
        # reassigns on the module, and silently exercise the real wss:// path
        # instead of the fake upstream.
        upstream = await ptybridge.connect_upstream_pty(
            address=host.address, node=row.node, guest_kind=row.guest_kind, vmid=row.vmid,
            upstream_user=row.upstream_user, upstream_ticket=row.upstream_ticket,
            upstream_port=row.upstream_port, verify_tls=host.verify_tls,
            tls_fingerprint=host.tls_fingerprint)
    except PtyBridgeError as e:
        await websocket.send_text(jsonlib.dumps({"type": "exit", "code": 1, "error": str(e)}))
        await websocket.close()
        return
    await websocket.send_text("OK")
    idle_s = websocket.app.state.settings.console_idle_timeout_s
    try:
        await bridge_pty(websocket, upstream, idle_timeout_s=idle_s)
    except WebSocketDisconnect:
        await upstream.close()


@router.websocket("/apps/{app_id}/console/ws")
async def app_console_ws(websocket: WebSocket, app_id: int, ticket: str | None = None):
    await _run_pty_ws(websocket, ticket)


@router.post("/vms/{vm_id}/console/tickets",
             dependencies=[Depends(_require_operator), Depends(require_entitlement("vms.console"))])
def vm_console_ticket(request: Request, vm_id: int, db=Depends(get_db),
                      user: User = Depends(_require_operator)):
    v = db.get(Vm, vm_id)
    if v is None:
        raise HTTPException(404, "vm not found")
    host = db.get(Host, v.host_id)
    if host is None:
        raise HTTPException(404, "host not found")
    client = _proxmox_client_for_host(request.app.state, db, host)
    node = host.node_name or ""
    upstream = client.vncproxy(node, v.vmid)
    raw, expires_at = mint_ticket(
        db, user_id=user.id, kind="vm_vnc", target_id=v.id, node=node,
        guest_kind="qemu", vmid=v.vmid, upstream_user=upstream["user"],
        upstream_ticket=upstream["ticket"], upstream_port=str(upstream["port"]),
        ttl_s=request.app.state.settings.console_ticket_ttl_s)
    write_audit(db, actor_type="user", actor_id=user.id, action="console.open",
               target_type="vm", target_id=v.id,
               ip=request.client.host if request.client else None)
    return {"ticket": raw, "expires_at": expires_at.isoformat() + "Z"}


@router.websocket("/vms/{vm_id}/vnc/ws")
async def vm_vnc_ws(websocket: WebSocket, vm_id: int, ticket: str | None = None):
    if ticket is None:
        await websocket.close(code=4401)
        return
    db = websocket.app.state.sessionmaker()
    try:
        row = redeem_ticket(db, ticket)
        if row is None or row.kind != "vm_vnc":
            await websocket.close(code=4401)
            return
        v = db.get(Vm, row.target_id)
        host = db.get(Host, v.host_id)
    finally:
        db.close()
    await websocket.accept()
    upstream = await connect_upstream_vnc(
        address=host.address, node=row.node, vmid=row.vmid,
        upstream_ticket=row.upstream_ticket, upstream_port=row.upstream_port,
        verify_tls=host.verify_tls, tls_fingerprint=host.tls_fingerprint)
    idle_s = websocket.app.state.settings.console_idle_timeout_s
    try:
        await bridge_binary(websocket, upstream, idle_timeout_s=idle_s)
    except WebSocketDisconnect:
        await upstream.close()
