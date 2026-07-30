# Proxploy Build Log

Autonomous build loop: cycles `/superpowers:writing-plans` (Fable 5) then
`/superpowers:executing-plans` (Sonnet 5) through each phase in
`docs/10-build-sequence.md`, fully unattended, no phase-gate pauses.
Driven by `bin/build-cycle.sh` on the `proxploy-build.timer` systemd user timer.

<!-- STATE: phase=4 step=plan -->

### 2026-07-29T01:22:23+05:30 — Phase 1 — write-plan FAILED (exit 1)

See /home/aasim/workspace/aspyrelabs/proxploy/proxploy-app/logs/build-2026-07-29.log for details. Will retry next run.

### 2026-07-29T01:30:04+05:30 — Phase 1 — write-plan FAILED (exit 1)

See /home/aasim/workspace/aspyrelabs/proxploy/proxploy-app/logs/build-2026-07-29.log for details. Will retry next run.

### 2026-07-29T02:00:03+05:30 — Phase 1 — write-plan FAILED (exit 1)

See /home/aasim/workspace/aspyrelabs/proxploy/proxploy-app/logs/build-2026-07-29.log for details. Will retry next run.

### 2026-07-29T02:30:08+05:30 — Phase 1 — write-plan FAILED (exit 1)

See /home/aasim/workspace/aspyrelabs/proxploy/proxploy-app/logs/build-2026-07-29.log for details. Will retry next run.

### 2026-07-29T03:34:09+05:30 — Phase 1 — write-plan completed (fable-5)

Plan: /home/aasim/workspace/aspyrelabs/proxploy/proxploy-app/docs/superpowers/plans/2026-07-29-phase-1-foundation.md

### 2026-07-29T04:29:46+05:30 — Phase 1 — execute-plan FAILED (exit 1)

See /home/aasim/workspace/aspyrelabs/proxploy/proxploy-app/logs/build-2026-07-29.log for details. Will retry next run (plan step is not re-run).

### 2026-07-29T04:29:49+05:30 — Phase 1 — execute-plan FAILED (exit 1)

See /home/aasim/workspace/aspyrelabs/proxploy/proxploy-app/logs/build-2026-07-29.log for details. Will retry next run (plan step is not re-run).

### 2026-07-29T04:30:03+05:30 — Phase 1 — execute-plan FAILED (exit 1)

See /home/aasim/workspace/aspyrelabs/proxploy/proxploy-app/logs/build-2026-07-29.log for details. Will retry next run (plan step is not re-run).

### 2026-07-29T05:00:05+05:30 — Phase 1 — execute-plan FAILED (exit 1)

See /home/aasim/workspace/aspyrelabs/proxploy/proxploy-app/logs/build-2026-07-29.log for details. Will retry next run (plan step is not re-run).

### 2026-07-29T05:30:08+05:30 — Phase 1 — execute-plan FAILED (exit 1)

See /home/aasim/workspace/aspyrelabs/proxploy/proxploy-app/logs/build-2026-07-29.log for details. Will retry next run (plan step is not re-run).

### 2026-07-29T06:00:05+05:30 — Phase 1 — execute-plan FAILED (exit 1)

See /home/aasim/workspace/aspyrelabs/proxploy/proxploy-app/logs/build-2026-07-29.log for details. Will retry next run (plan step is not re-run).

### 2026-07-29T06:30:08+05:30 — Phase 1 — execute-plan FAILED (exit 1)

See /home/aasim/workspace/aspyrelabs/proxploy/proxploy-app/logs/build-2026-07-29.log for details. Will retry next run (plan step is not re-run).

### 2026-07-29T07:00:05+05:30 — Phase 1 — execute-plan FAILED (exit 1)

See /home/aasim/workspace/aspyrelabs/proxploy/proxploy-app/logs/build-2026-07-29.log for details. Will retry next run (plan step is not re-run).

### 2026-07-29T07:30:04+05:30 — Phase 1 — execute-plan FAILED (exit 1)

See /home/aasim/workspace/aspyrelabs/proxploy/proxploy-app/logs/build-2026-07-29.log for details. Will retry next run (plan step is not re-run).

### 2026-07-29T08:20:58+05:30 — Phase 1 — execute-plan completed (sonnet-5)

All 16 Phase 1 tasks are now complete and committed, one commit per task, directly to `main` across all four repos (matching this project's established no-branch convention, confirmed by every prior commit in the history) — so I skipped the `finishing-a-development-branch` skill, since there's no feature branch to merge here; work streamed straight to `main` as it was built.

## What was built

**proxploy-app (backend, FastAPI + SQLAlchemy + Alembic):**
- Full doc-04 schema (24 tables) via Alembic migration 0001, SQLite-WAL by default, Postgres-portable
- SecretStore (Fernet/MultiFernet, 0400-root-only key file, regeneration guard)
- Append-only, secret-redacting audit writer + admin audit-read endpoint
- Local auth: argon2, DB sessions, CSRF double-submit, per-IP rate limiting, forced first-run owner bootstrap, RBAC stub
- Entitlement registry (all 81 flags ON), Ed25519 verification client with grace window, `/entitlements`
- Dormant license activate/refresh/remove flow against proxploy-api, with background refresh and an e2e roundtrip test
- Proxmox client layer (`ProxmoxClient`, single PVE-8/9 branch point) + fake PVE fixture infra + a gated live-PVE integration test
- Host onboarding — probe/create/list/detail/test, encrypted credential storage, consented SSH key enrolment — the audited route template every later route copies
- Settings service (`.enc` hygiene) + `/meta/version`, `/meta/onboarding`

**proxploy-app (frontend, Vite + React 19 + Tailwind v4):**
- Verbatim design tokens, API client with CSRF, login form
- App shell: fixed 8-page nav, topbar, theme toggle, entitlements hook, `LockVeil`, honest placeholder pages
- Onboarding wizard (admin → host → SSH consent → done) + Settings page (plan/hosts/add-host)

**CI + isolation:** executor-isolation lint (asyncssh/SSH-key-accessor confined to `executor/`, which doesn't exist yet), license audits in both repos, a Postgres CI leg, a secrets-gated disposable-PVE matrix, and the backend now serves the built SPA at `/`.

**proxploy-api, proxploy-web, proxploy-docs:** licensing resolver (from earlier in this build) plus its own CI; web/docs remain intentional empty scaffolds per the plan.

## Verification
- `backend`: 39 passed, 2 skipped (env-gated live-PVE + one other) — `pytest -q`
- `backend`: `check_executor_isolation.py` → OK
- `frontend`: 5 passed (3 files) — `npm test`; `npm run build` clean; SPA-serving confirmed via `TestClient`
- `proxploy-api`: 4 passed — `pytest -q`
- All three DoD quality gates hold; the Phase-1 DoD verification map's proof artifacts all exist and pass

Noted deviations (documented in the relevant commit messages): a few TS `as never` casts for routes/circular imports that resolve themselves as later tasks register those routes; `psycopg` (LGPL) split into its own extras group so it doesn't taint the license audit; license-audit commands needed `--ignore-packages`/`OFL-1.1` additions to correctly exclude our own unpublished packages and allow the SIL font license. No live PVE or Docker was available on this box, so those legs stayed env/secret-gated as designed, and the dev-server manual walkthrough was skipped (sandbox blocks background servers) in favor of the equivalent `TestClient`-based checks the plan itself sanctions for the no-PVE case.

### 2026-07-29T08:58:52+05:30 — Phase 2 — write-plan completed (fable-5)

Plan: /home/aasim/workspace/aspyrelabs/proxploy/proxploy-app/docs/superpowers/plans/2026-07-29-phase-2-observe.md

### 2026-07-29T10:24:02+05:30 — Phase 2 — execute-plan FAILED (exit 1)

See /home/aasim/workspace/aspyrelabs/proxploy/proxploy-app/logs/build-2026-07-29.log for details. Will retry next run (plan step is not re-run).

### 2026-07-29T10:24:06+05:30 — Phase 2 — execute-plan FAILED (exit 1)

See /home/aasim/workspace/aspyrelabs/proxploy/proxploy-app/logs/build-2026-07-29.log for details. Will retry next run (plan step is not re-run).

### 2026-07-29T10:30:08+05:30 — Phase 2 — execute-plan FAILED (exit 1)

See /home/aasim/workspace/aspyrelabs/proxploy/proxploy-app/logs/build-2026-07-29.log for details. Will retry next run (plan step is not re-run).

### 2026-07-29T11:00:05+05:30 — Phase 2 — execute-plan FAILED (exit 1)

See /home/aasim/workspace/aspyrelabs/proxploy/proxploy-app/logs/build-2026-07-29.log for details. Will retry next run (plan step is not re-run).

### 2026-07-29T11:30:04+05:30 — Phase 2 — execute-plan FAILED (exit 1)

See /home/aasim/workspace/aspyrelabs/proxploy/proxploy-app/logs/build-2026-07-29.log for details. Will retry next run (plan step is not re-run).

### 2026-07-29T11:45:00+05:30 — Phase 2 — execute-plan completed (Friday)

Phase 2 was built by Claude Code during a single 84-minute run (9:00–10:24 AM)
that hit the session limit mid-verification. All code was written; only Task 14
(benchmark + notes) remained. Friday completed the benchmark and wrote the
verification notes.

**Verification:**
- Backend: 63 passed, 1 skipped
- Frontend: 13 passed, build clean
- Executor isolation: OK
- Bench: 8×100 fleet writes at p50=154.7ms (well under 30s budget)

**What was built (by Claude Code):**
- Poller subsystem: per-host 30s asyncio poll loops, bulk cluster/resources + per-node rrddata
- MetricsStore: batched writes, 5m/1h rollups, retention pruning, range query API
- Read-only caches: apps (with discovered-CT heuristics), vms, storage/network snapshots
- SSE event stream for live cache invalidation
- 6 Phase 2 REST endpoints: cluster/summary, cluster/nodes, apps, apps/discovered, vms, metrics/query
- Frontend: Cluster page (rings + node cards), node detail, Apps grid + discovered panel, VMs table + detail overview, uPlot charts via Sparkline component, LiveProvider for SSE-to-QueryCache invalidation

### 2026-07-29T15:00:00+05:30 — Phase 3 — execute-plan completed

Plan: `docs/superpowers/plans/2026-07-29-phase-3-act.md`. All 14 tasks
implemented and committed directly to `main`, tasks 1-8 backend/1-10
individually reviewed, 11-13 batched with the review folded into the final
whole-branch pass. Full details, DoD proof and deviations in
`docs/notes/phase-3-act.md`.

**What was built:**
- JobBackend: in-process asyncio job runner (`Semaphore(4)`, `jobs` +
  `job_events` persistence, per-job SSE log stream, orphan sweep on boot)
- Lifecycle: `ProxmoxClient.guest_action`/`task_status`/`task_log`,
  `app.*`/`vm.*` job handlers, self-management guardrail (typed confirm),
  `POST /apps/{id}/{action}` and `POST /vms/{id}/{action}`
- Notifications: Apprise-backed `Notifier`, `notification_channels` CRUD +
  test-send, job-terminal-state routing (`job.succeeded/failed/canceled/interrupted`)
- Activity feed: `GET /cluster/activity` (jobs + audit, deduped, newest-first)
- Frontend: job hooks + SSE `job`-delta cache binding, TerminalPanel/JobLog/
  ActivityDrawer/topbar bell, lifecycle action buttons with optimistic UI +
  self-target confirm dialog, dashboard activity feed, Settings notification
  channels card

**Verification:**
- Backend: 190 passed, 1 skipped, 2 deselected — `pytest -q -m "not pve_integration and not e2e"`
- Backend: executor isolation OK; license audit OK
- Frontend: 33 passed (11 files); build clean; license audit OK
- `docs/notes/phase-3-act.md`'s `dod_verify.py` run: all 4 doc-10 DoD clauses
  proved against `tests.support.make_app` + `FakePVE` (no live PVE, no
  Docker, no browser on this box — clause 1's UI half is covered by
  `frontend/src/tests/lifecycle.test.tsx` under jsdom, not a visual run)

**Deviations** (full list + rationale in the notes doc): lifecycle verbs are
a documented superset of doc 05's paths; jobs/activity endpoints carry
additional entitlement gates doc 05 left blank; doc 05 §Streaming 4 was
amended to add `target_type` to the `job` SSE event; job-row writes are
inline on the event loop by design; `hosts/{id}/tasks` and `hosts/{id}/sync`
were deliberately not built (no Phase 3 dependency).

### 2026-07-30T16:28:38+05:30 — Phase 4 — execute-plan completed

Plan: `docs/superpowers/plans/2026-07-30-phase-4-store.md`. All 14 feature
tasks implemented and committed directly to `main`, each individually
reviewed (fix rounds where the reviewer found real gaps: Task 1's TOFU
pinning bug, Task 4's missing entitlement/audit wiring, Task 14's theme-token
color fix), Task 15 closing out with DoD verification, this notes doc, and
this buildlog entry. Full details, DoD proof, and deviations in
`docs/notes/phase-4-store.md`.

**What was built:**
- `proxploy/executor/`: asyncssh runner with closed stdin, host-key TOFU
  pinning (`hosts.ssh_host_key_fingerprint`), `run_for_host`
- Install-feasibility classifier (`services/classifier.py`): mechanical
  detection of unconditional interactive prompts and multi-CT patterns
- CatalogSource ingest (`services/catalog.py` + `catalog_categories.py`):
  GitHub-raw fetch of `ct/*.sh`/`install/*.sh` pairs, ETag-cached, classified,
  upserted into `catalog_entries`; `Settings.catalog_slugs` (24-app v1 seed)
- Catalog API (`GET /catalog`, `GET /catalog/{slug}`, `POST /catalog/refresh`)
- Install job handler (`app.install`): pin script into `app_scripts`, SSH
  install with streamed log, create `App` row
- `POST /catalog/{slug}/install` with root-consent + enrolled-ssh_key gates
- `POST /apps/adopt` bulk adoption (single-batch commit + audit)
- Script view/edit/diff-vs-upstream/version-history routes on `apps.py`
- Frontend: catalog hooks, `StoreCard`, `/store` route (tile grid, category
  chips, real installable/unsupported counts), install dialog (root-consent
  gate, live job log), bulk-adopt dialog wired into `/apps`, app detail
  Config tab (script view/edit + diff)

**Verification:**
- Backend: 290 passed, 2 skipped, 2 deselected — `pytest tests/ -q -m "not pve_integration and not e2e"`
- Backend: executor isolation OK (`scripts/check_executor_isolation.py`)
- Frontend: 49 passed (16 files) — `npx vitest run`; build clean
- `docs/notes/phase-4-store.md`'s `dod_verify_phase4.py` run: the "one real
  app installs as exactly one CT, with live log, archived log, audit row,
  consent step" DoD clause proved against `tests.support.make_app` + a real
  `TestClient` + `tests/fakes/ssh.py`'s `FakeSSHConnection` (no live PVE, no
  real SSH, no browser on this box)
- Real 24-slug live classifier measurement (this task, real network, real
  `classify_install_feasibility`, no mocks): **15/24 installable (62.5%)**,
  9/24 unsupported (all "install script requires interactive input, no
  non-interactive entrypoint"), 0 fetch failures — the true number for this
  v1 catalog, not the phase-4 spike's 493/559 full-corpus estimate

**Deviations** (full list + rationale in the notes doc): Task 1's TOFU
pinning had a real bug only visible against a live asyncssh server
(`known_hosts=None` silently disabling the pin check) caught in review, not
by the implementer's own fake-backed tests; Tasks 4/6/7/8 proactively added
entitlement gating + audit-log writes the plan's sample code omitted; Task
5 fixed an executor-isolation violation in the plan's own sample code by
adding `SSHExecutor.run_for_host` (key never leaves `executor/`) and
corrected `App.slug`'s scheme to include `host_id`; Task 8 fixed a
structurally-unsatisfiable diff-direction assertion in the plan's own test;
Task 12 kept the real 4-part install-consent gate rather than weakening it
to match a contradictory test in the plan, strengthening the test instead.
Known, undelivered gaps carried into Phase 9: no staleness banner on the
Store page (cache-survival itself works; the UI indicator does not exist),
and the `category`/`description`/`icon_url`/`popularity` v1 gap documented
before implementation began (no public community-scripts bulk metadata API).

### 2026-07-31T00:15:00+05:30 — Phase 5 — execute-plan completed

Plan: `docs/superpowers/plans/2026-07-30-phase-5-console.md`. All 12 tasks
implemented and committed directly to `main`, each individually reviewed (fix
rounds where the reviewer found real gaps: Tasks 3/4's shared `asyncio.wait()`
exception-swallowing bug in the plan's own example code, Task 6's missing
audit row on the node-shell toggle, Task 9's `@novnc/novnc/core/rfb` import
path that doesn't actually resolve). Task 12 closed out with DoD
verification, this notes doc, and this buildlog entry. Full details, DoD
proof, and deviations in `docs/notes/phase-5-console.md`.

**What was built:**
- `ProxmoxClient.termproxy`/`.node_termproxy`/`.vncproxy` (backend/proxploy/
  services/proxmox.py) + matching `FakePVE` support
- `console_tickets` schema + `mint_ticket`/`redeem_ticket`
  (backend/proxploy/services/consoletickets.py) — single-use, short-TTL,
  bound to a specific Proxmox target and its upstream ticket
- PtyBridge (backend/proxploy/services/ptybridge.py): translates doc 05's
  simple browser JSON framing to/from Proxmox's own `termproxy`/xtermjs wire
  protocol, reverse-engineered directly from `pve-xtermjs`'s own client code
- ConsoleProxy (backend/proxploy/services/consoleproxy.py): dumb byte-for-byte
  relay for VM noVNC (`vncproxy`/`vncwebsocket`), no translation needed
- `POST /apps/{id}/console/tickets` + `WS /apps/{id}/console/ws` (CT
  terminal), `POST /hosts/{id}/shell/tickets` + `WS /hosts/{id}/shell/ws`
  (node shell, three-way gated: role + entitlement + per-host opt-in),
  `POST /vms/{id}/console/tickets` + `WS /vms/{id}/vnc/ws` (VM noVNC) — every
  ticket-mint route audits `console.open`, every WS route is ticket-only
  (no session cookie)
- Frontend: `Terminal.tsx` (xterm.js + fit addon), `VncConsole.tsx`
  (`@novnc/novnc`'s `RFB`), `api/consoles.ts` ticket hooks, Console tab wired
  into app detail (CT) and VM detail, node-shell section on node detail, and
  the shared `TerminalPanel` log viewer used by both the live CT log tab and
  archived job logs

**Verification:**
- Backend: 333 passed, 2 skipped, 3 deselected — `pytest tests/ -q -m "not
  pve_integration and not e2e"` (the extra deselected test is this task's new
  gated live-PVE test, see below)
- Backend: executor isolation OK (`scripts/check_executor_isolation.py`,
  unaffected by this phase)
- Frontend: 65 passed (20 files) — `npx vitest run`; build clean
- `docs/notes/phase-5-console.md`'s `dod_verify_phase5.py` run: all three
  doc-10 DoD sub-clauses ("through the Proxploy origin only", "survive
  reconnect", "write audit rows on open") proved against
  `tests.support.make_app` + `FakePVE` + `FakeXtermUpstream` (no live PVE, no
  real websocket to Proxmox, no browser on this box)
- `backend/tests/test_console_pve_integration.py` added (Task 12): a
  `pve_integration`-marked, disposable-live-PVE-gated test proving-or-
  disproving the plan's own "Spike correction" finding — whether this PVE
  host's `termproxy` accepts API-token auth for the LXC/node-shell path
  (Proxmox bugzilla #6079, fixed for VMs in `qemu-server` 9.1.7+, unconfirmed
  for LXC/node-shell). Skips here, same standing no-live-PVE limitation every
  prior phase has stated — the single biggest open item this phase carries
  forward

**Deviations** (full list + rationale in the notes doc): Tasks 3 and 4 each
independently found and fixed the same real bug in the plan's own example
code — `asyncio.wait()` never propagates a done task's exception to the
`await` point, so an idle timeout or abnormal close would stop the bridge but
silently misreport `exit_code=0`; both fixes now walk the `done` set and
re-raise, both reviewer-verified via live repros. Task 7 deliberately skipped
the webgl xterm.js addon (marginal render-perf gain, no functional
difference, called out rather than silent). Task 9 fixed a `@novnc/novnc/
core/rfb` import path that doesn't resolve against the real package's
`exports` field, and a `FakeRFB.disconnect` test-infra bug that was silently
skipping the reconnect test's actual assertion. Task 6 added a missing audit
row on `PATCH /hosts/{id}`'s node-shell toggle (`host.node_shell_toggle`).
Known, undelivered/deferred items carried forward: no automated concurrency
regression test for `redeem_ticket`'s single-use atomicity (proven live by a
20-thread race in review, not committed to the suite), no dedicated
mismatched-ticket-kind test on `app_console_ws` specifically, no
operator-rejected-on-node-shell test, a cosmetic entitlement-loading tooltip
flash on the node-shell button, and no visibility-based pause on log
polling — none block this phase's DoD. The token/termproxy open question
above is the one item that needs a real PVE host to close out.
