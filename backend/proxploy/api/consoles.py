"""Console ticket + websocket routes (doc 05 §2/§3, doc 02 §5 PtyBridge/
ConsoleProxy). Every ticket-issuing POST is a normal cookie+CSRF+entitlement
route; every WS route below takes NO cookie, the one-time ticket already
proves auth (doc 05 "Auth model for streams"), so these follow jobs.py's
"manual auth inside the handler" idiom only where the SSE precedent doesn't
apply (session auth is not needed at all on the WS side)."""
from __future__ import annotations

import json as jsonlib

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket
from fastapi.websockets import WebSocketDisconnect

from proxploy.api.deps import authorize, get_db, require_entitlement, scope_app, scope_host, scope_vm
from proxploy.models import App, Host, User, Vm, to_iso
from proxploy.services import ptybridge
from proxploy.services.audit import write_audit
from proxploy.services.consoleproxy import ConsoleProxyError, bridge_binary, connect_upstream_vnc
from proxploy.services.consoletickets import mint_ticket, redeem_ticket
from proxploy.services.hostclient import client_for_host, guest_node
from proxploy.services.ptybridge import PtyBridgeError, bridge_pty
from proxploy.services.proxmox import ProxmoxError

router = APIRouter(tags=["consoles"])


_app_console = authorize("app", "console", scope_of=scope_app())
_host_console = authorize("host", "console", scope_of=scope_host())
_vm_console = authorize("vm", "console", scope_of=scope_vm())


@router.post("/apps/{app_id}/console/tickets",
             dependencies=[Depends(_app_console), Depends(require_entitlement("apps.console"))])
def app_console_ticket(request: Request, app_id: int, db=Depends(get_db),
                       user: User = Depends(_app_console)):
    a = db.get(App, app_id)
    if a is None:
        raise HTTPException(404, "app not found")
    host = db.get(Host, a.host_id)
    if host is None:
        raise HTTPException(404, "host not found")
    _refuse_if_not_running(a.status_cached, a.name)
    # Both the client build AND the proxy call are wrapped. The proxy call
    # used to sit outside this block, so a token too narrow for the console
    # (Proxmox answering "Permission check failed (/nodes/pve1,
    # Sys.Console)") escaped the route as an unhandled ProxmoxError. The
    # message was never missing: services/proxmox.py::_permission_detail
    # already names the privilege. Nothing was catching it to deliver.
    try:
        client = client_for_host(request.app, db, host, capability="console")
    except ProxmoxError as e:
        raise HTTPException(409, str(e)) from e
    node = host.node_name or ""
    try:
        upstream = client.termproxy("lxc", node, a.ctid)
    except ProxmoxError as e:
        raise HTTPException(409, str(e)) from e
    raw, expires_at = mint_ticket(
        db, user_id=user.id, kind="app_console", target_id=a.id, node=node,
        guest_kind="lxc", vmid=a.ctid, upstream_user=upstream["user"],
        upstream_ticket=upstream["ticket"], upstream_port=str(upstream["port"]),
        ttl_s=request.app.state.settings.console_ticket_ttl_s)
    write_audit(db, actor_type="user", actor_id=user.id, action="console.open",
               target_type="app", target_id=a.id,
               ip=request.client.host if request.client else None)
    return {"ticket": raw, "expires_at": to_iso(expires_at)}


# PVE happily mints a termproxy ticket for a guest that is not running, and the
# websocket then connects to a PTY that never emits a byte: the operator gets a
# blank terminal with no error and no hint (seen on PVE 9.2.6, 2026-08-10).
# Refuse up front instead.
#
# Only a KNOWN stopped state refuses. An unknown/None status (poller has not run
# yet, or the row predates it) falls through and opens the console, because
# blocking a console on a missing cache entry would be a worse failure than the
# blank terminal this prevents.
_NOT_RUNNING = frozenset({"stopped", "paused", "suspended"})


def _refuse_if_not_running(status: str | None, name: str) -> None:
    if (status or "").lower() in _NOT_RUNNING:
        raise HTTPException(409, {
            "error": "guest_not_running",
            "detail": f"{name} is {status}; start it before opening a console."})


def _auth_header_for(app, db, host: Host | None) -> str | None:
    """The `Authorization` value the two WS handlers must forward upstream.

    Returns None rather than raising when the host has no usable token: the
    connect below then fails with Proxmox's own 401, which both handlers
    already surface as a clean close. A missing credential is not worth a
    second, differently-shaped error path here.
    """
    if host is None:
        return None
    try:
        return client_for_host(app, db, host, capability="console").pve_auth_header
    except ProxmoxError:
        return None


# row.kind -> callable resolving the Host.id the ticket's node/guest lives on,
# or None if the ticket's own target row was deleted during the ticket's TTL
# window (a real race, not just theoretical -- doc 08's short TTL narrows but
# doesn't close it). "node_shell" is Task 6's kind (a ticket minted directly
# against a host), kept here so _run_pty_ws already dispatches on it without
# Task 6 touching this function at all -- it only needs to add the POST/WS
# routes that mint that kind.
def _app_console_host_id(db, row):
    a = db.get(App, row.target_id)
    return a.host_id if a is not None else None


def _node_shell_host_id(db, row):
    return row.target_id


_HOST_ID_RESOLVERS = {
    "app_console": _app_console_host_id,
    "node_shell": _node_shell_host_id,
}


async def _run_pty_ws(websocket: WebSocket, ticket: str | None, *, expected_kind: str):
    if ticket is None:
        await websocket.close(code=4401)
        return
    db = websocket.app.state.sessionmaker()
    try:
        row = redeem_ticket(db, ticket)
        if row is None or row.kind != expected_kind:
            # No row, or a ticket minted for a different kind of console (e.g. a
            # node_shell ticket redeemed at /apps/{id}/console/ws) -- reject the
            # same way an absent/expired ticket does, never trusting a ticket
            # kind this route didn't itself mint.
            await websocket.close(code=4401)
            return
        host_id = _HOST_ID_RESOLVERS[row.kind](db, row)
        host = db.get(Host, host_id) if host_id is not None else None
        # Built here, while the session is still open: PVE authenticates the
        # websocket upgrade itself, and the credential lives behind the db.
        auth_header = _auth_header_for(websocket.app, db, host)
    finally:
        db.close()
    if host is None:
        # The app/host row this ticket points at was deleted during the
        # ticket's short TTL window -- a clean 404-equivalent close, not an
        # AttributeError crash.
        await websocket.close(code=4404)
        return
    await websocket.accept()
    try:
        # Module-qualified call (not a bare name from a `from-import`) so that
        # tests can monkeypatch `ptybridge.connect_upstream_pty` in place --
        # an early-bound `from ... import connect_upstream_pty` name here would
        # keep pointing at the original function no matter what the test
        # reassigns on the module, and silently exercise the real wss:// path
        # instead of the fake upstream.
        upstream, buffered = await ptybridge.connect_upstream_pty(
            address=host.address, node=row.node, guest_kind=row.guest_kind, vmid=row.vmid,
            upstream_user=row.upstream_user, upstream_ticket=row.upstream_ticket,
            upstream_port=row.upstream_port, verify_tls=host.verify_tls,
            tls_fingerprint=host.tls_fingerprint, auth_header=auth_header)
    except PtyBridgeError as e:
        await websocket.send_text(jsonlib.dumps({"type": "exit", "code": 1, "error": str(e)}))
        await websocket.close()
        return
    if buffered:
        # Whatever PTY output was already buffered upstream (e.g. the shell
        # prompt) -- never a literal "OK" sentinel, which used to land as
        # garbage in the user's terminal.
        await websocket.send_text(buffered)
    idle_s = websocket.app.state.settings.console_idle_timeout_s
    try:
        await bridge_pty(websocket, upstream, idle_timeout_s=idle_s)
    except WebSocketDisconnect:
        await upstream.close()


@router.websocket("/apps/{app_id}/console/ws")
async def app_console_ws(websocket: WebSocket, app_id: int, ticket: str | None = None):
    await _run_pty_ws(websocket, ticket, expected_kind="app_console")


@router.post("/hosts/{host_id}/shell/tickets",
             dependencies=[Depends(_host_console), Depends(require_entitlement("terminal.node"))])
def node_shell_ticket(request: Request, host_id: int, db=Depends(get_db),
                      user: User = Depends(_host_console)):
    host = db.get(Host, host_id)
    if host is None:
        raise HTTPException(404, "host not found")
    if not host.node_shell_enabled:
        raise HTTPException(409, "node shell is not enabled for this host; "
                             "opt in via host settings first (doc 08 §9: a "
                             "second, deliberate gate on top of RBAC)")
    try:
        client = client_for_host(request.app, db, host, capability="console")
    except ProxmoxError as e:
        raise HTTPException(409, str(e)) from e
    node = host.node_name or ""
    try:
        upstream = client.node_termproxy(node)
    except ProxmoxError as e:
        raise HTTPException(409, str(e)) from e
    raw, expires_at = mint_ticket(
        db, user_id=user.id, kind="node_shell", target_id=host.id, node=node,
        guest_kind=None, vmid=None, upstream_user=upstream["user"],
        upstream_ticket=upstream["ticket"], upstream_port=str(upstream["port"]),
        ttl_s=request.app.state.settings.console_ticket_ttl_s)
    write_audit(db, actor_type="user", actor_id=user.id, action="console.open",
               target_type="host", target_id=host.id,
               ip=request.client.host if request.client else None)
    return {"ticket": raw, "expires_at": to_iso(expires_at)}


@router.websocket("/hosts/{host_id}/shell/ws")
async def node_shell_ws(websocket: WebSocket, host_id: int, ticket: str | None = None):
    await _run_pty_ws(websocket, ticket, expected_kind="node_shell")


@router.post("/vms/{vm_id}/console/tickets",
             dependencies=[Depends(_vm_console), Depends(require_entitlement("vms.console"))])
def vm_console_ticket(request: Request, vm_id: int, db=Depends(get_db),
                      user: User = Depends(_vm_console)):
    v = db.get(Vm, vm_id)
    if v is None:
        raise HTTPException(404, "vm not found")
    host = db.get(Host, v.host_id)
    if host is None:
        raise HTTPException(404, "host not found")
    _refuse_if_not_running(v.status, v.name or f"vm {v.vmid}")
    try:
        client = client_for_host(request.app, db, host, capability="console")
    except ProxmoxError as e:
        raise HTTPException(409, str(e)) from e
    node = guest_node(host, v)
    try:
        upstream = client.vncproxy(node, v.vmid)
    except ProxmoxError as e:
        raise HTTPException(409, str(e)) from e
    raw, expires_at = mint_ticket(
        db, user_id=user.id, kind="vm_vnc", target_id=v.id, node=node,
        guest_kind="qemu", vmid=v.vmid, upstream_user=upstream["user"],
        upstream_ticket=upstream["ticket"], upstream_port=str(upstream["port"]),
        ttl_s=request.app.state.settings.console_ticket_ttl_s)
    write_audit(db, actor_type="user", actor_id=user.id, action="console.open",
               target_type="vm", target_id=v.id,
               ip=request.client.host if request.client else None)
    return {"ticket": raw, "expires_at": to_iso(expires_at)}


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
        host = db.get(Host, v.host_id) if v is not None else None
        auth_header = _auth_header_for(websocket.app, db, host)
    finally:
        db.close()
    if host is None:
        # The VM row this ticket points at was deleted during the ticket's
        # short TTL window -- a clean 404-equivalent close, not an
        # AttributeError crash on `v.host_id`.
        await websocket.close(code=4404)
        return
    await websocket.accept()
    try:
        upstream = await connect_upstream_vnc(
            address=host.address, node=row.node, vmid=row.vmid,
            upstream_ticket=row.upstream_ticket, upstream_port=row.upstream_port,
            verify_tls=host.verify_tls, tls_fingerprint=host.tls_fingerprint,
            auth_header=auth_header)
    except ConsoleProxyError as e:
        # VNC has no JSON control-frame channel like PtyBridge's exit frame --
        # the close code/reason is the only signal available to the browser.
        await websocket.close(code=1011, reason=str(e))
        return
    idle_s = websocket.app.state.settings.console_idle_timeout_s
    try:
        await bridge_binary(websocket, upstream, idle_timeout_s=idle_s)
    except WebSocketDisconnect:
        await upstream.close()
