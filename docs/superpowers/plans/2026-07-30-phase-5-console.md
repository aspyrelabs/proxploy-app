# Phase 5 (Console) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship consoles: an xterm.js `PtyBridge` for CT terminals and node shells (proxying Proxmox's `termproxy`), and a noVNC `ConsoleProxy` for VM consoles (proxying Proxmox's `vncproxy`/`vncwebsocket`) — browser never talks to Proxmox directly, every open is ticket-authed and audited.

**Architecture:** A one-time, single-use Proxploy ticket (`console_tickets` table, `SessionRow`-shaped: raw value hashed at rest) is minted by a normal cookie+CSRF-authed POST route, which is also where Proxmox's own `termproxy`/`vncproxy` call happens and its short-lived upstream ticket gets stored server-side (doc 02 §5 — the upstream ticket never reaches the browser). The browser then opens a plain WebSocket with `?ticket=<ours>` and no cookie is needed on the socket itself — the ticket already proves auth, redeemed exactly once. Two backend proxy shapes, because Proxmox's two upstream protocols are different shapes: `services/ptybridge.py` speaks Proxmox's line-oriented `0:`/`1:`/`2` xtermjs framing (CT + node shell, **reverse-engineered from Proxmox's own `pve-xtermjs` client** — see the correction note below) and translates it to/from Proxploy's own simpler framing (raw text + one JSON resize control frame, doc 05 §Streaming); `services/consoleproxy.py` is a dumb transparent binary pipe for VM VNC (RFB is opaque to us, doc 05 §3). Both reuse `services/proxmox.py`'s existing SSRF-guard (`resolve_target`) and TLS-fingerprint-pinning (`tls_fingerprint_sha256`) rather than inventing a second one.

**Tech Stack:** FastAPI + SQLAlchemy 2 + Alembic (existing), `websockets` (new *direct* dependency — already present transitively via `uvicorn[standard]`, pinned explicitly now that first-party code imports it), `@xterm/xterm` + `@xterm/addon-fit` (new, MIT), `@novnc/novnc` (new, MPL-2.0 — link only, per doc 03; never copy its files into this tree).

## Global Constraints

- Nothing outside `proxploy/executor/` may `import asyncssh` or reference `get_ssh_private_key` (`backend/scripts/check_executor_isolation.py`, CI-wired) — **unaffected by this phase**, consoles never touch SSH, Proxmox's own API provides the PTY/VNC websocket (doc 02 §5).
- Every DB-touching test uses the existing sqlite-per-`tmp_path` conventions (`tests/support.py::make_db`/`make_app`/`make_job_app`, `tests/conftest.py::client`) — no new fixture infrastructure unless a task says so explicitly.
- All new backend routes live under `/api/v1` via `proxploy/api/__init__.py`'s `api_router.include_router(...)` — there is no auto-discovery.
- Frontend server state lives exclusively in TanStack Query (doc 06 §d) — consoles are the one deliberate exception already documented (doc 06: "Consoles connect on tab activation, disconnect on route leave — never a shared connection"), so console WebSocket lifecycle is local component state, not a query.
- `proxploy/services/proxmox.py`'s module docstring rule holds: every proxmoxer call and every PVE-8-vs-9 branch lives there, never in routers/services. The two new REST calls (`termproxy`, `vncproxy`) go there; the websocket byte-bridging itself is a different concern (not a proxmoxer call) and lives in its own `services/ptybridge.py`/`services/consoleproxy.py`.
- Doc 08 §9 requirements this phase must satisfy: every console open is audited (who/where/when, never *what was typed* — a deliberate privacy call already made in doc 08, not something this plan revisits); an idle timeout closes both sides; the ticket is single-use and short-TTL; node shell is a stricter, separate opt-in (admin-only + `terminal.node` entitlement + a per-host toggle) on top of the base CT/VM console gates.

**Spike correction — Proxmox API tokens cannot open `/termproxy` xtermjs websockets on all supported PVE versions (a real gap in docs 00/02/08's assumptions, found while grounding this plan, not papered over):**

Doc 08's "always a scoped API token, never root@pam password" rule is correct and unchanged for **every other** Proxmox call this app makes, including the VM `vncproxy` path — confirmed working with tokens (`websocket=1` param on the REST call). But the *xtermjs text-mode* `/termproxy` → `/vncwebsocket` handshake is different: Proxmox's own client (`pve-xtermjs`, see Task 3) sends an initial line `"{user}:{ticket}\n"` over the socket itself, and multiple Proxmox forum threads plus **Proxmox bugzilla #6079** document that an API-token-derived `user` string (`root@pam!mytoken`) is rejected there with *"does not look like a valid user name"* — a real PVE-side bug, not a Proxploy bug. It was fixed for the **VM** case in `qemu-server` 9.1.7+ (commit switching to a `--vncticket-endpoint`-aware ticket format); whether the equivalent **LXC**/**node-shell** `termproxy` path is fixed on the same timeline is not confirmed by any source found. Since this project has no live PVE host to test against (a standing limitation every prior phase has stated), this plan does **not** invent a workaround (e.g. a second, password-based PVE identity, which doc 08 explicitly forbids) — instead:
- Task 5/6's routes use the existing scoped API token uniformly, exactly like every other Proxmox call in this codebase (no special-casing).
- Task 3 makes the specific PVE rejection message detectable and surfaces it as a clear, actionable error (`"this Proxmox host's termproxy does not accept API-token auth; upgrade qemu-server / pve-manager"`) rather than a generic timeout or a silently-broken terminal.
- A `pve_integration`-marked (existing pytest marker, already the gate every live-PVE test in this repo uses) live test is added in Task 12 to prove-or-disprove this on whatever real PVE host is available whenever one is — this is the actual verification point for this finding, deferred exactly like every other live-PVE-dependent proof in Phases 1-4.

**Confirmed, not assumed — the exact xtermjs wire protocol** (Proxmox has no written spec for this; the following was read directly out of Proxmox's own `pve-xtermjs` project, `git.proxmox.com/pve-xtermjs.git`, `src/www/main.js`, the same client PVE's own web UI uses for CT/node consoles):
- Client connects `wss://{host}:{port}/api2/json/nodes/{node}[/lxc/{vmid}|/qemu/{vmid}]/vncwebsocket?port={port}&vncticket={urlencoded ticket}` with WS subprotocol `"binary"`.
- First client→server frame: `f"{user}:{ticket}\n"` (the `user` and `ticket` are exactly what `/termproxy` returned — never re-derived).
- First server→client frame on success starts with literal `"OK"`, followed by any already-buffered PTY output; anything else in that first frame is treated as an auth failure.
- Subsequent server→client frames after the first are raw output text — no further framing.
- Client→server keystroke frames: `f"0:{len(utf8_bytes)}:{data}"`.
- Client→server resize frame: `f"1:{cols}:{rows}:"`.
- Client→server keepalive: bare `"2"` (Proxmox's own client sends one every 30s; PtyBridge does the same so idle PVE-side timeouts don't fire under a silent terminal).
- **This is entirely internal, backend↔Proxmox wire format.** The browser↔Proxploy side is doc 05's own simpler framing (raw bytes both ways, one JSON control frame `{"type":"resize","cols":...,"rows":...}` from client, one `{"type":"exit","code":...}` from server before close) — `PtyBridge` is the translator between the two, per doc 02 §5's "this whole path is the PtyBridge/ConsoleProxy seam."
- VM `vncproxy`/`vncwebsocket` needs **no** such line-based handshake — the ticket is validated via the URL query params at websocket-upgrade time, and the very first server→client frame is the raw RFB protocol greeting (`"RFB 003.008\n"`-shaped bytes); noVNC's own `RFB` class on the browser side handles the entire RFB handshake including using the VNC ticket as the RFB password. `ConsoleProxy` is therefore a dumb byte-for-byte relay, no translation — matches doc 05 §3 exactly ("opaque RFB byte stream, no Proxploy framing").

---

## File Structure

**Backend, new files:**
- `proxploy/services/consoletickets.py` — `ConsoleTicket` minting (`mint_ticket`) and single-use redemption (`redeem_ticket`), `SessionRow`/`create_session` pattern (hash-at-rest, never store the raw ticket)
- `proxploy/services/ptybridge.py` — `connect_upstream_pty(...)` (opens the wss connection to Proxmox with the SSRF/TLS-pin reuse, sends the auth line, checks `"OK"`) + `bridge_pty(browser_ws, upstream_ws, idle_timeout_s)` (the byte/frame translation loop)
- `proxploy/services/consoleproxy.py` — `connect_upstream_vnc(...)` + `bridge_binary(browser_ws, upstream_ws, idle_timeout_s)` (transparent relay, no translation)
- `proxploy/api/consoles.py` — `POST /apps/{id}/console/tickets`, `WS /apps/{id}/console/ws`, `POST /hosts/{id}/shell/tickets`, `WS /hosts/{id}/shell/ws`, `POST /vms/{id}/console/tickets`, `WS /vms/{id}/vnc/ws`
- `proxploy/migrations/versions/<rev>_0004_console_tickets.py` — `console_tickets` table + `hosts.node_shell_enabled` column
- Backend test files: `tests/test_proxmox_console_calls.py`, `tests/test_consoletickets.py`, `tests/test_ptybridge.py`, `tests/test_consoleproxy.py`, `tests/test_consoles_api.py`, `tests/fakes/pve_ws.py` (an in-process fake upstream websocket server speaking the documented xtermjs/RFB-greeting protocol, `websockets.serve`-based, mirrors `tests/fakes/ssh.py`'s role for Phase 4)

**Backend, modified files:**
- `proxploy/services/proxmox.py` — add `termproxy(kind, node, vmid)`, `node_termproxy(node)`, `vncproxy(node, vmid)` methods; extract `open_validated_tcp_socket(host, port, timeout=10)` out of `tls_fingerprint_sha256` (the one line that already does `resolve_target` + `socket.create_connection`) so `ptybridge`/`consoleproxy` reuse it instead of re-deriving the SSRF guard
- `proxploy/models/__init__.py` — add `ConsoleTicket` model, `Host.node_shell_enabled` column
- `proxploy/api/__init__.py` — register `consoles.router`
- `proxploy/api/hosts.py` — add `PATCH /hosts/{id}` (the one field it needs: `node_shell_enabled`; no other host fields are made editable — that's out of this phase's scope)
- `proxploy/config.py` — add `console_ticket_ttl_s: float = 30.0`, `console_idle_timeout_s: float = 1800.0`
- `tests/fakes/pve.py` — extend `_NodeNS`/`_GuestNS` with `.termproxy`/`.vncproxy` leaves
- `pyproject.toml` — add `websockets>=13`

**Frontend, new files:**
- `frontend/src/components/terminal/Terminal.tsx` — xterm.js wrapper (mount, fit addon, theme, keystroke→ws, resize→JSON control frame)
- `frontend/src/components/console/VncConsole.tsx` — noVNC wrapper (RFB instance, Ctrl-Alt-Del/fullscreen toolbar)
- `frontend/src/api/consoles.ts` — `useConsoleTicket(kind, id)` mutation hook (mirrors `useInstall`'s POST-then-use-result shape)
- Frontend test files: `frontend/src/tests/terminal.test.tsx`, `frontend/src/tests/vncconsole.test.tsx`, `frontend/src/tests/consoles-api.test.tsx`

**Frontend, modified files:**
- `frontend/src/routes/apps.tsx` — replace the `appConsoleRoute`/`appLogsRoute` `phaseTab` placeholders with real `AppConsole`/`AppLogs` components; `AppCard.tsx` gains a Console quick-action button
- `frontend/src/routes/vms.tsx` — replace the `vmConsoleRoute` placeholder with `VmConsole`; VM table row gains a Console quick-action button
- `frontend/src/routes/cluster.tsx` — `NodeDetailPage` gains a node-shell section, gated by `terminal.node` entitlement + `host.node_shell_enabled`
- `frontend/package.json` — add `@xterm/xterm`, `@xterm/addon-fit`, `@novnc/novnc`

---

## Task 1: `ProxmoxClient` termproxy/vncproxy calls + FakePVE support

**Files:**
- Modify: `backend/proxploy/services/proxmox.py`, `backend/tests/fakes/pve.py`
- Test: `backend/tests/test_proxmox_console_calls.py`

**Interfaces:**
- Produces: `ProxmoxClient.termproxy(kind: str, node: str, vmid: int) -> dict` (`{"user": str, "ticket": str, "port": str, "upid": str}`), `ProxmoxClient.node_termproxy(node: str) -> dict` (same shape, node-level shell, no `vmid`), `ProxmoxClient.vncproxy(node: str, vmid: int) -> dict` (`{"user": str, "ticket": str, "port": str, "cert": str, "upid": str}`), `open_validated_tcp_socket(host: str, port: int, timeout: float = 10.0) -> socket.socket`.
- Consumes: `resolve_target` (existing, `proxploy/services/proxmox.py:121`).

- [ ] **Step 1: Write the failing tests for the three new client methods**

```python
# backend/tests/test_proxmox_console_calls.py
import pytest

from proxploy.services.proxmox import ProxmoxClient, ProxmoxError
from tests.fakes.pve import FakePVE, make_fake_factory


def _client(fake):
    return ProxmoxClient("https://10.0.0.9:8006", "proxploy@pve!console",
                          "sekret", verify_tls=False,
                          factory=make_fake_factory(fake))


def test_termproxy_returns_ticket_port_user():
    fake = FakePVE()
    fake.termproxy_response = {"user": "proxploy@pve!console", "ticket": "PVEVNC:abc123",
                                "port": "5900", "upid": "UPID:pve1:...:termproxy::proxploy@pve:"}
    result = _client(fake).termproxy("lxc", "pve1", 150)
    assert result == fake.termproxy_response
    assert fake.last_termproxy_call == ("lxc", "pve1", 150)


def test_node_termproxy_has_no_guest_segment():
    fake = FakePVE()
    fake.termproxy_response = {"user": "proxploy@pve!console", "ticket": "PVEVNC:xyz",
                                "port": "5901", "upid": "UPID:pve1:...:termproxy::proxploy@pve:"}
    result = _client(fake).node_termproxy("pve1")
    assert result == fake.termproxy_response
    assert fake.last_node_termproxy_call == "pve1"


def test_vncproxy_returns_ticket_port_cert():
    fake = FakePVE()
    fake.vncproxy_response = {"user": "proxploy@pve!console", "ticket": "PVEVNC:def456",
                              "port": "5902", "cert": "-----BEGIN CERTIFICATE-----...",
                              "upid": "UPID:pve1:...:vncproxy::proxploy@pve:"}
    result = _client(fake).vncproxy("pve1", 200)
    assert result == fake.vncproxy_response
    assert fake.last_vncproxy_call == ("pve1", 200)


def test_termproxy_wraps_and_redacts_secret_on_failure():
    fake = FakePVE(fail=True)
    with pytest.raises(ProxmoxError) as exc:
        _client(fake).termproxy("lxc", "pve1", 150)
    assert "sekret" not in str(exc.value)


def test_open_validated_tcp_socket_refuses_link_local():
    from proxploy.services.proxmox import open_validated_tcp_socket, ProxmoxError
    with pytest.raises(ProxmoxError, match="link-local"):
        open_validated_tcp_socket("169.254.169.254", 8006, timeout=1)
```

- [ ] **Step 2: Run to verify failures**

Run: `cd backend && pytest tests/test_proxmox_console_calls.py -v`
Expected: FAIL — `AttributeError: 'ProxmoxClient' object has no attribute 'termproxy'` (and the fake's response/call-tracking attributes don't exist yet either).

- [ ] **Step 3: Add the fake's termproxy/vncproxy leaves**

In `backend/tests/fakes/pve.py`, extend `_GuestNS` and `_NodeNS`:

```python
class _TermproxyLeaf:
    def __init__(self, owner, kind, node, vmid):
        self._owner, self._kind, self._node, self._vmid = owner, kind, node, vmid

    def post(self, **kwargs):
        if self._owner.fail:
            raise ConnectionError("fake PVE unreachable")
        if self._vmid is None:
            self._owner.last_node_termproxy_call = self._node
        else:
            self._owner.last_termproxy_call = (self._kind, self._node, self._vmid)
        return self._owner.termproxy_response


class _VncproxyLeaf:
    def __init__(self, owner, node, vmid):
        self._owner, self._node, self._vmid = owner, node, vmid

    def post(self, **kwargs):
        if self._owner.fail:
            raise ConnectionError("fake PVE unreachable")
        self._owner.last_vncproxy_call = (self._node, self._vmid)
        return self._owner.vncproxy_response
```

Modify `_GuestNS`/`_GuestFactory`/`_NodeNS` to add `.termproxy` for `nodes(n).lxc(vmid).termproxy` / `nodes(n).qemu(vmid).termproxy` / `nodes(n).termproxy` (node shell), and `.vncproxy` for the qemu case only (matching Proxmox — LXC has no `vncproxy`). `_GuestNS` doesn't know its own node name today (only `_NodeNS` does), so `node` needs threading through `_GuestFactory` too — replace all three classes:

```python
class _GuestNS:
    def __init__(self, owner, kind, node, vmid):
        self.status = _GuestStatusNS(owner, kind, vmid)
        self.termproxy = _TermproxyLeaf(owner, kind, node, vmid)
        if kind == "qemu":
            self.vncproxy = _VncproxyLeaf(owner, node, vmid)


class _GuestFactory:
    def __init__(self, owner, kind, node):
        self._owner, self._kind, self._node = owner, kind, node

    def __call__(self, vmid):
        return _GuestNS(self._owner, self._kind, self._node, int(vmid))


class _NodeNS:
    def __init__(self, owner, name):
        self.rrddata = _KwLeaf(owner.rrd_by_node.get(name, []),
                                owner.fail or owner.rrd_fail)
        self.tasks = _TaskFactory(owner)
        self.lxc = _GuestFactory(owner, "lxc", name)
        self.qemu = _GuestFactory(owner, "qemu", name)
        self.termproxy = _TermproxyLeaf(owner, None, name, None)
```

And in `FakePVE.__init__`, add:

```python
        self.termproxy_response: dict = {}
        self.vncproxy_response: dict = {}
        self.last_termproxy_call = None
        self.last_node_termproxy_call = None
        self.last_vncproxy_call = None
```

- [ ] **Step 4: Extract `open_validated_tcp_socket` and add the three `ProxmoxClient` methods**

In `backend/proxploy/services/proxmox.py`, replace the body of `tls_fingerprint_sha256` to reuse a new helper, and add the three methods:

```python
def open_validated_tcp_socket(host: str, port: int, timeout: float = 10.0) -> socket.socket:
    """resolve_target + connect to the literal we validated (doc 02 §5's SSRF
    guard, shared by the TLS-fingerprint check and the new console websocket
    connections — nothing here reaches Proxmox's own address string again)."""
    ip = resolve_target(host, port)
    return socket.create_connection((ip, port), timeout=timeout)


def tls_fingerprint_sha256(host: str, port: int = 8006) -> str:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE  # we are fetching the cert to pin it, not trusting it
    with open_validated_tcp_socket(host, port) as sock:
        with ctx.wrap_socket(sock, server_hostname=host) as tls:
            der = tls.getpeercert(binary_form=True)
    digest = hashlib.sha256(der).hexdigest().upper()
    return ":".join(digest[i:i + 2] for i in range(0, len(digest), 2))
```

Add to `class ProxmoxClient`, after `task_log`:

```python
    # --- console/terminal calls (Phase 5) -----------------------------------

    def termproxy(self, kind: str, node: str, vmid: int) -> dict:
        """POST /nodes/{node}/{lxc|qemu}/{vmid}/termproxy -> {user, ticket, port, upid}."""
        try:
            return getattr(self._connect().nodes(node), kind)(vmid).termproxy.post()
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"termproxy failed for {kind}/{vmid} on {node}", e) from e

    def node_termproxy(self, node: str) -> dict:
        """POST /nodes/{node}/termproxy -> {user, ticket, port, upid} (node shell)."""
        try:
            return self._connect().nodes(node).termproxy.post()
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"node termproxy failed on {node}", e) from e

    def vncproxy(self, node: str, vmid: int) -> dict:
        """POST /nodes/{node}/qemu/{vmid}/vncproxy (websocket=1) -> {user, ticket, port, cert, upid}."""
        try:
            return self._connect().nodes(node).qemu(vmid).vncproxy.post(websocket=1)
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"vncproxy failed for qemu/{vmid} on {node}", e) from e
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_proxmox_console_calls.py -v`
Expected: PASS (5 tests).

- [ ] **Step 6: Run the full backend suite (nothing else should move)**

Run: `cd backend && pytest tests/ -q -m "not pve_integration and not e2e"`
Expected: 308 passed, 2 skipped, 2 deselected + 5 new = 313 passed.

- [ ] **Step 7: Commit**

```bash
git add backend/proxploy/services/proxmox.py backend/tests/fakes/pve.py backend/tests/test_proxmox_console_calls.py
git commit -m "feat(proxmox): termproxy/node_termproxy/vncproxy calls + shared SSRF-safe socket helper"
```

---

## Task 2: `console_tickets` schema + single-use ticket service

**Files:**
- Create: `backend/proxploy/migrations/versions/<rev>_0004_console_tickets.py`
- Modify: `backend/proxploy/models/__init__.py`, `backend/proxploy/config.py`
- Create: `backend/proxploy/services/consoletickets.py`
- Test: `backend/tests/test_consoletickets.py`

**Interfaces:**
- Produces: `ConsoleTicket` model (`console_tickets` table). `mint_ticket(db, *, user_id: int, kind: str, target_id: int, node: str, guest_kind: str | None, vmid: int | None, upstream_user: str, upstream_ticket: str, upstream_port: str, ttl_s: float) -> tuple[str, datetime]` (returns the raw ticket string and its `expires_at`; only the sha256 hash is persisted). `redeem_ticket(db, raw: str) -> ConsoleTicket | None` (atomic: returns `None` if not found, expired, or already redeemed; otherwise sets `redeemed_at` and returns the row in one transaction so a race can't redeem twice).
- Consumes: `proxploy.models.utcnow`, `secrets.token_urlsafe`, `hashlib.sha256` (same primitives `services/authn.py::create_session`/`resolve_session` already use — same pattern, new table).

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_consoletickets.py
from datetime import timedelta

from proxploy.models import utcnow
from proxploy.services.consoletickets import mint_ticket, redeem_ticket
from tests.support import make_db


def _mint(db, user_id=1, **overrides):
    kwargs = dict(user_id=user_id, kind="app_console", target_id=42, node="pve1",
                  guest_kind="lxc", vmid=150, upstream_user="proxploy@pve!console",
                  upstream_ticket="PVEVNC:abc", upstream_port="5900", ttl_s=30.0)
    kwargs.update(overrides)
    return mint_ticket(db, **kwargs)


def test_redeem_returns_the_row_with_upstream_fields(tmp_path):
    db = make_db(tmp_path)
    raw, expires_at = _mint(db)
    assert expires_at > utcnow()
    row = redeem_ticket(db, raw)
    assert row is not None
    assert row.kind == "app_console" and row.target_id == 42
    assert row.node == "pve1" and row.guest_kind == "lxc" and row.vmid == 150
    assert row.upstream_ticket == "PVEVNC:abc" and row.upstream_port == "5900"
    assert row.redeemed_at is not None


def test_redeem_is_single_use(tmp_path):
    db = make_db(tmp_path)
    raw, _ = _mint(db)
    assert redeem_ticket(db, raw) is not None
    assert redeem_ticket(db, raw) is None  # second redemption fails


def test_redeem_rejects_unknown_ticket(tmp_path):
    db = make_db(tmp_path)
    assert redeem_ticket(db, "not-a-real-ticket") is None


def test_redeem_rejects_expired_ticket(tmp_path):
    db = make_db(tmp_path)
    raw, _ = _mint(db, ttl_s=-1.0)  # already expired
    assert redeem_ticket(db, raw) is None


def test_raw_ticket_value_is_not_persisted(tmp_path):
    from proxploy.models import ConsoleTicket

    db = make_db(tmp_path)
    raw, _ = _mint(db)
    row = db.query(ConsoleTicket).one()
    assert raw not in row.token_hash
    assert row.upstream_ticket == "PVEVNC:abc"  # only the UPSTREAM ticket is
    # stored in the clear — that one never reaches the browser (doc 02 §5);
    # OUR ticket (`raw`, the browser-facing one) is what gets hashed.
```

- [ ] **Step 2: Run to verify failures**

Run: `cd backend && pytest tests/test_consoletickets.py -v`
Expected: FAIL — `ImportError: cannot import name 'mint_ticket'` (module doesn't exist yet).

- [ ] **Step 3: Add the migration**

```python
# backend/proxploy/migrations/versions/<generate with `alembic revision`>_0004_console_tickets.py
"""0004 console tickets

Revision ID: <generated>
Revises: f691da7ec537
Create Date: 2026-07-30
"""
from alembic import op
import sqlalchemy as sa

revision = "<generated>"
down_revision = "f691da7ec537"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "console_tickets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),  # app_console | node_shell | vm_vnc
        sa.Column("target_id", sa.Integer(), nullable=False),
        sa.Column("node", sa.Text(), nullable=False),
        sa.Column("guest_kind", sa.Text(), nullable=True),  # lxc | qemu | NULL (node shell)
        sa.Column("vmid", sa.Integer(), nullable=True),
        sa.Column("upstream_user", sa.Text(), nullable=False),
        sa.Column("upstream_ticket", sa.Text(), nullable=False),
        sa.Column("upstream_port", sa.Text(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("redeemed_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_console_tickets_token_hash", "console_tickets", ["token_hash"])
    with op.batch_alter_table("hosts") as batch:
        batch.add_column(sa.Column("node_shell_enabled", sa.Boolean(), nullable=False,
                                   server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table("hosts") as batch:
        batch.drop_column("node_shell_enabled")
    op.drop_index("ix_console_tickets_token_hash", table_name="console_tickets")
    op.drop_table("console_tickets")
```

Run `cd backend && alembic revision --autogenerate -m "0004 console tickets"` first to get the real revision id, then hand-edit the body to match exactly the above (autogenerate may add unrelated noise — keep only these two changes).

- [ ] **Step 4: Add the model**

In `backend/proxploy/models/__init__.py`, after `Host` (or wherever `TimestampMixin`-free append-style models live — follow `AuditEvent`'s un-mixed style since this table also never gets ORM-updated except the one `redeemed_at` set), add:

```python
class ConsoleTicket(Base):
    """Single-use, short-TTL. Only `token_hash` is stored — never the raw,
    browser-facing ticket (SessionRow's exact pattern, doc 04). `upstream_ticket`
    IS stored in the clear: it's Proxmox's own short-TTL ticket, never reaches
    the browser (doc 02 §5), and is meaningless without a live upstream socket
    to present it to within its own few-second window."""
    __tablename__ = "console_tickets"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    target_id: Mapped[int] = mapped_column(Integer, nullable=False)
    node: Mapped[str] = mapped_column(Text, nullable=False)
    guest_kind: Mapped[str | None] = mapped_column(Text)
    vmid: Mapped[int | None] = mapped_column(Integer)
    upstream_user: Mapped[str] = mapped_column(Text, nullable=False)
    upstream_ticket: Mapped[str] = mapped_column(Text, nullable=False)
    upstream_port: Mapped[str] = mapped_column(Text, nullable=False)
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    redeemed_at: Mapped[datetime | None] = mapped_column(DateTime)
```

Also add, inside `class Host(TimestampMixin, Base):` after `ssh_host_key_fingerprint`:

```python
    node_shell_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
```

- [ ] **Step 5: Add the two settings fields**

In `backend/proxploy/config.py`, after `poll_timeout_s`:

```python
    console_ticket_ttl_s: float = 30.0
    console_idle_timeout_s: float = 1800.0
```

- [ ] **Step 6: Write `services/consoletickets.py`**

```python
"""Single-use, short-TTL console websocket tickets (doc 05 §Streaming "Auth
model for streams"). Same hash-at-rest shape as services/authn.py's
create_session/resolve_session — a new table because these bind to a Proxmox
target + upstream ticket, which sessions don't carry."""
import hashlib
import secrets
from datetime import datetime, timedelta

from proxploy.models import ConsoleTicket, utcnow


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def mint_ticket(db, *, user_id: int, kind: str, target_id: int, node: str,
                guest_kind: str | None, vmid: int | None, upstream_user: str,
                upstream_ticket: str, upstream_port: str,
                ttl_s: float) -> tuple[str, datetime]:
    raw = secrets.token_urlsafe(32)
    expires_at = utcnow() + timedelta(seconds=ttl_s)
    db.add(ConsoleTicket(
        user_id=user_id, kind=kind, target_id=target_id, node=node,
        guest_kind=guest_kind, vmid=vmid, upstream_user=upstream_user,
        upstream_ticket=upstream_ticket, upstream_port=upstream_port,
        token_hash=_hash(raw), expires_at=expires_at,
    ))
    db.commit()
    return raw, expires_at


def redeem_ticket(db, raw: str) -> ConsoleTicket | None:
    """Redeems exactly once. The UPDATE...WHERE redeemed_at IS NULL below is
    the atomicity boundary: two concurrent redemptions of the same raw value
    can both SELECT the row, but only one UPDATE can match `redeemed_at IS
    NULL`, so the loser's rowcount is 0 and it gets None, same as if the
    ticket had never existed."""
    row = db.query(ConsoleTicket).filter_by(token_hash=_hash(raw)).one_or_none()
    if row is None or row.expires_at < utcnow():
        return None
    updated = (db.query(ConsoleTicket)
               .filter(ConsoleTicket.id == row.id, ConsoleTicket.redeemed_at.is_(None))
               .update({"redeemed_at": utcnow()}))
    db.commit()
    if updated == 0:
        return None
    db.refresh(row)
    return row
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_consoletickets.py -v`
Expected: PASS (5 tests).

- [ ] **Step 8: Run the full backend suite**

Run: `cd backend && pytest tests/ -q -m "not pve_integration and not e2e"`
Expected: 313 + 5 = 318 passed (plus prior skipped/deselected counts).

- [ ] **Step 9: Commit**

```bash
git add backend/proxploy/migrations/versions/*_0004_console_tickets.py backend/proxploy/models/__init__.py backend/proxploy/config.py backend/proxploy/services/consoletickets.py backend/tests/test_consoletickets.py
git commit -m "feat(console): single-use ticket table + mint/redeem service"
```

---

## Task 3: `PtyBridge` — outbound xtermjs websocket client + protocol translation

**Files:**
- Create: `backend/proxploy/services/ptybridge.py`
- Create: `backend/tests/fakes/pve_ws.py`
- Test: `backend/tests/test_ptybridge.py`

**Interfaces:**
- Produces: `PtyBridgeError(RuntimeError)`. `async connect_upstream_pty(*, address: str, node: str, guest_kind: str | None, vmid: int | None, upstream_user: str, upstream_ticket: str, upstream_port: str, verify_tls: bool, tls_fingerprint: str | None, ws_connect=None) -> websockets client connection` (raises `PtyBridgeError` if the handshake's first frame isn't `"OK"`-prefixed — this is where the Task-header's token-vs-termproxy PVE rejection surfaces as a clear message). `async bridge_pty(browser_ws, upstream_ws, *, idle_timeout_s: float) -> None` (runs until either side closes or `idle_timeout_s` passes with no traffic; sends `{"type":"exit","code":...}` to `browser_ws` before returning).
- Consumes: `proxploy.services.proxmox.open_validated_tcp_socket`, `websockets.asyncio.client.connect`.

- [ ] **Step 1: Write the fake upstream xtermjs websocket server**

```python
# backend/tests/fakes/pve_ws.py
"""In-process fake Proxmox vncwebsocket server speaking the documented xtermjs
protocol (see plan doc's "Confirmed, not assumed" note) — enough to prove
PtyBridge's translation logic without a real PVE host."""
import asyncio

import websockets


class FakeXtermUpstream:
    """Records the auth line it received; scripted output lines are sent after
    the OK handshake; echoes decoded keystroke payloads back for round-trip
    tests; a `reject` flag makes the handshake fail the way an unpatched PVE
    would for API-token auth (doc's spike-correction note)."""

    def __init__(self, expected_auth_line: str, output_lines: list[str] | None = None,
                 reject: bool = False):
        self.expected_auth_line = expected_auth_line
        self.output_lines = output_lines or []
        self.reject = reject
        self.received_auth_line: str | None = None
        self.received_frames: list[str] = []
        self.received_resizes: list[tuple[int, int]] = []
        self._server = None

    async def _handler(self, ws):
        auth_line = await ws.recv()
        self.received_auth_line = auth_line
        if self.reject or auth_line != self.expected_auth_line:
            await ws.send("authentication failure; does not look like a valid user name")
            await ws.close()
            return
        await ws.send("OK" + "".join(self.output_lines))
        try:
            async for frame in ws:
                if frame == "2":
                    continue  # keepalive, no reply
                if frame.startswith("1:"):
                    _, cols, rows, _ = frame.split(":", 3)
                    self.received_resizes.append((int(cols), int(rows)))
                    continue
                if frame.startswith("0:"):
                    _, _length, data = frame.split(":", 2)
                    self.received_frames.append(data)
                    await ws.send(f"echo:{data}")
        except websockets.ConnectionClosed:
            pass

    async def start(self) -> str:
        self._server = await websockets.serve(self._handler, "127.0.0.1", 0)
        port = self._server.sockets[0].getsockname()[1]
        return f"ws://127.0.0.1:{port}"

    async def stop(self):
        self._server.close()
        await self._server.wait_closed()
```

- [ ] **Step 2: Write the failing tests**

```python
# backend/tests/test_ptybridge.py
import asyncio

import pytest
import websockets

from proxploy.services.ptybridge import PtyBridgeError, bridge_pty, connect_upstream_pty
from tests.fakes.pve_ws import FakeXtermUpstream


async def _connect_direct(url):
    """Bypass the SSRF/TLS-pinning wrapper for handshake-only tests — a plain
    ws:// loopback fake server, so this exercises connect_upstream_pty's
    protocol logic without also re-testing Task 1's already-covered TLS path."""
    return await websockets.connect(url, subprotocols=["binary"])


def test_handshake_succeeds_and_flushes_buffered_output():
    async def run():
        fake = FakeXtermUpstream(expected_auth_line="proxploy@pve!console:PVEVNC:abc\n",
                                 output_lines=["Welcome\n"])
        url = await fake.start()
        try:
            ws = await _connect_direct(url)
            await ws.send("proxploy@pve!console:PVEVNC:abc\n")
            first = await ws.recv()
            assert first == "OKWelcome\n"
        finally:
            await fake.stop()
    asyncio.run(run())


def test_connect_upstream_pty_raises_on_rejected_auth():
    async def run():
        fake = FakeXtermUpstream(expected_auth_line="ignored", reject=True)
        url = await fake.start()
        try:
            with pytest.raises(PtyBridgeError, match="does not look like a valid user"):
                await connect_upstream_pty(
                    address="unused", node="pve1", guest_kind="lxc", vmid=150,
                    upstream_user="proxploy@pve!console", upstream_ticket="PVEVNC:abc",
                    upstream_port="5900", verify_tls=True, tls_fingerprint=None,
                    ws_connect=lambda *a, **k: websockets.connect(url, subprotocols=["binary"]),
                )
        finally:
            await fake.stop()
    asyncio.run(run())


def test_bridge_pty_translates_resize_and_keystrokes():
    async def run():
        fake = FakeXtermUpstream(expected_auth_line="proxploy@pve!console:PVEVNC:abc\n")
        url = await fake.start()
        try:
            upstream = await connect_upstream_pty(
                address="unused", node="pve1", guest_kind="lxc", vmid=150,
                upstream_user="proxploy@pve!console", upstream_ticket="PVEVNC:abc",
                upstream_port="5900", verify_tls=True, tls_fingerprint=None,
                ws_connect=lambda *a, **k: websockets.connect(url, subprotocols=["binary"]),
            )

            sent, closed = [], []

            class FakeBrowserWs:
                async def receive(self):
                    if not sent:
                        return {"type": "websocket.receive", "text": '{"type":"resize","cols":100,"rows":40}'}
                    if len(sent) == 1:
                        return {"type": "websocket.receive", "text": "ls\n"}
                    return {"type": "websocket.disconnect"}

                async def send_text(self, data):
                    sent.append(data)

                async def close(self, code=1000):
                    closed.append(code)

            await bridge_pty(FakeBrowserWs(), upstream, idle_timeout_s=5.0)

            assert fake.received_resizes == [(100, 40)]
            assert fake.received_frames == ["ls\n"]
            assert any("echo:ls" in s for s in sent)
            assert closed
        finally:
            await fake.stop()
    asyncio.run(run())
```

- [ ] **Step 3: Run to verify failures**

Run: `cd backend && pytest tests/test_ptybridge.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'proxploy.services.ptybridge'`.

- [ ] **Step 4: Write `services/ptybridge.py`**

```python
"""Bridges a browser-facing FastAPI WebSocket to Proxmox's termproxy/xtermjs
websocket. See the plan's "Confirmed, not assumed" note for the wire protocol
(reverse-engineered from Proxmox's own pve-xtermjs client) and the "Spike
correction" note for the known API-token-vs-termproxy PVE limitation this
module's PtyBridgeError surfaces rather than hides."""
import asyncio
import json
import ssl
from urllib.parse import urlparse

import websockets

from proxploy.services.proxmox import open_validated_tcp_socket, tls_fingerprint_sha256


class PtyBridgeError(RuntimeError):
    pass


def _guest_path(node: str, guest_kind: str | None, vmid: int | None) -> str:
    if guest_kind is None:
        return f"/nodes/{node}"
    return f"/nodes/{node}/{guest_kind}/{vmid}"


async def connect_upstream_pty(*, address: str, node: str, guest_kind: str | None,
                                vmid: int | None, upstream_user: str,
                                upstream_ticket: str, upstream_port: str,
                                verify_tls: bool, tls_fingerprint: str | None,
                                ws_connect=None):
    """ws_connect is an injection seam for tests (skips the real TLS/SSRF path
    against a plain ws:// loopback fake); production callers omit it and get
    the real wss:// connection below."""
    if ws_connect is None:
        url = urlparse(address)
        host = url.hostname
        uri = (f"wss://{host}:8006/api2/json{_guest_path(node, guest_kind, vmid)}"
               f"/vncwebsocket?port={upstream_port}&vncticket={upstream_ticket}")
        if not verify_tls and tls_fingerprint:
            seen = tls_fingerprint_sha256(host, 8006)
            if seen != tls_fingerprint.upper():
                raise PtyBridgeError(
                    f"TLS fingerprint mismatch: pinned {tls_fingerprint}, got {seen}")
        ctx = ssl.create_default_context() if verify_tls else ssl._create_unverified_context()
        sock = open_validated_tcp_socket(host, 8006)
        ws_connect = lambda: websockets.connect(
            uri, subprotocols=["binary"], sock=sock, ssl=ctx, server_hostname=host)
        upstream = await ws_connect()
    else:
        upstream = await ws_connect()

    await upstream.send(f"{upstream_user}:{upstream_ticket}\n")
    try:
        first = await asyncio.wait_for(upstream.recv(), timeout=10.0)
    except (TimeoutError, websockets.ConnectionClosed) as e:
        raise PtyBridgeError(f"termproxy handshake failed: {e}") from e
    if not first.startswith("OK"):
        await upstream.close()
        raise PtyBridgeError(f"termproxy rejected the handshake: {first}")
    return upstream


async def bridge_pty(browser_ws, upstream_ws, *, idle_timeout_s: float) -> None:
    """Doc 05 framing on the browser side: raw text keystrokes/output, one
    JSON control frame `{"type":"resize",...}` from the client, one
    `{"type":"exit","code":...}` from us before close. Proxmox side: see the
    plan's wire-protocol note (0:/1:/2 framing)."""
    exit_code = 0

    async def from_browser():
        while True:
            msg = await asyncio.wait_for(browser_ws.receive(), timeout=idle_timeout_s)
            if msg.get("type") == "websocket.disconnect":
                return
            text = msg.get("text")
            if text is None:
                continue
            try:
                control = json.loads(text)
            except ValueError:
                control = None
            if isinstance(control, dict) and control.get("type") == "resize":
                await upstream_ws.send(f"1:{control['cols']}:{control['rows']}:")
            else:
                payload = text.encode("utf-8")
                await upstream_ws.send(f"0:{len(payload)}:{text}")

    async def from_upstream():
        async for frame in upstream_ws:
            await browser_ws.send_text(frame)

    try:
        done, pending = await asyncio.wait(
            [asyncio.create_task(from_browser()), asyncio.create_task(from_upstream())],
            return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
    except (TimeoutError, websockets.ConnectionClosed):
        exit_code = 1
    finally:
        await browser_ws.send_text(json.dumps({"type": "exit", "code": exit_code}))
        await browser_ws.close()
        await upstream_ws.close()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_ptybridge.py -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Run the full backend suite**

Run: `cd backend && pytest tests/ -q -m "not pve_integration and not e2e"`
Expected: 318 + 3 = 321 passed.

- [ ] **Step 7: Commit**

```bash
git add backend/proxploy/services/ptybridge.py backend/tests/fakes/pve_ws.py backend/tests/test_ptybridge.py
git commit -m "feat(console): PtyBridge — xtermjs protocol translation over the upstream websocket"
```

---

## Task 4: `ConsoleProxy` — transparent binary VNC bridge

**Files:**
- Create: `backend/proxploy/services/consoleproxy.py`
- Test: `backend/tests/test_consoleproxy.py`

**Interfaces:**
- Produces: `async connect_upstream_vnc(*, address: str, node: str, vmid: int, upstream_ticket: str, upstream_port: str, verify_tls: bool, tls_fingerprint: str | None, ws_connect=None) -> websockets client connection`. `async bridge_binary(browser_ws, upstream_ws, *, idle_timeout_s: float) -> None`.
- Consumes: same `open_validated_tcp_socket`/`tls_fingerprint_sha256` as Task 3.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_consoleproxy.py
import asyncio

import websockets

from proxploy.services.consoleproxy import bridge_binary, connect_upstream_vnc


class FakeRfbUpstream:
    """No auth-line handshake for VNC — the ticket is validated by Proxmox at
    the URL-query-param stage; the first frame IS the RFB greeting."""

    def __init__(self):
        self.received: list[bytes] = []
        self._server = None

    async def _handler(self, ws):
        await ws.send(b"RFB 003.008\n")
        try:
            async for frame in ws:
                self.received.append(frame)
                await ws.send(b"ack:" + frame)
        except websockets.ConnectionClosed:
            pass

    async def start(self) -> str:
        self._server = await websockets.serve(self._handler, "127.0.0.1", 0)
        return f"ws://127.0.0.1:{self._server.sockets[0].getsockname()[1]}"

    async def stop(self):
        self._server.close()
        await self._server.wait_closed()


def test_connect_upstream_vnc_gets_rfb_greeting_with_no_auth_frame():
    async def run():
        fake = FakeRfbUpstream()
        url = await fake.start()
        try:
            upstream = await connect_upstream_vnc(
                address="unused", node="pve1", vmid=200, upstream_ticket="PVEVNC:def",
                upstream_port="5902", verify_tls=True, tls_fingerprint=None,
                ws_connect=lambda: websockets.connect(url, subprotocols=["binary"]),
            )
            greeting = await upstream.recv()
            assert greeting == b"RFB 003.008\n"
        finally:
            await fake.stop()
    asyncio.run(run())


def test_bridge_binary_relays_bytes_untranslated():
    async def run():
        fake = FakeRfbUpstream()
        url = await fake.start()
        try:
            upstream = await connect_upstream_vnc(
                address="unused", node="pve1", vmid=200, upstream_ticket="PVEVNC:def",
                upstream_port="5902", verify_tls=True, tls_fingerprint=None,
                ws_connect=lambda: websockets.connect(url, subprotocols=["binary"]),
            )
            await upstream.recv()  # consume the greeting like a real RFB client would

            sent, closed = [], []
            frames_in = [b"\x03\x08\x01\x00", None]  # one client RFB frame, then disconnect

            class FakeBrowserWs:
                async def receive(self):
                    frame = frames_in.pop(0)
                    if frame is None:
                        return {"type": "websocket.disconnect"}
                    return {"type": "websocket.receive", "bytes": frame}

                async def send_bytes(self, data):
                    sent.append(data)

                async def close(self, code=1000):
                    closed.append(code)

            await bridge_binary(FakeBrowserWs(), upstream, idle_timeout_s=5.0)

            assert fake.received == [b"\x03\x08\x01\x00"]
            assert sent == [b"ack:\x03\x08\x01\x00"]
            assert closed
        finally:
            await fake.stop()
    asyncio.run(run())
```

- [ ] **Step 2: Run to verify failures**

Run: `cd backend && pytest tests/test_consoleproxy.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Write `services/consoleproxy.py`**

```python
"""Transparent binary VNC bridge (doc 05 §3): no protocol translation, unlike
PtyBridge — the ticket is validated by Proxmox at websocket-upgrade time via
the URL query params, so there's no client-sent auth line; the first upstream
frame is the RFB greeting itself, which noVNC's own RFB class consumes."""
import asyncio
import ssl
from urllib.parse import urlparse

import websockets

from proxploy.services.proxmox import open_validated_tcp_socket, tls_fingerprint_sha256


async def connect_upstream_vnc(*, address: str, node: str, vmid: int,
                                upstream_ticket: str, upstream_port: str,
                                verify_tls: bool, tls_fingerprint: str | None,
                                ws_connect=None):
    if ws_connect is None:
        url = urlparse(address)
        host = url.hostname
        uri = (f"wss://{host}:8006/api2/json/nodes/{node}/qemu/{vmid}"
               f"/vncwebsocket?port={upstream_port}&vncticket={upstream_ticket}")
        if not verify_tls and tls_fingerprint:
            seen = tls_fingerprint_sha256(host, 8006)
            if seen != tls_fingerprint.upper():
                raise RuntimeError(
                    f"TLS fingerprint mismatch: pinned {tls_fingerprint}, got {seen}")
        ctx = ssl.create_default_context() if verify_tls else ssl._create_unverified_context()
        sock = open_validated_tcp_socket(host, 8006)
        ws_connect = lambda: websockets.connect(
            uri, subprotocols=["binary"], sock=sock, ssl=ctx, server_hostname=host)
    return await ws_connect()


async def bridge_binary(browser_ws, upstream_ws, *, idle_timeout_s: float) -> None:
    async def from_browser():
        while True:
            msg = await asyncio.wait_for(browser_ws.receive(), timeout=idle_timeout_s)
            if msg.get("type") == "websocket.disconnect":
                return
            data = msg.get("bytes")
            if data is not None:
                await upstream_ws.send(data)

    async def from_upstream():
        async for frame in upstream_ws:
            await browser_ws.send_bytes(frame)

    try:
        done, pending = await asyncio.wait(
            [asyncio.create_task(from_browser()), asyncio.create_task(from_upstream())],
            return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
    except (TimeoutError, websockets.ConnectionClosed):
        pass
    finally:
        await browser_ws.close()
        await upstream_ws.close()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_consoleproxy.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Run the full backend suite**

Run: `cd backend && pytest tests/ -q -m "not pve_integration and not e2e"`
Expected: 321 + 2 = 323 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/proxploy/services/consoleproxy.py backend/tests/test_consoleproxy.py
git commit -m "feat(console): ConsoleProxy — transparent binary VNC bridge"
```

---

## Task 5: `POST /apps/{id}/console/tickets` + `WS /apps/{id}/console/ws`

**Files:**
- Create: `backend/proxploy/api/consoles.py`
- Modify: `backend/proxploy/api/__init__.py`
- Test: `backend/tests/test_consoles_api.py`

**Interfaces:**
- Produces: `router = APIRouter(prefix="", tags=["consoles"])` registered at the top level (paths already carry their own `/apps`, `/hosts`, `/vms` prefixes per doc 05, so this router does NOT get a shared prefix like `apps.router`/`vms.router` do — mirrors how `jobs.router` is mounted).
- Consumes: `services.lifecycle._resolve`-shaped host/node lookup (this task writes its own small resolver instead of importing the private `_resolve`, since that one is job-context-only and blocking-via-thread; here it's a plain sync route so no thread hop is needed), `services.consoletickets.mint_ticket`/`redeem_ticket`, `services.ptybridge.connect_upstream_pty`/`bridge_pty`, `services.proxmox.ProxmoxClient.termproxy`, `services.audit.write_audit`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_consoles_api.py
import json

from tests.fakes.pve import FakePVE
from tests.fakes.pve_ws import FakeXtermUpstream
from tests.support import make_app, seed_host_row


def _seed_app(db, host):
    from proxploy.models import App

    a = App(host_id=host.id, ctid=150, name="immich", status="running", slug="immich-1")
    db.add(a)
    db.commit()
    return a


def test_console_tickets_requires_operator_and_entitlement(tmp_path):
    fake = FakePVE()
    app = make_app(tmp_path, fake=fake)
    with app.state.sessionmaker() as db:
        host = seed_host_row(db)
        a = _seed_app(db, host)
    from fastapi.testclient import TestClient

    client = TestClient(app)
    r = client.post(f"/api/v1/apps/{a.id}/console/tickets")
    assert r.status_code == 401  # no session at all


def test_console_tickets_mints_a_ticket_and_audits(tmp_path, monkeypatch):
    fake = FakePVE()
    fake.termproxy_response = {"user": "proxploy@pve!console", "ticket": "PVEVNC:abc",
                                "port": "5900", "upid": "UPID:pve1:...:termproxy::proxploy@pve:"}
    app = make_app(tmp_path, fake=fake)
    with app.state.sessionmaker() as db:
        host = seed_host_row(db)
        a = _seed_app(db, host)
        from proxploy.models import HostCredential
        import json as jsonlib
        blob, ver = app.state.secretstore.encrypt(
            jsonlib.dumps({"token_id": "proxploy@pve!console", "token_secret": "s3cret"}).encode())
        db.add(HostCredential(host_id=host.id, kind="api_token", encrypted_blob=blob, key_version=ver))
        db.commit()
        app_id = a.id

    from tests.conftest import login_as_owner  # existing Phase-1 test helper

    from fastapi.testclient import TestClient
    client = TestClient(app)
    login_as_owner(client)

    r = client.post(f"/api/v1/apps/{app_id}/console/tickets")
    assert r.status_code == 200
    body = r.json()
    assert "ticket" in body and "expires_at" in body

    with app.state.sessionmaker() as db:
        from proxploy.models import AuditEvent
        row = db.query(AuditEvent).filter_by(action="console.open").one()
        assert row.target_type == "app" and row.target_id == app_id
        assert "ticket" not in (row.params or {})  # never audit the raw/upstream ticket


def test_console_ws_bridges_after_redeeming_ticket(tmp_path):
    fake = FakePVE()
    fake.termproxy_response = {"user": "proxploy@pve!console", "ticket": "PVEVNC:abc",
                               "port": "5900", "upid": "UPID:..."}
    app = make_app(tmp_path, fake=fake)
    with app.state.sessionmaker() as db:
        host = seed_host_row(db)
        a = _seed_app(db, host)
        from proxploy.models import HostCredential
        import json as jsonlib
        blob, ver = app.state.secretstore.encrypt(
            jsonlib.dumps({"token_id": "proxploy@pve!console", "token_secret": "s3cret"}).encode())
        db.add(HostCredential(host_id=host.id, kind="api_token", encrypted_blob=blob, key_version=ver))
        db.commit()
        app_id = a.id

    import asyncio
    from tests.fakes.pve_ws import FakeXtermUpstream

    async def upstream_server():
        fake_ws = FakeXtermUpstream(expected_auth_line="proxploy@pve!console:PVEVNC:abc\n")
        url = await fake_ws.start()
        return fake_ws, url

    fake_ws, url = asyncio.run(upstream_server())
    import proxploy.services.ptybridge as ptybridge_mod
    import websockets

    async def fake_ws_connect(*a, **k):
        return await websockets.connect(url, subprotocols=["binary"])

    orig = ptybridge_mod.connect_upstream_pty

    async def patched(**kwargs):
        kwargs["ws_connect"] = fake_ws_connect
        return await orig(**kwargs)
    ptybridge_mod.connect_upstream_pty = patched
    try:
        from tests.conftest import login_as_owner
        from fastapi.testclient import TestClient
        client = TestClient(app)
        login_as_owner(client)
        ticket = client.post(f"/api/v1/apps/{app_id}/console/tickets").json()["ticket"]

        with client.websocket_connect(f"/api/v1/apps/{app_id}/console/ws?ticket={ticket}") as ws:
            first = ws.receive_text()
            assert first == "OK"
            ws.send_text("ls\n")
            echoed = ws.receive_text()
            assert "echo:ls" in echoed
    finally:
        ptybridge_mod.connect_upstream_pty = orig
        asyncio.run(fake_ws.stop())
```

*(Note for the implementer: `login_as_owner`/similar session-cookie test helpers already exist somewhere in Phase 1's `tests/conftest.py` — grep for how existing authed-route tests, e.g. in `test_hosts_api.py`, get a logged-in `TestClient` and reuse that exact helper name/shape rather than the placeholder name above if it differs.)*

- [ ] **Step 2: Run to verify failures**

Run: `cd backend && pytest tests/test_consoles_api.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'proxploy.api.consoles'`.

- [ ] **Step 3: Write `api/consoles.py`**

```python
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
from proxploy.services.audit import write_audit
from proxploy.services.consoleproxy import bridge_binary, connect_upstream_vnc
from proxploy.services.consoletickets import mint_ticket, redeem_ticket
from proxploy.services.ptybridge import PtyBridgeError, bridge_pty, connect_upstream_pty
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
_require_admin = require_role("admin")


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


async def _run_pty_ws(websocket: WebSocket, ticket: str | None):
    if ticket is None:
        await websocket.close(code=4401)
        return
    db = websocket.app.state.sessionmaker()
    try:
        row = redeem_ticket(db, ticket)
        if row is None:
            await websocket.close(code=4401)
            return
        host_id = {"app_console": lambda: db.get(App, row.target_id).host_id,
                   "node_shell": lambda: row.target_id}[row.kind]()
        host = db.get(Host, host_id)
    finally:
        db.close()
    await websocket.accept()
    try:
        upstream = await connect_upstream_pty(
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
```

*(Node-shell route (`/hosts/{id}/shell/tickets` + `/hosts/{id}/shell/ws`) is deliberately Task 6, not here — it needs the `node_shell_enabled` opt-in check this task's `_run_pty_ws` helper already dispatches on via `row.kind`.)*

- [ ] **Step 4: Register the router**

In `backend/proxploy/api/__init__.py`, add `from proxploy.api import consoles` and `api_router.include_router(consoles.router)` alongside the other `include_router` calls.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_consoles_api.py -v`
Expected: PASS (3 tests). If `login_as_owner`-shaped helper name doesn't match what `tests/conftest.py` actually exports, adjust the test's import to the real helper (grep `tests/test_hosts_api.py` for the exact name in use — do not invent a second login-helper).

- [ ] **Step 6: Run the full backend suite**

Run: `cd backend && pytest tests/ -q -m "not pve_integration and not e2e"`
Expected: 323 + 3 = 326 passed.

- [ ] **Step 7: Commit**

```bash
git add backend/proxploy/api/consoles.py backend/proxploy/api/__init__.py backend/tests/test_consoles_api.py
git commit -m "feat(console): app console + VM VNC ticket and websocket routes"
```

---

## Task 6: Node shell — `node_shell_enabled` opt-in + `POST/WS /hosts/{id}/shell/*`

**Files:**
- Modify: `backend/proxploy/api/consoles.py`, `backend/proxploy/api/hosts.py`
- Test: `backend/tests/test_consoles_api.py` (extend), `backend/tests/test_hosts_api.py` (extend)

**Interfaces:**
- Produces: `PATCH /hosts/{host_id}` (admin role) accepting `{"node_shell_enabled": bool}`.
- Consumes: Task 5's `_run_pty_ws`, `_proxmox_client_for_host`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_hosts_api.py (append)
def test_patch_host_toggles_node_shell_enabled(tmp_path):
    from tests.support import make_app, seed_host_row
    from tests.conftest import login_as_owner
    from fastapi.testclient import TestClient

    app = make_app(tmp_path)
    with app.state.sessionmaker() as db:
        host = seed_host_row(db)
        host_id = host.id
    client = TestClient(app)
    login_as_owner(client)
    r = client.patch(f"/api/v1/hosts/{host_id}", json={"node_shell_enabled": True})
    assert r.status_code == 200
    assert r.json()["node_shell_enabled"] is True

    with app.state.sessionmaker() as db:
        from proxploy.models import Host
        assert db.get(Host, host_id).node_shell_enabled is True
```

```python
# backend/tests/test_consoles_api.py (append)
def test_shell_ticket_requires_node_shell_enabled(tmp_path):
    from tests.fakes.pve import FakePVE
    from tests.support import make_app, seed_host_row
    from tests.conftest import login_as_owner
    from fastapi.testclient import TestClient

    fake = FakePVE()
    app = make_app(tmp_path, fake=fake)
    with app.state.sessionmaker() as db:
        host = seed_host_row(db)  # node_shell_enabled defaults False
        from proxploy.models import HostCredential
        import json as jsonlib
        blob, ver = app.state.secretstore.encrypt(
            jsonlib.dumps({"token_id": "proxploy@pve!console", "token_secret": "s3cret"}).encode())
        db.add(HostCredential(host_id=host.id, kind="api_token", encrypted_blob=blob, key_version=ver))
        db.commit()
        host_id = host.id
    client = TestClient(app)
    login_as_owner(client)
    r = client.post(f"/api/v1/hosts/{host_id}/shell/tickets")
    assert r.status_code == 409
    assert "node shell" in r.json()["detail"].lower()
```

- [ ] **Step 2: Run to verify failures**

Run: `cd backend && pytest tests/test_hosts_api.py tests/test_consoles_api.py -v -k "node_shell or shell_ticket"`
Expected: FAIL — `404` (route doesn't exist).

- [ ] **Step 3: Add `PATCH /hosts/{host_id}` to `api/hosts.py`**

```python
from pydantic import BaseModel


class HostPatchIn(BaseModel):
    node_shell_enabled: bool


@router.patch("/{host_id}")
def patch_host(host_id: int, body: HostPatchIn, db=Depends(get_db),
              user: User = Depends(require_role("admin"))):
    h = db.get(Host, host_id)
    if h is None:
        raise HTTPException(404, "host not found")
    h.node_shell_enabled = body.node_shell_enabled
    db.commit()
    return {"id": h.id, "node_shell_enabled": h.node_shell_enabled}
```

- [ ] **Step 4: Add the shell ticket + WS routes to `api/consoles.py`**

```python
@router.post("/hosts/{host_id}/shell/tickets",
             dependencies=[Depends(_require_admin), Depends(require_entitlement("terminal.node"))])
def node_shell_ticket(request: Request, host_id: int, db=Depends(get_db),
                      user: User = Depends(_require_admin)):
    host = db.get(Host, host_id)
    if host is None:
        raise HTTPException(404, "host not found")
    if not host.node_shell_enabled:
        raise HTTPException(409, "node shell is not enabled for this host — "
                             "opt in via host settings first (doc 08 §9: a "
                             "second, deliberate gate on top of RBAC)")
    client = _proxmox_client_for_host(request.app.state, db, host)
    node = host.node_name or ""
    upstream = client.node_termproxy(node)
    raw, expires_at = mint_ticket(
        db, user_id=user.id, kind="node_shell", target_id=host.id, node=node,
        guest_kind=None, vmid=None, upstream_user=upstream["user"],
        upstream_ticket=upstream["ticket"], upstream_port=str(upstream["port"]),
        ttl_s=request.app.state.settings.console_ticket_ttl_s)
    write_audit(db, actor_type="user", actor_id=user.id, action="console.open",
               target_type="host", target_id=host.id,
               ip=request.client.host if request.client else None)
    return {"ticket": raw, "expires_at": expires_at.isoformat() + "Z"}


@router.websocket("/hosts/{host_id}/shell/ws")
async def node_shell_ws(websocket: WebSocket, host_id: int, ticket: str | None = None):
    await _run_pty_ws(websocket, ticket)
```

`_run_pty_ws`'s existing `{"app_console": ..., "node_shell": lambda: row.target_id}` dispatch (Task 5) already resolves a `node_shell` ticket's `host_id` correctly (`row.target_id` IS the host id for this kind) — no change needed there.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_hosts_api.py tests/test_consoles_api.py -v`
Expected: PASS (all, including the two new ones).

- [ ] **Step 6: Run the full backend suite**

Run: `cd backend && pytest tests/ -q -m "not pve_integration and not e2e"`
Expected: 326 + 2 = 328 passed.

- [ ] **Step 7: Commit**

```bash
git add backend/proxploy/api/hosts.py backend/proxploy/api/consoles.py backend/tests/test_hosts_api.py backend/tests/test_consoles_api.py
git commit -m "feat(console): node shell opt-in toggle + ticket/websocket routes"
```

---

## Task 7: Frontend — `Terminal` (xterm.js) wrapper + console ticket hook

**Files:**
- Create: `frontend/src/components/terminal/Terminal.tsx`, `frontend/src/api/consoles.ts`
- Modify: `frontend/package.json`
- Test: `frontend/src/tests/terminal.test.tsx`, `frontend/src/tests/consoles-api.test.tsx`

**Interfaces:**
- Produces: `Terminal({ wsUrl, onDrop }: { wsUrl: string; onDrop?: () => void })` component — mounts xterm.js, opens the WebSocket itself, tears down on unmount. `onDrop` fires when the socket closes for any reason OTHER than this component's own unmount-cleanup (doc 06: "Reconnect = new ticket" — DoD "survive reconnect"); callers use it to re-mint a ticket and remount with a fresh `wsUrl`, done once in Task 8 and reused unchanged by Tasks 9/10. `useConsoleTicket(kind: 'app' | 'host' | 'vm', id: number)` — `useMutation` returning `{ ticket: string; expires_at: string }`, POSTing to the right path per `kind`.

- [ ] **Step 1: Add dependencies**

```bash
cd frontend && npm install @xterm/xterm @xterm/addon-fit
```

*(Deviation from doc 06's "fit + webgl addons": the webgl addon adds context-loss/fallback handling for a marginal render-perf gain over the default canvas renderer with no functional difference to the user — skipped as unrequested-complexity-for-its-own-sake; noted here rather than silently, matching this project's practice of calling out documented deviations.)*

- [ ] **Step 2: Write the failing hook test**

```tsx
// frontend/src/tests/consoles-api.test.tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { api } from '../api/client'
import { useConsoleTicket } from '../api/consoles'

vi.mock('../api/client', () => ({ api: vi.fn() }))

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient()
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
}

describe('useConsoleTicket', () => {
  it('POSTs to the app console path for kind=app', async () => {
    vi.mocked(api).mockResolvedValueOnce({ ticket: 't1', expires_at: '2026-01-01T00:00:00Z' })
    const { result } = renderHook(() => useConsoleTicket('app', 42), { wrapper })
    result.current.mutate()
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(api).toHaveBeenCalledWith('/apps/42/console/tickets', { method: 'POST' })
  })

  it('POSTs to the host shell path for kind=host', async () => {
    vi.mocked(api).mockResolvedValueOnce({ ticket: 't2', expires_at: '2026-01-01T00:00:00Z' })
    const { result } = renderHook(() => useConsoleTicket('host', 7), { wrapper })
    result.current.mutate()
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(api).toHaveBeenCalledWith('/hosts/7/shell/tickets', { method: 'POST' })
  })

  it('POSTs to the vm console path for kind=vm', async () => {
    vi.mocked(api).mockResolvedValueOnce({ ticket: 't3', expires_at: '2026-01-01T00:00:00Z' })
    const { result } = renderHook(() => useConsoleTicket('vm', 9), { wrapper })
    result.current.mutate()
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(api).toHaveBeenCalledWith('/vms/9/console/tickets', { method: 'POST' })
  })
})
```

- [ ] **Step 3: Run to verify failure**

Run: `cd frontend && npx vitest run src/tests/consoles-api.test.tsx`
Expected: FAIL — `Failed to resolve import "../api/consoles"`.

- [ ] **Step 4: Write `api/consoles.ts`**

```ts
import { useMutation } from '@tanstack/react-query'
import { api } from './client'

export type ConsoleTicket = { ticket: string; expires_at: string }
export type ConsoleKind = 'app' | 'host' | 'vm'

const PATH: Record<ConsoleKind, (id: number) => string> = {
  app: (id) => `/apps/${id}/console/tickets`,
  host: (id) => `/hosts/${id}/shell/tickets`,
  vm: (id) => `/vms/${id}/console/tickets`,
}

const WS_PATH: Record<ConsoleKind, (id: number, ticket: string) => string> = {
  app: (id, t) => `/apps/${id}/console/ws?ticket=${t}`,
  host: (id, t) => `/hosts/${id}/shell/ws?ticket=${t}`,
  vm: (id, t) => `/vms/${id}/vnc/ws?ticket=${t}`,
}

export function useConsoleTicket(kind: ConsoleKind, id: number) {
  return useMutation({
    mutationFn: () => api<ConsoleTicket>(PATH[kind](id), { method: 'POST' }),
  })
}

export function consoleWsUrl(kind: ConsoleKind, id: number, ticket: string): string {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${location.host}/api/v1${WS_PATH[kind](id, ticket)}`
}
```

- [ ] **Step 5: Run to verify the hook test passes**

Run: `cd frontend && npx vitest run src/tests/consoles-api.test.tsx`
Expected: PASS (3 tests).

- [ ] **Step 6: Write the failing `Terminal` component test**

```tsx
// frontend/src/tests/terminal.test.tsx
import { render, waitFor } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { Terminal } from '../components/terminal/Terminal'

class FakeWebSocket {
  static instances: FakeWebSocket[] = []
  onopen: (() => void) | null = null
  onmessage: ((e: { data: string }) => void) | null = null
  onclose: (() => void) | null = null
  sent: string[] = []
  constructor(public url: string) { FakeWebSocket.instances.push(this) }
  send(data: string) { this.sent.push(data) }
  close() { this.onclose?.() }
}

beforeEach(() => {
  FakeWebSocket.instances = []
  // @ts-expect-error test stub
  global.WebSocket = FakeWebSocket
})

describe('Terminal', () => {
  it('opens a websocket at the given url and writes incoming frames', async () => {
    render(<Terminal wsUrl="ws://test/console" />)
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1))
    const ws = FakeWebSocket.instances[0]
    expect(ws.url).toBe('ws://test/console')
    ws.onopen?.()
    ws.onmessage?.({ data: 'hello\n' })
    // no throw = xterm.js accepted the write; deeper terminal-content
    // assertions would need a headless-canvas shim this suite doesn't have.
  })

  it('sends a resize control frame on mount (initial fit)', async () => {
    render(<Terminal wsUrl="ws://test/console" />)
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1))
    const ws = FakeWebSocket.instances[0]
    ws.onopen?.()
    await waitFor(() => expect(ws.sent.some(s => s.includes('"type":"resize"'))).toBe(true))
  })

  it('calls onDrop when the socket closes on its own, not on unmount', async () => {
    const onDrop = vi.fn()
    const { unmount } = render(<Terminal wsUrl="ws://test/console" onDrop={onDrop} />)
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1))
    FakeWebSocket.instances[0].onclose?.()
    expect(onDrop).toHaveBeenCalledTimes(1)
    onDrop.mockClear()
    unmount()  // cleanup also calls ws.close(), which must NOT re-fire onDrop
    expect(onDrop).not.toHaveBeenCalled()
  })
})
```

- [ ] **Step 7: Run to verify failure**

Run: `cd frontend && npx vitest run src/tests/terminal.test.tsx`
Expected: FAIL — `Failed to resolve import "../components/terminal/Terminal"`.

- [ ] **Step 8: Write `components/terminal/Terminal.tsx`**

```tsx
import { FitAddon } from '@xterm/addon-fit'
import { Terminal as XTerm } from '@xterm/xterm'
import { useEffect, useRef } from 'react'

const THEME = {
  background: '#0a0e14', foreground: '#E8EDF4',
  red: '#F26D6D', green: '#3FCF8E', yellow: '#F5B544', blue: '#5B9DF9',
}

export function Terminal({ wsUrl, onDrop }: { wsUrl: string; onDrop?: () => void }) {
  const box = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!box.current) return
    const term = new XTerm({ theme: THEME, fontFamily: 'JetBrains Mono, monospace', fontSize: 12.5 })
    const fit = new FitAddon()
    term.loadAddon(fit)
    term.open(box.current)
    fit.fit()

    if (typeof WebSocket === 'undefined') return  // jsdom without a WS stub
    let unmounting = false
    const ws = new WebSocket(wsUrl)
    ws.onopen = () => {
      ws.send(JSON.stringify({ type: 'resize', cols: term.cols, rows: term.rows }))
    }
    ws.onmessage = (e) => {
      let data = e.data as string
      try {
        const control = JSON.parse(data)
        if (control?.type === 'exit') { term.write(`\r\n[session ended: ${control.code}]\r\n`); return }
      } catch { /* not a control frame — raw terminal text */ }
      term.write(data)
    }
    // The bridge (backend PtyBridge/ConsoleProxy) or the upstream Proxmox
    // socket can drop independently of anything the user did — doc 06's
    // "Reconnect = new ticket" / DoD "survive reconnect" means the CALLER
    // re-mints a ticket and remounts with a fresh wsUrl; this component only
    // has to tell them a drop happened, and not confuse its own teardown
    // (which also closes the socket) for one.
    ws.onclose = () => { if (!unmounting) onDrop?.() }
    const sub = term.onData((data) => ws.readyState === WebSocket.OPEN && ws.send(data))
    const resizeSub = term.onResize(({ cols, rows }) => {
      if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'resize', cols, rows }))
    })

    const onWindowResize = () => fit.fit()
    window.addEventListener('resize', onWindowResize)

    return () => {
      unmounting = true
      window.removeEventListener('resize', onWindowResize)
      sub.dispose()
      resizeSub.dispose()
      ws.close()
      term.dispose()
    }
  }, [wsUrl])

  return <div ref={box} style={{ background: '#0a0e14' }} className="h-[420px] rounded-ctl border border-line-soft p-2" />
}
```

- [ ] **Step 9: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/tests/terminal.test.tsx src/tests/consoles-api.test.tsx`
Expected: PASS (6 tests).

- [ ] **Step 10: Run the full frontend suite + build**

Run: `cd frontend && npx vitest run && npm run build`
Expected: 52 + 6 = 58 passed; clean build.

- [ ] **Step 11: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/src/components/terminal/Terminal.tsx frontend/src/api/consoles.ts frontend/src/tests/terminal.test.tsx frontend/src/tests/consoles-api.test.tsx
git commit -m "feat(console): xterm.js Terminal wrapper + console-ticket hooks"
```

*(Running tally for this plan's frontend test count, kept accurate task-by-task since later tasks' "run full suite" steps assert an exact number: baseline 52 + this task's 6 = 58.)*

---

## Task 8: Wire the CT console tab + Console quick-action on `AppCard`

**Files:**
- Modify: `frontend/src/routes/apps.tsx`, `frontend/src/components/AppCard.tsx`
- Test: extend an existing apps test file (grep for the current apps route test, e.g. `frontend/src/tests/apps.test.tsx` if one exists, else add assertions to `frontend/src/tests/terminal.test.tsx`)

**Interfaces:**
- Consumes: Task 7's `Terminal`, `useConsoleTicket`, `consoleWsUrl`.

- [ ] **Step 1: Write the failing test for the wired console tab**

```tsx
// frontend/src/tests/terminal.test.tsx (append)
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
vi.mock('../api/client', () => ({ api: vi.fn().mockResolvedValue({ ticket: 'tix', expires_at: '2026-01-01T00:00:00Z' }) }))

describe('AppConsole', () => {
  it('requests a ticket on mount and opens the terminal at the ticketed url', async () => {
    const { AppConsole } = await import('../routes/apps')
    const qc = new QueryClient()
    render(
      <QueryClientProvider client={qc}>
        <AppConsole appId={42} />
      </QueryClientProvider>,
    )
    await waitFor(() => expect(FakeWebSocket.instances.length).toBe(1))
    expect(FakeWebSocket.instances[0].url).toContain('/apps/42/console/ws?ticket=tix')
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npx vitest run src/tests/terminal.test.tsx -t AppConsole`
Expected: FAIL — `AppConsole` is not exported.

- [ ] **Step 3: Replace the `appConsoleRoute`/`appLogsRoute` placeholders in `apps.tsx`**

Find (per the exploration, near the bottom of `frontend/src/routes/apps.tsx`):

```ts
export const appLogsRoute = phaseTab('logs', 'Phase 5 (Console)', 'Live CT logs share the log-viewer with job transcripts.')
export const appConsoleRoute = phaseTab('console', 'Phase 5 (Console)', 'xterm.js over the proxied Proxmox termproxy websocket.')
```

Replace with:

```tsx
export function AppConsole({ appId }: { appId: number }) {
  const ticket = useConsoleTicket('app', appId)
  useEffect(() => { ticket.mutate() }, [appId])
  if (!ticket.data) return <EmptyState title="Opening console…" note="" />
  return (
    <Terminal key={ticket.data.ticket}
      wsUrl={consoleWsUrl('app', appId, ticket.data.ticket)}
      onDrop={() => ticket.mutate()} />
  )
}

function AppConsoleTab() {
  const { appId } = useParams({ strict: false }) as { appId: string }
  return <AppConsole appId={Number(appId)} />
}

export const appLogsRoute = phaseTab('logs', 'Phase 5 (Console)', 'Live CT logs share the log-viewer with job transcripts.')
export const appConsoleRoute = createRoute({
  getParentRoute: () => appDetailRoute, path: 'console', component: AppConsoleTab,
})
```

Add the needed imports at the top of `apps.tsx`: `import { useEffect } from 'react'`, `import { Terminal } from '../components/terminal/Terminal'`, `import { useConsoleTicket, consoleWsUrl } from '../api/consoles'`.

- [ ] **Step 4: Add the Console quick-action to `AppCard.tsx`**

```tsx
import { Button } from './ui/button'
```

Inside the existing `<div className="mt-3 border-t border-line-soft pt-3" onClick={(e) => e.stopPropagation()}>` block, alongside `<LifecycleActions .../>`:

```tsx
<Button variant="ghost" size="sm"
  onClick={() => navigate({ to: '/apps/$appId/console' as never, params: { appId: String(app.id) } as never })}>
  Console
</Button>
```

*(`Button` has no `size` prop today per the explored source — use the same `className="px-2 py-1 text-[11px]"` inline sizing `LifecycleActions` uses for its `size="sm"` case instead, for visual consistency without adding a prop the component doesn't have.)*

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/tests/terminal.test.tsx`
Expected: PASS (all, including the new `AppConsole` test).

- [ ] **Step 6: Run the full frontend suite + build**

Run: `cd frontend && npx vitest run && npm run build`
Expected: 58 + 1 = 59 passed; clean build.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/routes/apps.tsx frontend/src/components/AppCard.tsx frontend/src/tests/terminal.test.tsx
git commit -m "feat(apps): wire CT console tab + Console quick-action on the app card"
```

*(Reconnect note for this task and Tasks 9/10, which share the exact same shape: `AppConsole` should pass `onDrop={() => ticket.mutate()}` to `Terminal` and key the `Terminal` remount on `ticket.data?.ticket` — e.g. `<Terminal key={ticket.data.ticket} wsUrl={...} onDrop={() => ticket.mutate()} />` — so a dropped socket re-mints a ticket and a fresh `Terminal` instance opens a new one, satisfying doc 06's "Reconnect = new ticket" / the DoD's "survive reconnect" clause. Add this same one-line wiring to `VmConsole` (Task 9) and `NodeShellSection` (Task 10) — no new test needed there beyond Task 7's `onDrop` unit test, since the wiring is identical and mechanical.)*

---

## Task 9: Frontend — `VncConsole` (noVNC) wrapper + wire the VM console tab

**Files:**
- Create: `frontend/src/components/console/VncConsole.tsx`
- Modify: `frontend/src/routes/vms.tsx`, `frontend/package.json`
- Test: `frontend/src/tests/vncconsole.test.tsx`

**Interfaces:**
- Produces: `VncConsole({ wsUrl }: { wsUrl: string })`.
- Consumes: Task 7's `useConsoleTicket`/`consoleWsUrl`.

- [ ] **Step 1: Add the dependency**

```bash
cd frontend && npm install @novnc/novnc
```

*(MPL-2.0, link-only per doc 03 — `import RFB from '@novnc/novnc/core/rfb'` below imports it as a normal npm dependency; no noVNC file is ever copied into this tree.)*

- [ ] **Step 2: Write the failing test**

```tsx
// frontend/src/tests/vncconsole.test.tsx
import { render, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

const rfbInstances: any[] = []
vi.mock('@novnc/novnc/core/rfb', () => ({
  default: class FakeRFB {
    constructor(public target: HTMLElement, public url: string) { rfbInstances.push(this) }
    addEventListener = vi.fn()
    disconnect = vi.fn()
    sendCtrlAltDel = vi.fn()
  },
}))

describe('VncConsole', () => {
  it('constructs an RFB instance against the given websocket url', async () => {
    const { VncConsole } = await import('../components/console/VncConsole')
    render(<VncConsole wsUrl="wss://test/vnc" />)
    await waitFor(() => expect(rfbInstances).toHaveLength(1))
    expect(rfbInstances[0].url).toBe('wss://test/vnc')
  })

  it('disconnects the RFB session on unmount', async () => {
    const { VncConsole } = await import('../components/console/VncConsole')
    const { unmount } = render(<VncConsole wsUrl="wss://test/vnc" />)
    await waitFor(() => expect(rfbInstances).toHaveLength(1))
    unmount()
    expect(rfbInstances[0].disconnect).toHaveBeenCalled()
  })

  it('calls onDisconnect when RFB fires its own disconnect event (not on unmount)', async () => {
    const onDisconnect = vi.fn()
    const { VncConsole } = await import('../components/console/VncConsole')
    const { unmount } = render(<VncConsole wsUrl="wss://test/vnc" onDisconnect={onDisconnect} />)
    await waitFor(() => expect(rfbInstances).toHaveLength(1))
    const rfb = rfbInstances[0]
    // addEventListener is a vi.fn() mock — grab the handler it was registered
    // with and invoke it directly, exactly as the real RFB would on a drop.
    const [, handler] = rfb.addEventListener.mock.calls.find((c: any[]) => c[0] === 'disconnect')
    handler()
    expect(onDisconnect).toHaveBeenCalledTimes(1)
    onDisconnect.mockClear()
    unmount()
    expect(onDisconnect).not.toHaveBeenCalled()
  })
})
```

- [ ] **Step 3: Run to verify failure**

Run: `cd frontend && npx vitest run src/tests/vncconsole.test.tsx`
Expected: FAIL — `Failed to resolve import "../components/console/VncConsole"`.

- [ ] **Step 4: Write `components/console/VncConsole.tsx`**

```tsx
import RFB from '@novnc/novnc/core/rfb'
import { useEffect, useRef } from 'react'
import { Button } from '../ui/button'

export function VncConsole({ wsUrl, onDisconnect }: { wsUrl: string; onDisconnect?: () => void }) {
  const box = useRef<HTMLDivElement>(null)
  const rfb = useRef<InstanceType<typeof RFB> | null>(null)

  useEffect(() => {
    if (!box.current) return
    let unmounting = false
    const conn = new RFB(box.current, wsUrl)
    conn.addEventListener('disconnect', () => { if (!unmounting) onDisconnect?.() })
    rfb.current = conn
    return () => { unmounting = true; conn.disconnect() }
  }, [wsUrl])

  return (
    <div>
      <div className="mb-2 flex gap-2">
        <Button variant="ghost" className="px-2 py-1 text-[11px]"
          onClick={() => rfb.current?.sendCtrlAltDel()}>
          Ctrl+Alt+Del
        </Button>
        <Button variant="ghost" className="px-2 py-1 text-[11px]"
          onClick={() => box.current?.requestFullscreen()}>
          Fullscreen
        </Button>
      </div>
      <div ref={box} style={{ background: '#0a0e14' }} className="h-[480px] rounded-ctl border border-line-soft" />
    </div>
  )
}
```

- [ ] **Step 5: Run to verify the test passes**

Run: `cd frontend && npx vitest run src/tests/vncconsole.test.tsx`
Expected: PASS (3 tests).

- [ ] **Step 6: Replace the `vmConsoleRoute` placeholder in `vms.tsx`**

Find:

```ts
export const vmConsoleRoute = phaseTab('console', 'Phase 5 (Console)', 'noVNC over the proxied Proxmox vncwebsocket.')
```

Replace with:

```tsx
function VmConsole() {
  const { vmId } = useParams({ strict: false }) as { vmId: string }
  const id = Number(vmId)
  const ticket = useConsoleTicket('vm', id)
  useEffect(() => { ticket.mutate() }, [id])
  if (!ticket.data) return <EmptyState title="Opening console…" note="" />
  // VncConsole has no onDrop today (Task 9 doesn't add one — noVNC's RFB
  // class exposes its own 'disconnect' event for this instead of a generic
  // prop); wire the same re-mint-on-drop behavior via that event:
  return <VncConsoleWithReconnect vmId={id} ticket={ticket.data.ticket} onNeedNewTicket={() => ticket.mutate()} />
}

function VncConsoleWithReconnect({ vmId, ticket, onNeedNewTicket }:
  { vmId: number; ticket: string; onNeedNewTicket: () => void }) {
  return (
    <VncConsole key={ticket} wsUrl={consoleWsUrl('vm', vmId, ticket)}
      onDisconnect={onNeedNewTicket} />
  )
}

export const vmConsoleRoute = createRoute({
  getParentRoute: () => vmDetailRoute, path: 'console', component: VmConsole,
})
```

Add imports: `import { useEffect } from 'react'`, `import { VncConsole } from '../components/console/VncConsole'`, `import { useConsoleTicket, consoleWsUrl } from '../api/consoles'`.

- [ ] **Step 7: Add the Console quick-action to the VMs table row**

In `VmsPage`'s table row (`frontend/src/routes/vms.tsx`), alongside the existing `<LifecycleActions target="vm" .../>` cell:

```tsx
<Button variant="ghost" className="px-2 py-1 text-[11px]"
  onClick={() => navigate({ to: '/vms/$vmId/console' as never, params: { vmId: String(v.id) } as never })}>
  Console
</Button>
```

Add `import { Button } from '../components/ui/button'` to `vms.tsx`.

- [ ] **Step 8: Run the full frontend suite + build**

Run: `cd frontend && npx vitest run && npm run build`
Expected: 59 + 3 = 62 passed; clean build.

- [ ] **Step 9: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/src/components/console/VncConsole.tsx frontend/src/routes/vms.tsx frontend/src/tests/vncconsole.test.tsx
git commit -m "feat(vms): noVNC VncConsole wrapper + wire the VM console tab and quick-action"
```

---

## Task 10: Frontend — node shell on `NodeDetailPage`, gated by entitlement + opt-in

**Files:**
- Modify: `frontend/src/routes/cluster.tsx`
- Test: extend `frontend/src/tests/terminal.test.tsx` or a new `frontend/src/tests/nodeshell.test.tsx`

**Interfaces:**
- Consumes: Task 7's `Terminal`/`useConsoleTicket`, `useEntitlements` (`terminal.node` flag), the host row's `node_shell_enabled` (already returned by `GET /hosts/{id}` per Task 6's `HostCredential`-adjacent read path — confirm `host_detail`'s output includes it; if not, this task's Step 3 adds it).

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/tests/nodeshell.test.tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, waitFor, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

vi.mock('../api/client', () => ({ api: vi.fn() }))
import { api } from '../api/client'

describe('node shell section', () => {
  it('shows a disabled button with a tooltip when node_shell_enabled is false', async () => {
    vi.mocked(api).mockImplementation((path: string) => {
      if (path.includes('/entitlements')) return Promise.resolve({ tier: 'pro', features: { 'terminal.node': true }, grace: null })
      if (path.startsWith('/hosts/')) return Promise.resolve({ id: 7, name: 'pve1', node_shell_enabled: false })
      return Promise.resolve([])
    })
    const { NodeDetailPage } = await import('../routes/cluster')
    const qc = new QueryClient()
    render(
      <QueryClientProvider client={qc}>
        <NodeDetailPage />
      </QueryClientProvider>,
    )
    await waitFor(() => expect(screen.getByText(/node shell/i)).toBeInTheDocument())
    const btn = screen.getByRole('button', { name: /open node shell/i })
    expect(btn).toBeDisabled()
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npx vitest run src/tests/nodeshell.test.tsx`
Expected: FAIL — no "node shell" text in the rendered page.

- [ ] **Step 3: Add the node-shell section to `NodeDetailPage` in `cluster.tsx`**

```tsx
import { useState } from 'react'
import { useEntitlements } from '../api/hooks'
import { useConsoleTicket, consoleWsUrl } from '../api/consoles'
import { Terminal } from '../components/terminal/Terminal'
import { Button } from '../components/ui/button'
```

Inside `NodeDetailPage` (per doc 06 §360's "disabled control + tooltip" pattern for a small inline action, not a full `LockVeil`):

```tsx
function NodeShellSection({ hostId, nodeShellEnabled }: { hostId: number; nodeShellEnabled: boolean }) {
  const ent = useEntitlements()
  const [open, setOpen] = useState(false)
  const ticket = useConsoleTicket('host', hostId)
  const allowed = ent.has('terminal.node') && nodeShellEnabled
  if (open && ticket.data) {
    return (
      <Terminal key={ticket.data.ticket}
        wsUrl={consoleWsUrl('host', hostId, ticket.data.ticket)}
        onDrop={() => ticket.mutate()} />
    )
  }
  return (
    <div className={card}>
      <h2 className="mb-2 text-[13px] uppercase text-text-3">Node shell</h2>
      <Button variant="ghost" disabled={!allowed}
        title={!ent.has('terminal.node') ? 'Pro — Node shells'
             : !nodeShellEnabled ? 'Enable node shell in host settings first' : undefined}
        onClick={() => { setOpen(true); ticket.mutate() }}>
        Open node shell
      </Button>
    </div>
  )
}
```

Render it inside `NodeDetailPage`'s existing layout, passing `hostId={Number(hostId)}` (the route's own `$hostId` param) and `nodeShellEnabled={host.node_shell_enabled}` from the page's existing host-detail query.

- [ ] **Step 4: Confirm `GET /hosts/{id}` returns `node_shell_enabled`**

Check `backend/proxploy/api/hosts.py`'s `host_detail` response dict; if it doesn't already include `node_shell_enabled` (Task 6 only added it to the `PATCH` response), add it there too — one field, same pattern as every other host column already returned.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/tests/nodeshell.test.tsx`
Expected: PASS.

- [ ] **Step 6: Run the full frontend suite + build**

Run: `cd frontend && npx vitest run && npm run build`
Expected: 62 + 1 = 63 passed; clean build.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/routes/cluster.tsx frontend/src/tests/nodeshell.test.tsx backend/proxploy/api/hosts.py
git commit -m "feat(cluster): node shell section on node detail, gated by entitlement + opt-in"
```

---

## Task 11: Logs tab — live-follow CT logs sharing the log-viewer with job transcripts

**Files:**
- Modify: `frontend/src/routes/apps.tsx`
- Test: extend `frontend/src/tests/terminal.test.tsx`

**Interfaces:**
- Consumes: doc 10's Phase 5 scope line "Logs tabs finalized: live-follow CT logs and archived job logs share one log-viewer component" — the existing static-mode `TerminalPanel` (already the shared component per doc 06) plus a live source. CT log output has no existing SSE/stream endpoint from prior phases (`apps.py`'s `GET /apps/{id}/logs` is a point-in-time tail per doc 05, not a stream) — this task wires the **existing** `GET /apps/{id}/logs` on a poll, not a new streaming endpoint, since doc 10's Phase 5 scope names only Console-proper (PtyBridge/ConsoleProxy) as new backend surface; a genuinely live-tailing CT log stream is not in doc 05's endpoint list and would be new backend scope this plan does not invent speculatively.

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/tests/terminal.test.tsx (append)
vi.mock('../api/client', () => ({ api: vi.fn().mockResolvedValue([{ stream: 'stdout', message: 'app started' }]) }))

describe('AppLogs', () => {
  it('renders the logs tail in a static TerminalPanel', async () => {
    const { AppLogs } = await import('../routes/apps')
    const qc = new QueryClient()
    render(<QueryClientProvider client={qc}><AppLogs appId={42} /></QueryClientProvider>)
    await waitFor(() => expect(screen.getByText('app started')).toBeInTheDocument())
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npx vitest run src/tests/terminal.test.tsx -t AppLogs`
Expected: FAIL — `AppLogs` not exported.

- [ ] **Step 3: Replace the `appLogsRoute` placeholder**

```tsx
export function AppLogs({ appId }: { appId: number }) {
  const { data } = useQuery({
    queryKey: ['apps', appId, 'logs'],
    queryFn: () => api<{ stream: string; message: string }[]>(`/apps/${appId}/logs`),
    refetchInterval: 5_000,
  })
  return <TerminalPanel lines={data ?? []} />
}

function AppLogsTab() {
  const { appId } = useParams({ strict: false }) as { appId: string }
  return <AppLogs appId={Number(appId)} />
}

export const appLogsRoute = createRoute({
  getParentRoute: () => appDetailRoute, path: 'logs', component: AppLogsTab,
})
```

Add `import { TerminalPanel } from '../components/TerminalPanel'` if not already imported in `apps.tsx`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/tests/terminal.test.tsx`
Expected: PASS (all).

- [ ] **Step 5: Run the full frontend suite + build**

Run: `cd frontend && npx vitest run && npm run build`
Expected: 63 + 1 = 64 passed; clean build.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/routes/apps.tsx frontend/src/tests/terminal.test.tsx
git commit -m "feat(apps): Logs tab polls the existing tail endpoint into the shared TerminalPanel"
```

---

## Task 12: DoD verification, live-PVE gated test, notes doc, buildlog

**Files:**
- Create: `backend/tests/test_console_pve_integration.py` (marked `pve_integration`, mirrors every prior phase's live-gate pattern)
- Create: `docs/notes/phase-5-console.md`
- Modify: `buildlog.md`

Doc 10 Phase 5 DoD: *"CT terminal, node shell, and VM noVNC session all work through the Proxploy origin only (no direct-to-PVE browser connections), survive reconnect, and write audit rows on open."*

- [ ] **Step 1: Add the gated live-PVE test (this is the real proof for the plan's "spike correction" finding)**

```python
# backend/tests/test_console_pve_integration.py
"""Needs a disposable live PVE (PROXPLOY_TEST_PVE_* env, same gate as every
other pve_integration test in this repo). Proves-or-disproves this plan's
documented open question: does this host's termproxy accept API-token auth
for LXC/node-shell consoles (doc's "Spike correction" note — fixed for VMs in
qemu-server 9.1.7+, unconfirmed for the LXC/node-shell path)."""
import os

import pytest

pytestmark = pytest.mark.pve_integration


def _pve_env():
    host = os.environ.get("PROXPLOY_TEST_PVE_HOST")
    if not host:
        pytest.skip("no disposable live PVE configured")
    return host


def test_app_console_ticket_and_ws_against_real_pve(tmp_path):
    host_addr = _pve_env()
    # ... exercises POST /apps/{id}/console/tickets and WS /apps/{id}/console/ws
    # against the real host from PROXPLOY_TEST_PVE_* env, asserting either a
    # working PTY round-trip OR the PtyBridgeError message this plan's Task 3
    # makes explicit for the known token/termproxy PVE limitation — either
    # outcome is a pass for THIS test; a bare hang/timeout is the only failure.
    pytest.skip("fill in against the disposable PVE fixture once one is available "
                "(doc 11 pattern) — no live PVE on this box (standing limitation, "
                "every phase)")
```

- [ ] **Step 2: Write and run the DoD verification script (fakes-based, matching every prior phase's no-live-PVE approach)**

```python
# backend/dod_verify_phase5.py — run once from backend/ with the project venv, not committed
"""Phase 5 DoD verification, doc 10. Uses tests.support.make_app + the fakes
from Tasks 1-4 — no live PVE, no real websocket to Proxmox, no browser on this
box, matching every prior phase's stated limitation."""
import asyncio
from pathlib import Path

import websockets

from tests.fakes.pve import FakePVE
from tests.fakes.pve_ws import FakeXtermUpstream
from tests.support import make_app, seed_host_row


def main():
    tmp = Path("/tmp/phase5_dod")
    tmp.mkdir(exist_ok=True)
    fake = FakePVE()
    fake.termproxy_response = {"user": "proxploy@pve!console", "ticket": "PVEVNC:abc",
                               "port": "5900", "upid": "UPID:..."}
    app = make_app(tmp, fake=fake)
    with app.state.sessionmaker() as db:
        from proxploy.models import App, HostCredential
        import json as jsonlib
        host = seed_host_row(db)
        blob, ver = app.state.secretstore.encrypt(
            jsonlib.dumps({"token_id": "proxploy@pve!console", "token_secret": "s3cret"}).encode())
        db.add(HostCredential(host_id=host.id, kind="api_token", encrypted_blob=blob, key_version=ver))
        a = App(host_id=host.id, ctid=150, name="immich", status="running", slug="immich-1")
        db.add(a)
        db.commit()
        app_id, host_id = a.id, host.id

    async def upstream():
        fake_ws = FakeXtermUpstream(expected_auth_line="proxploy@pve!console:PVEVNC:abc\n")
        url = await fake_ws.start()
        return fake_ws, url
    fake_ws, url = asyncio.run(upstream())

    import proxploy.services.ptybridge as ptybridge_mod
    orig = ptybridge_mod.connect_upstream_pty

    async def patched(**kwargs):
        kwargs["ws_connect"] = lambda: websockets.connect(url, subprotocols=["binary"])
        return await orig(**kwargs)
    ptybridge_mod.connect_upstream_pty = patched

    from tests.conftest import login_as_owner
    from fastapi.testclient import TestClient
    client = TestClient(app)
    login_as_owner(client)

    r = client.post(f"/api/v1/apps/{app_id}/console/tickets")
    print("ticket response:", r.status_code, r.json())
    ticket = r.json()["ticket"]

    with client.websocket_connect(f"/api/v1/apps/{app_id}/console/ws?ticket={ticket}") as ws:
        print("first frame:", ws.receive_text())
        ws.send_text("ls\n")
        print("echoed:", ws.receive_text())

    with app.state.sessionmaker() as db:
        from proxploy.models import AuditEvent
        row = db.query(AuditEvent).filter_by(action="console.open").one()
        print("audit row:", row.target_type, row.target_id)
    print("PROVED: ticket mint -> WS redeem -> PTY bridge round trip -> audit row, single origin throughout")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run it and paste real output into the notes doc**

Run: `cd backend && python dod_verify_phase5.py`

- [ ] **Step 4: Run the full backend + frontend suites**

Run: `cd backend && pytest tests/ -q -m "not pve_integration and not e2e"` — expect Phase 4's 308 passed, 2 skipped, 2 deselected plus this plan's new tests (Task 1: 5, Task 2: 5, Task 3: 3, Task 4: 2, Task 5: 3, Task 6: 2 = 20), zero failures, ~328 passed.
Run: `cd backend && python scripts/check_executor_isolation.py` — expect `executor isolation: OK` (unaffected by this phase).
Run: `cd frontend && npx vitest run` — expect Phase 4's 52 passed plus this plan's new tests (Task 7: 6, Task 8: 1, Task 9: 3, Task 10: 1, Task 11: 1 = 12), ~64 passed.
Run: `cd frontend && npm run build` — expect a clean build.

- [ ] **Step 5: Write `docs/notes/phase-5-console.md`**

Follow `docs/notes/phase-4-store.md`'s exact structure: "What shipped, per subsystem", a DoD verification map table (clause | proving artifact | verdict) covering the one doc 10 DoD clause above, real command output, and a "What was NOT verified" section — call out explicitly: no real Proxmox host (the `pve_integration`-marked test in Step 1 is skipped without one, same as every prior phase's live-PVE gate), no browser UI check, and this plan's own "spike correction" finding (API-token-vs-termproxy PVE version dependency) as an open item for whenever a live PVE becomes available.

- [ ] **Step 6: Update `buildlog.md`**

Append a `### <timestamp> — Phase 5 — execute-plan completed` entry matching Phases 2/3/4's format exactly (plan path, verification counts, what was built, deviations — including the webgl-addon skip from Task 7 and the token/termproxy open question from this plan's header).

- [ ] **Step 7: Commit**

```bash
git add docs/notes/phase-5-console.md buildlog.md backend/tests/test_console_pve_integration.py
git commit -m "docs(phase-5): DoD verification notes + buildlog entry"
```
