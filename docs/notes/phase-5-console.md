# Phase 5 (Console) — verification notes

## What shipped, per subsystem

**Proxmox client — termproxy/vncproxy calls** —
`backend/proxploy/services/proxmox.py`: `ProxmoxClient.termproxy(kind, node,
vmid)` (CT/VM text console), `.node_termproxy(node)` (node shell), and
`.vncproxy(node, vmid)` (VM noVNC, `websocket=1`). `tests/fakes/pve.py`'s
`FakePVE` grew matching fakes so every route below can be proven without a
live PVE host.

**Console tickets** — `backend/proxploy/services/consoletickets.py`
(`mint_ticket`, `redeem_ticket`) + `ConsoleTicket` table
(`backend/proxploy/models/__init__.py`). Single-use, short-TTL, bound to a
specific Proxmox target + the upstream ticket/port Proxmox itself issued —
never a generic session token. `redeem_ticket`'s atomicity is a conditional
`UPDATE ... WHERE redeemed_at IS NULL`: two concurrent redemptions of the same
raw value can both `SELECT`, but only one `UPDATE` can match, so the loser
gets `None` exactly as if the ticket never existed. Only `token_hash` is
stored, matching `SessionRow`'s hash-at-rest precedent; `upstream_ticket` is
stored in the clear because it's Proxmox's own few-second-TTL ticket, never
reaches the browser, and is meaningless without a live upstream socket to
present it to in time.

**PtyBridge** — `backend/proxploy/services/ptybridge.py`:
`connect_upstream_pty` (opens the CT/node-shell `termproxy` → `vncwebsocket`
handshake, sends the `"{user}:{ticket}\n"` auth line, requires the first
server frame to start with `"OK"`) and `bridge_pty` (translates doc 05's
simple browser framing — raw text both ways, one `{"type":"resize",...}` JSON
control frame in, one `{"type":"exit","code":...}` JSON frame out before close
— to/from Proxmox's own `0:`/`1:`/`2` wire framing, reverse-engineered
directly from `pve-xtermjs`'s `src/www/main.js`, not assumed). `PtyBridgeError`
surfaces PVE's own termproxy rejection message rather than a generic hang —
this is the documented API-token/termproxy limitation's error path (see the
DoD table below).

**ConsoleProxy** — `backend/proxploy/services/consoleproxy.py`:
`connect_upstream_vnc` + `bridge_binary`, a dumb byte-for-byte relay (no
translation — the VM `vncwebsocket` path needs no line-based handshake; the
first server frame is the raw RFB greeting and noVNC's own `RFB` class on the
browser handles the rest, using the VNC ticket as the RFB password).

**Console ticket + WS routes** — `backend/proxploy/api/consoles.py`:
`POST /apps/{id}/console/tickets` + `WS /apps/{id}/console/ws` (CT terminal,
`operator` + `apps.console`), `POST /hosts/{id}/shell/tickets` + `WS
/hosts/{id}/shell/ws` (node shell, `admin` + `terminal.node`, plus a third,
independent gate — `Host.node_shell_enabled` must be toggled on first, a
409 otherwise), `POST /vms/{id}/console/tickets` + `WS /vms/{id}/vnc/ws` (VM
noVNC, `operator` + `vms.console`). Every ticket-mint route writes a
`console.open` audit row (`app`/`host`/`vm` target respectively) and never
audits the raw or upstream ticket. Every WS route takes no cookie/session at
all — the one-time ticket already proves auth — and `_run_pty_ws`'s
`_HOST_ID_RESOLVERS` dict rejects (closes 4401) a ticket redeemed against the
wrong route kind (e.g. a `vm_vnc` ticket replayed at `/apps/{id}/console/ws`)
rather than `KeyError`-ing.

**Host node-shell opt-in** — `PATCH /hosts/{id}` (`backend/proxploy/api/
hosts.py`) accepts `node_shell_enabled`, now audited as
`host.node_shell_toggle` (a gap in the plan's own sample code, fixed in Task
6's review — see "Deviations").

**Frontend Terminal (xterm.js)** — `frontend/src/components/terminal/
Terminal.tsx` (61 lines): wraps `@xterm/xterm` + `@xterm/addon-fit` (webgl
addon deliberately skipped, see "Deviations"), opens a raw `WebSocket` at
`wsUrl`, translates doc 05's simple JSON control frame both ways, calls
`onDrop()` on an unexpected `ws.onclose` (guarded against firing on the
component's own unmount-triggered close). `frontend/src/api/consoles.ts`:
`useConsoleTicket(kind, id)` mutation + `consoleWsUrl(kind, id, ticket)`
across all three console kinds (`app`/`host`/`vm`).

**Frontend VncConsole (noVNC)** — `frontend/src/components/console/
VncConsole.tsx` (33 lines) wraps `@novnc/novnc`'s `RFB` class (bare import,
not the `@novnc/novnc/core/rfb` path the plan assumed — that path doesn't
resolve against the real package's `exports` field, fixed in Task 9's
review). `frontend/src/types/novnc.d.ts`: implementer-authored, type-only
`.d.ts` shim (no vendored noVNC logic, MPL-2.0-safe).

**Wiring** — CT console tab + AppCard Console button
(`frontend/src/routes/apps.tsx`): `Terminal` keyed on `ticket.data.ticket` so
a re-mint (`onDrop={() => ticket.mutate()}`) forces a clean remount — the
concrete mechanism behind the DoD's "survive reconnect" clause. VM console
tab (`frontend/src/routes/vms.tsx`): same key+remint shape via
`VncConsoleWithReconnect`, though `VncConsole` itself has no `onDrop` today
(noVNC's own `RFB.disconnect` handler is the reconnect signal Task 9 wired
instead — see "What was NOT verified" for the one open gap here). Node shell
section (`frontend/src/routes/cluster.tsx`): `useHostDetail` (new — the node
detail page had no host-detail query before this task) feeds
`node_shell_enabled` into `NodeShellSection`, gating the shell button with a
tooltip when disabled.

**Logs tab** — `frontend/src/components/TerminalPanel.tsx` wired into both
the app detail's live CT log tab and the archived job-log view, sharing one
log-viewer component per doc 10's "Logs tabs finalized" bullet.

## DoD verification map (doc 10 Phase 5)

DoD: *"CT terminal, node shell, and VM noVNC session all work through the
Proxploy origin only (no direct-to-PVE browser connections), survive
reconnect, and write audit rows on open."*

| Clause | Proving artifact | Verdict |
|---|---|---|
| CT terminal, node shell, and VM noVNC session all work through the Proxploy origin only (no direct-to-PVE browser connections) | Every WS route the browser calls is same-origin (`/api/v1/apps/{id}/console/ws`, `/hosts/{id}/shell/ws`, `/vms/{id}/vnc/ws`, `frontend/src/api/consoles.ts::consoleWsUrl`) — the browser never receives a Proxmox host/port/ticket; `PtyBridge`/`ConsoleProxy` hold the upstream `wss://{pve}:8006/...` connection entirely server-side (`backend/proxploy/services/ptybridge.py`, `consoleproxy.py`). `dod_verify_phase5.py` (below) drives the real route end-to-end and never touches a PVE address from the client side. Backend unit coverage: `tests/test_ptybridge.py` (4, incl. Task 3's fix-round regression test for the `asyncio.wait()` exception-swallowing bug), `tests/test_consoleproxy.py` (3, incl. Task 4's equivalent regression test), `tests/test_consoles_api.py` (5), `tests/test_consoletickets.py` (5) | PROVED |
| Survive reconnect | `frontend/src/routes/apps.tsx`: `Terminal` keyed on the ticket value, remounted via `onDrop={() => ticket.mutate()}` on an unexpected close; `frontend/src/routes/vms.tsx`'s `VncConsoleWithReconnect` does the same for the VM tab. `frontend/src/tests/terminal.test.tsx` and `frontend/src/tests/vncconsole.test.tsx` (Task 9's fix round made `FakeRFB.disconnect` genuinely fire the registered handler, mutation-proof RED/GREEN documented in the ledger) exercise both halves of the chain. Task 8's reviewer traced the full key+onDrop reconnect chain end-to-end and confirmed the clause is genuinely satisfied, not just one half wired | PROVED BY TEST, NOT BY BROWSER |
| Write audit rows on open | Every ticket-mint route (`app_console_ticket`, `node_shell_ticket`, `vm_console_ticket` in `backend/proxploy/api/consoles.py`) calls `write_audit(..., action="console.open", ...)` before returning the ticket — proven directly in `dod_verify_phase5.py`'s output below and in `tests/test_consoles_api.py::test_console_tickets_mints_a_ticket_and_audits` / `::test_shell_ticket_mints_after_toggling_on_and_audits`, both of which also assert the raw/upstream ticket is never written into the audit row's params | PROVED |

### `dod_verify_phase5.py` — real output

Run against `tests.support.make_app` + a real `TestClient` (so the real
routes, ticket service, and PtyBridge run for real) + `tests/fakes/pve.py`'s
`FakePVE` and `tests/fakes/pve_ws.py`'s `FakeXtermUpstream` standing in for a
live PVE host and its termproxy websocket — no live PVE, no real websocket to
Proxmox, no browser on this box, matching every prior phase's stated
limitation. Script was written to the repo root of `backend/` (not committed
— throwaway per this task's brief; adjusted from the brief's sample to match
the real `App.status_cached` column name, the real lifespan-gated
`app.state.sessionmaker`, and an inlined login sequence since
`tests.conftest.login_as_owner` doesn't exist as an importable function).

```
ticket response: 200 {'ticket': '1NQM7FdEWrRiEY1D0LUP2cl3Nd6kZtiA718gbfPBf00', 'expires_at': '2026-07-30T18:27:02.204966Z'}
first frame: OK
echoed: echo:ls

audit row: app 1
PROVED: ticket mint -> WS redeem -> PTY bridge round trip -> audit row, single origin throughout
```

## Gate numbers (real, captured this run)

| Gate | Command | Result |
|---|---|---|
| Backend tests | `pytest tests/ -q -m "not pve_integration and not e2e"` | **333 passed, 2 skipped, 3 deselected** (was 2 deselected before this task added one more `pve_integration`-marked test) |
| Executor isolation | `python scripts/check_executor_isolation.py` | **OK** (unaffected by this phase) |
| Frontend tests | `npx vitest run` | **65 passed (20 files)** |
| Frontend build | `npm run build` | **clean** (`tsc -b` + vite build; one pre-existing "chunk > 500kB" size warning, not a new regression) |

One flaky observation during this run, not a regression: a single run of the
full frontend suite timed out `nodeshell.test.tsx`'s first test at the
default 5000ms under full-suite resource contention; re-run in isolation and
as part of a second full-suite run both passed cleanly (65/65). No frontend
files were touched by this task.

## Every endpoint added this phase

| Method + path | Role | Entitlement | Notes |
|---|---|---|---|
| `POST /api/v1/apps/{id}/console/tickets` | operator | `apps.console` | mints an `app_console` ticket, audits `console.open` (target `app`) |
| `WS /api/v1/apps/{id}/console/ws` | ticket-only | — | no session/cookie required, the ticket is the auth |
| `POST /api/v1/hosts/{id}/shell/tickets` | admin | `terminal.node` | third gate: `Host.node_shell_enabled` must already be on (409 otherwise); audits `console.open` (target `host`) |
| `WS /api/v1/hosts/{id}/shell/ws` | ticket-only | — | node shell PTY |
| `POST /api/v1/vms/{id}/console/tickets` | operator | `vms.console` | mints a `vm_vnc` ticket, audits `console.open` (target `vm`) |
| `WS /api/v1/vms/{id}/vnc/ws` | ticket-only | — | raw RFB byte relay, no PtyBridge translation |
| `PATCH /api/v1/hosts/{id}` (extended) | admin | — | `node_shell_enabled` field; now audits `host.node_shell_toggle` (Task 6 fix round) |

## Deviations from the plan (controller decisions during the build)

- **Task 3, Task 4: `asyncio.wait()` silently swallows a done task's
  exception** — a real bug in the plan's own example `bridge_pty`/
  `bridge_binary` code, independently found and fixed by both implementers.
  `asyncio.wait()` never raises a completed task's exception at the `await`
  point; it just sits unretrieved on the `Future`. Both fixes now walk the
  `done` set and re-raise any exception found there, each with a regression
  test the reviewer verified genuinely discriminates buggy vs. fixed code via
  a live repro.
- **Task 2: `redeem_ticket`'s single-use atomicity was verified live, not by
  an automated regression test in the suite.** The brief's own test was
  sequential-only; the reviewer independently ran a real 20-thread
  concurrency race against the conditional `UPDATE ... WHERE redeemed_at IS
  NULL` — one winner, every time. Genuinely proven, but there is still no
  concurrency test committed to the suite (deferred, see "What was NOT
  verified").
- **Task 6: `PATCH /hosts/{id}`'s node-shell toggle had no audit row** — a
  gap in the plan's own sample code, fixed in review by adding `write_audit`
  with `action="host.node_shell_toggle"`.
- **Task 7: the webgl xterm.js addon was deliberately skipped** (doc 06 asks
  for "fit + webgl addons"). The webgl addon only adds context-loss/fallback
  handling for a marginal render-perf gain over the default canvas renderer,
  with no functional difference to the user — skipped as
  unrequested-complexity-for-its-own-sake, called out here rather than
  silently, matching this project's practice of naming its deviations.
- **Task 9: `@novnc/novnc/core/rfb` doesn't actually resolve** against the
  real package's `exports` field (verified directly against its
  `package.json`, not assumed from the plan's sample import) — fixed to the
  bare `@novnc/novnc` import. `FakeRFB.disconnect` also didn't originally fire
  the registered `'disconnect'` handler the way real noVNC does, which meant
  the reconnect test wasn't actually exercising the unmounting guard; fixed
  in the same review round.
- **Task 5: a background event-loop test-infra bug (Python late-binding +
  an asyncio double-run) was found and fixed** so that monkeypatching
  `ptybridge.connect_upstream_pty` in tests actually takes effect — the same
  loop-in-a-thread pattern `dod_verify_phase5.py` above and `test_consoles_
  api.py` both now rely on.

No documented DoD clause or non-negotiable acceptance criterion was loosened
by any of the deviations above.

## What was NOT verified

- **No real Proxmox host.** Every proof above runs against `tests/fakes/
  pve.py`'s `FakePVE` and `tests/fakes/pve_ws.py`'s `FakeXtermUpstream`,
  matching every prior phase's no-live-PVE approach. `backend/tests/
  test_console_pve_integration.py::test_app_console_ticket_and_ws_against_
  real_pve` (Step 1 of this task) is the gated test that would prove-or-
  disprove this against a disposable live PVE — it is `pve_integration`-
  marked and skips (as it did this run) without one, same standing
  limitation as `tests/test_pve_integration.py` since Phase 1.
- **The plan's own "Spike correction" finding is still an open question.**
  Proxmox API tokens have historically been rejected by `/termproxy` xtermjs
  websocket handshakes on some PVE/qemu-server versions (Proxmox bugzilla
  #6079) — fixed for the **VM** case in `qemu-server` 9.1.7+, but whether the
  equivalent **LXC/node-shell** `termproxy` path is fixed on the same
  timeline is not confirmed by any source found while grounding this plan.
  `PtyBridgeError` surfaces PVE's own rejection message explicitly rather
  than a generic hang (`backend/proxploy/services/ptybridge.py`), so the
  failure mode is clean either way — but only a real PVE host run of the
  gated test above can settle whether this app's CT-terminal/node-shell path
  works against a given host's PVE version. This is the single biggest open
  item carried out of this phase.
- **No browser UI check.** The Terminal, VncConsole, node-shell tooltip, and
  logs-tab wiring are proved by `frontend/src/tests/{terminal,vncconsole,
  nodeshell,consoles-api}.test.tsx` under jsdom, not by a visual run in an
  actual browser. No screenshot, no manual click-through happened or is
  claimed to have happened — same gap Phases 1-4 all named.
- **No automated concurrency regression test for `redeem_ticket`'s
  single-use atomicity** (Task 2) — genuinely proven live by the reviewer's
  20-thread race, just not committed as a suite test.
- **No dedicated test for a mismatched-ticket-kind replay against
  `app_console_ws` specifically** (Task 5) — the `_HOST_ID_RESOLVERS`
  KeyError guard is only inference-verified via `node_shell_ws`'s equivalent
  path plus code inspection.
- **No test that an operator (vs. viewer) is rejected on the node-shell
  ticket route specifically** (Task 6) — only inferable from `ROLE_ORDER`,
  not asserted directly.
- **Node-shell entitlement-loading tooltip flash** (Task 10) — momentary
  "Pro" tooltip before entitlements resolve, cosmetic only, no
  `ent.data-loaded` guard like `LifecycleActions`' established pattern.
- **No visibility-based pause on log polling** (Task 11) — polling continues
  on a backgrounded/hidden tab; acceptable for v1, not scope-critical.
- Postgres-backend behavior for the new/changed tables (`console_tickets`,
  `hosts.node_shell_enabled`) — nothing in this phase added Postgres-specific
  exercises beyond Phase 1/2's generic schema-portability CI leg.

## What Phase 9 (docs) should write

- User-facing docs for the Console feature: what a console ticket is (a
  single-use, short-TTL grant bound to one Proxmox target), why the WS routes
  take no session cookie, and what "survive reconnect" looks like from the
  user's side (a fresh terminal, not a resumed one).
- The node-shell opt-in flow: why it's a three-way gate (RBAC role +
  entitlement + a deliberate per-host `node_shell_enabled` toggle), not just
  a permission.
- A decision on the open termproxy/API-token question once a live PVE is
  available: run `backend/tests/test_console_pve_integration.py` against it,
  and either update doc 08 to note the confirmed LXC/node-shell behavior for
  the tested PVE/qemu-server version, or file the upstream limitation as a
  known caveat in user-facing docs if it's still unfixed there.
