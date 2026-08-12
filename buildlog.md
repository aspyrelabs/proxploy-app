# Proxploy Build Log

Autonomous build loop: cycles `/superpowers:writing-plans` (Fable 5) then
`/superpowers:executing-plans` (Sonnet 5) through each phase in
`docs/10-build-sequence.md`, fully unattended, no phase-gate pauses.
Driven by `bin/build-cycle.sh` on the `proxploy-build.timer` systemd user timer.

<!-- STATE: phase=6 step=plan -->

### 2026-07-29T01:22:23+05:30: Phase 1, write-plan FAILED (exit 1)

See /home/aasim/workspace/aspyrelabs/proxploy/proxploy-app/logs/build-2026-07-29.log for details. Will retry next run.

### 2026-07-29T01:30:04+05:30: Phase 1, write-plan FAILED (exit 1)

See /home/aasim/workspace/aspyrelabs/proxploy/proxploy-app/logs/build-2026-07-29.log for details. Will retry next run.

### 2026-07-29T02:00:03+05:30: Phase 1, write-plan FAILED (exit 1)

See /home/aasim/workspace/aspyrelabs/proxploy/proxploy-app/logs/build-2026-07-29.log for details. Will retry next run.

### 2026-07-29T02:30:08+05:30: Phase 1, write-plan FAILED (exit 1)

See /home/aasim/workspace/aspyrelabs/proxploy/proxploy-app/logs/build-2026-07-29.log for details. Will retry next run.

### 2026-07-29T03:34:09+05:30: Phase 1, write-plan completed (fable-5)

Plan: /home/aasim/workspace/aspyrelabs/proxploy/proxploy-app/docs/superpowers/plans/2026-07-29-phase-1-foundation.md

### 2026-07-29T04:29:46+05:30: Phase 1, execute-plan FAILED (exit 1)

See /home/aasim/workspace/aspyrelabs/proxploy/proxploy-app/logs/build-2026-07-29.log for details. Will retry next run (plan step is not re-run).

### 2026-07-29T04:29:49+05:30: Phase 1, execute-plan FAILED (exit 1)

See /home/aasim/workspace/aspyrelabs/proxploy/proxploy-app/logs/build-2026-07-29.log for details. Will retry next run (plan step is not re-run).

### 2026-07-29T04:30:03+05:30: Phase 1, execute-plan FAILED (exit 1)

See /home/aasim/workspace/aspyrelabs/proxploy/proxploy-app/logs/build-2026-07-29.log for details. Will retry next run (plan step is not re-run).

### 2026-07-29T05:00:05+05:30: Phase 1, execute-plan FAILED (exit 1)

See /home/aasim/workspace/aspyrelabs/proxploy/proxploy-app/logs/build-2026-07-29.log for details. Will retry next run (plan step is not re-run).

### 2026-07-29T05:30:08+05:30: Phase 1, execute-plan FAILED (exit 1)

See /home/aasim/workspace/aspyrelabs/proxploy/proxploy-app/logs/build-2026-07-29.log for details. Will retry next run (plan step is not re-run).

### 2026-07-29T06:00:05+05:30: Phase 1, execute-plan FAILED (exit 1)

See /home/aasim/workspace/aspyrelabs/proxploy/proxploy-app/logs/build-2026-07-29.log for details. Will retry next run (plan step is not re-run).

### 2026-07-29T06:30:08+05:30: Phase 1, execute-plan FAILED (exit 1)

See /home/aasim/workspace/aspyrelabs/proxploy/proxploy-app/logs/build-2026-07-29.log for details. Will retry next run (plan step is not re-run).

### 2026-07-29T07:00:05+05:30: Phase 1, execute-plan FAILED (exit 1)

See /home/aasim/workspace/aspyrelabs/proxploy/proxploy-app/logs/build-2026-07-29.log for details. Will retry next run (plan step is not re-run).

### 2026-07-29T07:30:04+05:30: Phase 1, execute-plan FAILED (exit 1)

See /home/aasim/workspace/aspyrelabs/proxploy/proxploy-app/logs/build-2026-07-29.log for details. Will retry next run (plan step is not re-run).

### 2026-07-29T08:20:58+05:30: Phase 1, execute-plan completed (sonnet-5)

All 16 Phase 1 tasks are now complete and committed, one commit per task, directly to `main` across all four repos (matching this project's established no-branch convention, confirmed by every prior commit in the history); so I skipped the `finishing-a-development-branch` skill, since there's no feature branch to merge here; work streamed straight to `main` as it was built.

## What was built

**proxploy-app (backend, FastAPI + SQLAlchemy + Alembic):**
- Full doc-04 schema (24 tables) via Alembic migration 0001, SQLite-WAL by default, Postgres-portable
- SecretStore (Fernet/MultiFernet, 0400-root-only key file, regeneration guard)
- Append-only, secret-redacting audit writer + admin audit-read endpoint
- Local auth: argon2, DB sessions, CSRF double-submit, per-IP rate limiting, forced first-run owner bootstrap, RBAC stub
- Entitlement registry (all 81 flags ON), Ed25519 verification client with grace window, `/entitlements`
- Dormant license activate/refresh/remove flow against proxploy-api, with background refresh and an e2e roundtrip test
- Proxmox client layer (`ProxmoxClient`, single PVE-8/9 branch point) + fake PVE fixture infra + a gated live-PVE integration test
- Host onboarding, probe/create/list/detail/test, encrypted credential storage, consented SSH key enrolment; the audited route template every later route copies
- Settings service (`.enc` hygiene) + `/meta/version`, `/meta/onboarding`

**proxploy-app (frontend, Vite + React 19 + Tailwind v4):**
- Verbatim design tokens, API client with CSRF, login form
- App shell: fixed 8-page nav, topbar, theme toggle, entitlements hook, `LockVeil`, honest placeholder pages
- Onboarding wizard (admin → host → SSH consent → done) + Settings page (plan/hosts/add-host)

**CI + isolation:** executor-isolation lint (asyncssh/SSH-key-accessor confined to `executor/`, which doesn't exist yet), license audits in both repos, a Postgres CI leg, a secrets-gated disposable-PVE matrix, and the backend now serves the built SPA at `/`.

**proxploy-api, proxploy-web, proxploy-docs:** licensing resolver (from earlier in this build) plus its own CI; web/docs remain intentional empty scaffolds per the plan.

## Verification
- `backend`: 39 passed, 2 skipped (env-gated live-PVE + one other); `pytest -q`
- `backend`: `check_executor_isolation.py` → OK
- `frontend`: 5 passed (3 files), `npm test`; `npm run build` clean; SPA-serving confirmed via `TestClient`
- `proxploy-api`: 4 passed, `pytest -q`
- All three DoD quality gates hold; the Phase-1 DoD verification map's proof artifacts all exist and pass

Noted deviations (documented in the relevant commit messages): a few TS `as never` casts for routes/circular imports that resolve themselves as later tasks register those routes; `psycopg` (LGPL) split into its own extras group so it doesn't taint the license audit; license-audit commands needed `--ignore-packages`/`OFL-1.1` additions to correctly exclude our own unpublished packages and allow the SIL font license. No live PVE or Docker was available on this box, so those legs stayed env/secret-gated as designed, and the dev-server manual walkthrough was skipped (sandbox blocks background servers) in favor of the equivalent `TestClient`-based checks the plan itself sanctions for the no-PVE case.

### 2026-07-29T08:58:52+05:30: Phase 2, write-plan completed (fable-5)

Plan: /home/aasim/workspace/aspyrelabs/proxploy/proxploy-app/docs/superpowers/plans/2026-07-29-phase-2-observe.md

### 2026-07-29T10:24:02+05:30: Phase 2, execute-plan FAILED (exit 1)

See /home/aasim/workspace/aspyrelabs/proxploy/proxploy-app/logs/build-2026-07-29.log for details. Will retry next run (plan step is not re-run).

### 2026-07-29T10:24:06+05:30: Phase 2, execute-plan FAILED (exit 1)

See /home/aasim/workspace/aspyrelabs/proxploy/proxploy-app/logs/build-2026-07-29.log for details. Will retry next run (plan step is not re-run).

### 2026-07-29T10:30:08+05:30: Phase 2, execute-plan FAILED (exit 1)

See /home/aasim/workspace/aspyrelabs/proxploy/proxploy-app/logs/build-2026-07-29.log for details. Will retry next run (plan step is not re-run).

### 2026-07-29T11:00:05+05:30: Phase 2, execute-plan FAILED (exit 1)

See /home/aasim/workspace/aspyrelabs/proxploy/proxploy-app/logs/build-2026-07-29.log for details. Will retry next run (plan step is not re-run).

### 2026-07-29T11:30:04+05:30: Phase 2, execute-plan FAILED (exit 1)

See /home/aasim/workspace/aspyrelabs/proxploy/proxploy-app/logs/build-2026-07-29.log for details. Will retry next run (plan step is not re-run).

### 2026-07-29T11:45:00+05:30: Phase 2, execute-plan completed (Friday)

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

### 2026-07-29T15:00:00+05:30: Phase 3, execute-plan completed

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
- Backend: 190 passed, 1 skipped, 2 deselected; `pytest -q -m "not pve_integration and not e2e"`
- Backend: executor isolation OK; license audit OK
- Frontend: 33 passed (11 files); build clean; license audit OK
- `docs/notes/phase-3-act.md`'s `dod_verify.py` run: all 4 doc-10 DoD clauses
  proved against `tests.support.make_app` + `FakePVE` (no live PVE, no
  Docker, no browser on this box; clause 1's UI half is covered by
  `frontend/src/tests/lifecycle.test.tsx` under jsdom, not a visual run)

**Deviations** (full list + rationale in the notes doc): lifecycle verbs are
a documented superset of doc 05's paths; jobs/activity endpoints carry
additional entitlement gates doc 05 left blank; doc 05 §Streaming 4 was
amended to add `target_type` to the `job` SSE event; job-row writes are
inline on the event loop by design; `hosts/{id}/tasks` and `hosts/{id}/sync`
were deliberately not built (no Phase 3 dependency).

### 2026-07-30T16:28:38+05:30: Phase 4, execute-plan completed

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
- Backend: 290 passed, 2 skipped, 2 deselected; `pytest tests/ -q -m "not pve_integration and not e2e"`
- Backend: executor isolation OK (`scripts/check_executor_isolation.py`)
- Frontend: 49 passed (16 files), `npx vitest run`; build clean
- `docs/notes/phase-4-store.md`'s `dod_verify_phase4.py` run: the "one real
  app installs as exactly one CT, with live log, archived log, audit row,
  consent step" DoD clause proved against `tests.support.make_app` + a real
  `TestClient` + `tests/fakes/ssh.py`'s `FakeSSHConnection` (no live PVE, no
  real SSH, no browser on this box)
- Real 24-slug live classifier measurement (this task, real network, real
  `classify_install_feasibility`, no mocks): **15/24 installable (62.5%)**,
  9/24 unsupported (all "install script requires interactive input, no
  non-interactive entrypoint"), 0 fetch failures; the true number for this
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

### 2026-07-31T00:15:00+05:30: Phase 5, execute-plan completed

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
  (backend/proxploy/services/consoletickets.py), single-use, short-TTL,
  bound to a specific Proxmox target and its upstream ticket
- PtyBridge (backend/proxploy/services/ptybridge.py): translates doc 05's
  simple browser JSON framing to/from Proxmox's own `termproxy`/xtermjs wire
  protocol, reverse-engineered directly from `pve-xtermjs`'s own client code
- ConsoleProxy (backend/proxploy/services/consoleproxy.py): dumb byte-for-byte
  relay for VM noVNC (`vncproxy`/`vncwebsocket`), no translation needed
- `POST /apps/{id}/console/tickets` + `WS /apps/{id}/console/ws` (CT
  terminal), `POST /hosts/{id}/shell/tickets` + `WS /hosts/{id}/shell/ws`
  (node shell, three-way gated: role + entitlement + per-host opt-in),
  `POST /vms/{id}/console/tickets` + `WS /vms/{id}/vnc/ws` (VM noVNC), every
  ticket-mint route audits `console.open`, every WS route is ticket-only
  (no session cookie)
- Frontend: `Terminal.tsx` (xterm.js + fit addon), `VncConsole.tsx`
  (`@novnc/novnc`'s `RFB`), `api/consoles.ts` ticket hooks, Console tab wired
  into app detail (CT) and VM detail, node-shell section on node detail, and
  the shared `TerminalPanel` log viewer used by both the live CT log tab and
  archived job logs

**Verification:**
- Backend: 333 passed, 2 skipped, 3 deselected; `pytest tests/ -q -m "not
  pve_integration and not e2e"` (the extra deselected test is this task's new
  gated live-PVE test, see below)
- Backend: executor isolation OK (`scripts/check_executor_isolation.py`,
  unaffected by this phase)
- Frontend: 65 passed (20 files), `npx vitest run`; build clean
- `docs/notes/phase-5-console.md`'s `dod_verify_phase5.py` run: all three
  doc-10 DoD sub-clauses ("through the Proxploy origin only", "survive
  reconnect", "write audit rows on open") proved against
  `tests.support.make_app` + `FakePVE` + `FakeXtermUpstream` (no live PVE, no
  real websocket to Proxmox, no browser on this box)
- `backend/tests/test_console_pve_integration.py` added (Task 12): a
  `pve_integration`-marked, disposable-live-PVE-gated test proving-or-
  disproving the plan's own "Spike correction" finding, whether this PVE
  host's `termproxy` accepts API-token auth for the LXC/node-shell path
  (Proxmox bugzilla #6079, fixed for VMs in `qemu-server` 9.1.7+, unconfirmed
  for LXC/node-shell). Skips here, same standing no-live-PVE limitation every
  prior phase has stated, the single biggest open item this phase carries
  forward

**Deviations** (full list + rationale in the notes doc): Tasks 3 and 4 each
independently found and fixed the same real bug in the plan's own example
code, `asyncio.wait()` never propagates a done task's exception to the
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
polling, none block this phase's DoD. The token/termproxy open question
above is the one item that needs a real PVE host to close out.

### 2026-07-31T00:45:00+05:30: Phase 5, final whole-branch review + fix wave

Per-task reviews above cover Tasks 1-12 individually; the final whole-branch
review (opus) covering the full `433ce46..fb01529` range found 1 Critical +
11 Important cross-task integration gaps that no single task's reviewer was
scoped to see, each sat precisely at a seam between two individually-correct
tasks. Fixed in one consolidated wave (`5c974d9`, `432e22a`):

- **Critical**: the Logs tab (Task 11) polled `GET /apps/{id}/logs`, which
  never existed, confirmed 404, silently empty terminal. No CT-log-tailing
  subsystem exists anywhere in the codebase (`ProxmoxClient` has no `pct
  exec`; the executor only runs host-side install scripts), so the honest
  fix is a real `501` route plus a frontend `EmptyState` saying so, not a
  fabricated tail.
- **Important** (11): PtyBridge discarded the buffered shell prompt after
  the `"OK"` handshake frame (blank terminal until Enter); the test meant to
  prove that flush didn't call the production function at all; the plan's
  own mandated 30s keepalive was never implemented; `Terminal`/`VncConsole`'s
  reconnect-on-drop had no attempt cap (unbounded loop against a real
  Proxmox host on exactly the PVE-token-rejection case this plan documents);
  the actionable `PtyBridgeError` text was sent to the browser but never
  rendered; the literal `"OK"` sentinel leaked into the terminal; `vm_vnc_ws`
  had no error handling and a differently-typed error than the PTY path;
  blocking TLS/socket I/O ran directly on the event loop inside the async
  connect functions; the bridges' `finally` blocks could skip the
  upstream-close step if the browser-side close raised first (a leaked PVE
  session per abandoned console); no frontend UI existed anywhere to toggle
  `Host.node_shell_enabled` (added to the Settings page); and the resize
  control frame's `cols`/`rows` were read without validation at a trust
  boundary.
- Several Minor items bundled in: hardcoded `:8006` ignoring a host's actual
  port, a ticket-kind check missing between `_run_pty_ws`'s shared routes,
  `websockets` bumped `>=13` → `>=14`, a deleted-target race with no `None`
  guard, a redundant index, and the plan doc itself being untracked in git.

Backend rose to 340 passed / 2 skipped / 3 deselected, frontend to 71 passed
/ 20 files, clean build. A scoped re-review of the fix wave (opus)
independently re-ran both suites, confirmed 16 of 18 findings cleanly fixed
with real regression tests, and found the fix wave itself introduced two
narrow new issues, both adjudicated (not a second fix wave, per the
process) as real but deferred, nothing later in this phase depends on
either: the new keepalive teardown can, on a narrow timing window, skip the
just-fixed close-ordering cleanup; and the reconnect give-up screen can
unmount the `Terminal` before the user reads the actionable error it was
built to show. Both documented with exact fix guidance in
`docs/notes/phase-5-console.md`'s "Final whole-branch review" section for a
fast-follow.

**Phase 5 final state**: all 12 planned tasks + 1 consolidated fix wave,
15 commits total (`433ce46..432e22a`) plus this buildlog/notes bookkeeping,
all committed directly to `main`. Ready to merge, with two parked findings.

### 2026-07-31T22:18:00+05:30: Phase 6, execute-plan completed

Plan: `docs/superpowers/plans/2026-07-31-phase-6-infra.md`. All 17 tasks
implemented and committed directly to `main` (`2182940..5ad5579`), each
individually reviewed (fix rounds where the reviewer found real gaps: Task
4's `requests-toolbelt` finding below, Task 8's anti-stampede sync lock and
per-storage-failure isolation, Task 9's audit-row assertion gap on the
self-targeted-restore refusal, Task 11's missing audit assertions on all
three VM-delete refusal branches, Task 14's dead untested branch in
`errBody()`, Task 16's two-round false-negative test fix). Task 18 closed
out with DoD verification, this notes doc, and this buildlog entry. Full
details, DoD proof, and deviations in `docs/notes/phase-6-infra.md`.

**What was built:**
- **Storage**: `ProxmoxClient` reads/writes (`storages`, `storage_status`,
  `storage_content`, `cluster_storage`, `storage_create/update/remove`,
  `storage_upload`, `storage_delete_volume`) + `client_for_host` extraction;
  `GET/POST/PATCH/DELETE /storage[...]` (`backend/proxploy/api/storage.py`);
  chunked-spool multipart upload job with crash-safe cleanup on boot;
  frontend Storage page + upload/attach/edit/detach dialogs
- **Network**: `netconfig.py` NIC-string round-tripper; bridge/guest-config
  `ProxmoxClient` methods; `GET /network/bridges|throughput`,
  `GET/PUT /{apps|vms}/{id}/network[/{iface}]`, host bridge stage/apply/
  revert (`POST/PUT/DELETE /network/bridges/...`, `POST /network/{h}/{n}/
  apply|revert`, typed node-name confirmation on apply); frontend Network
  page + NIC/bridge forms
- **Backups**: `backupjobs.py` sync (droppable `backups` mirror, anti-
  stampede lock, auto-sync-on-stale), run/restore/prune `ProxmoxClient`
  methods + routes (`POST /backups/run`, `POST /backups/{id}/restore`,
  `GET /backups/prune-preview`, `POST /backups/prune`, `DELETE /backups/
  {id}`); frontend Backups page (last placeholder page deleted)
- **VM lifecycle**: snapshot list/create/rollback/delete, create, clone,
  delete `ProxmoxClient` methods + job handlers + routes (`GET/POST /vms/
  {id}/snapshots`, rollback with typed confirm, `POST /vms`, `POST /vms/
  {id}/clone`, `DELETE /vms/{id}`; owner-role 3-gate refusal chain);
  frontend snapshots tab, VM create wizard, clone dialog
- **Shared**: `pvetask.py::await_task`, `api/jobs.py::enqueue_and_audit`,
  both extracted from the existing lifecycle-job pattern and reused by every
  route above

**Verification:**
- Backend: 491 passed, 2 skipped, 4 deselected (178.01s); `pytest tests/ -q
  -m "not pve_integration and not e2e"` (deselected rose from 3 to 4: this
  task's new gated live-PVE test)
- Backend: executor isolation OK, unaffected by this phase
- Backend license audit: fails locally on `psycopg` (LGPL), pre-existing,
  documented since Phase 1/4, `postgres` extras never installed in CI's
  actual gate; this phase's own two new dependencies are both cleanly
  allowlisted (see Deviations)
- Migrations: 7 passed, 2 skipped; `alembic heads` = `2330a95b98d2`,
  unchanged, zero migrations this phase
- Frontend: 118 passed (26 files), `npx vitest run`; build clean; lint
  exit 0 (pre-existing warning classes only, no errors)
- `docs/notes/phase-6-infra.md`'s `dod_verify_phase6.py` run: all four
  doc-10 DoD clauses ("every nav page renders real content", "VM created/
  snapshotted/rolled back/cloned", "CT backs up to PBS and restores as a new
  CTID", "ISO uploads through Proxploy") proved against `tests.support.
  make_app` + `FakePVE` (no live PVE, no browser on this box)
- `backend/tests/test_infra_pve_integration.py` added (Task 18): a
  `pve_integration`-marked, disposable-live-PVE-gated test for what only a
  real host can prove (real multi-hundred-MB upload, a real vzdump-to-PBS
  and restore, real network apply/revert semantics on PVE 8.x/9.x, and that
  prunebackups' dry-run really deletes nothing). Skips here, same standing
  no-live-PVE limitation every phase has stated

**Deviations** (full list + rationale in the notes doc): Phase 6 shipped
**two** new backend dependencies, not one as both the plan's header and this
task's own brief claimed, `python-multipart` (Apache-2.0, Task 4, FastAPI
requires it to define an `UploadFile` route at all) and `requests-toolbelt`
(Apache Software License, added in Task 4's fix round after discovering
proxmoxer silently falls back to buffering an entire upload in RAM without
it, and hard-fails with `OverflowError` above ~2 GiB; the exact failure
mode `storage_upload_max_bytes: 16 GiB` was supposed to make safe). Zero
Alembic migrations, as planned; the `backups` table and every column this
phase populates existed unused since migration 0001. Doc 05 was amended
(Task 18) for three real omissions this phase surfaced: a missing §Network
section for guest/host config endpoints, six read endpoints with a blank
entitlement column that should have read `storage.view`/`storage.content`/
`network.view`/`vms.snapshots`, and a missing `GET /backups/prune-preview` +
`POST /backups/prune` pair, plus a fourth, unrequested fix found in the
same table: `POST /backups/run`/`POST /backups/{id}/restore` were both
listed under `backups.pbs`, but the code gates them on the distinct
`backups.run`/`backups.restore` keys doc 01 already defines. A docstring
defect in `api/vms.py`'s snapshot
rollback (claiming it reuses `enqueue_lifecycle`'s `self_target` 409 shape,
when it actually emits `confirm_required`, the frontend keys on the exact
string) was corrected in the same pass. The staged-network-changes indicator
was deliberately not built: proxmoxer's `.get()` unwraps only the `data` key
and drops the sibling `changes` property PVE uses to report pending state,
so Apply/Revert are always offered rather than guessing at pending state.
Linked-clone validity is not pre-checked, Proxploy does not track
template-ness, so PVE's rejection is surfaced verbatim. `POST /backups/
prune` ships unconsumed by any UI control (retention-by-policy belongs to
Phase 7's scheduler). `sync_host_backups` reads only `Host.node_name`, so
node-local archives on a cluster's other nodes are missed until `Host`
models more than one node. An adjudicated, intentionally asymmetric audit
decision is recorded in the notes doc: only the `self_target` restore
refusal writes an audit row (`guest_missing`/`confirm_required`/
`guest_running` are ordinary retryable rejections, not incidents). Known,
carried-forward test-hygiene item: `test_concurrent_stale_reads_enqueue_
only_one_sync` is slow and timing-variable (62s/62s/2s across three runs,
passing every time), deliberately left as-is. Three frontend
`window.confirm`-dismissed tests (`backups.test.tsx`'s archive-delete, and
two in `storage-mutations.test.tsx`) were suspected false negatives via the
same microtask-timing gap Task 16 found and fixed on a sibling test; the
final whole-branch review below individually neutralised each production
guard to check. Only `storage-mutations.test.tsx`'s detach test was
genuinely broken, fixed with the same macrotask-flush idiom. The other two, 
`backups.test.tsx`'s archive-delete and `storage-mutations.test.tsx`'s
volume-delete, do fail when their guards are removed, via a `waitFor`
already present, so they were verified load-bearing and correctly left
untouched.

### 2026-07-31T22:45:00+05:30: Phase 6, final whole-branch review + fix wave

Per-task reviews above cover Tasks 1-18 individually; the final whole-branch
review (opus) covering the full `ce590bd..13a0737` range (25 commits, 68
files, ~10.8k insertions) returned MERGE AFTER FIXES with 4 blocking
findings plus same-wave items, fixed in `172167d` and `b36846c`:

- **Two parameter-collision bugs, both proven live against the running
  app.** `api/network.py::create_bridge` and `api/storage.py::attach_storage`
  each built their PVE call as `{route_key: value, **caller_config}`, so a
  caller-supplied `config` key named `iface`/`type` (or `storage`/`type`)
  silently overrode the route's own. Demonstrated: a request naming `vmbr9`
  returned 201 saying `vmbr9`, wrote an audit row saying `vmbr9`, and staged
  a redefinition of **`vmbr0`**, the management bridge, as a VLAN
  interface, which a subsequent apply would have `ifreload`ed. Fixed by
  reordering so route-controlled keys win, with regression tests asserting
  against what the PVE fake actually recorded rather than the response body.
  Worth stating honestly: a per-task review had checked this pattern and
  reported it absent; it had checked `vms.py`, not `storage.py`, which is
  exactly the kind of seam only a whole-branch view catches.
- **`api/network.py` never caught `ProxmoxError`**, unlike every sibling
  router, so seven call sites plus `api/backups.py::prune_preview_route`
  returned bare 500s with no audit row. `client_for_host` raises it for a
  routine missing-credential (no outage required), and `list_bridges`
  iterates every host, so one unreachable host 500'd the whole Network page.
  Fixed to the `storage.py` pattern (scrubbed 502 + `result="error"` audit
  row), with `list_bridges` degrading per host into an `errors` list.
- **`settings.pve_task_timeout_s` was dead config.** Both `config.py` and
  `pvetask.py` documented it as the ceiling every Phase 6 handler passes to
  `await_task`; none of the 13 call sites passed it, so every job silently
  used the 300s default. A `vm.clone`, `backup.restore` or vzdump exceeding
  five minutes would report FAILED while the PVE task continued
  successfully, inviting a destructive retry on a mid-flight restore. The
  existing test only asserted the setting *parsed*. Now threaded through all
  13 sites with the default raised to 3600s (these handlers are
  disk-copy-bound, unlike lifecycle's start/stop which still uses its own
  shorter constant), and the new test proves the configured value actually
  reaches `await_task`.
- **`DELETE /backups/{id}` was gated on `backups.pbs`**: the same key as
  the backup list, so view rights implied permanent-delete rights on
  archives. Moved to `backups.retention`.
- `ProxmoxError` → `JobFailed` translation added to the seven Phase 6 job
  resolvers, matching `lifecycle.py`'s long-standing behaviour so a missing
  credential reports as a failed job rather than a handler bug. Dead code
  removed (`EDITABLE`, an unused role singleton).

The scoped re-review of that wave then found the wave had introduced two
regressions of its own, both fixed in `b36846c`: the per-host network
degrade was invisible in the UI (the frontend type lacked `errors` and
nothing rendered it, so an unreachable host silently vanished from the page
trading a loud failure for a quiet one), and the backup delete button was
left ungated after the entitlement change, so a `backups.pbs`-only tenant
saw a button that 403s.

Final suite state: backend 499 passed / 2 skipped / 4 deselected; frontend
121 passed across 26 files; Alembic head unchanged at `2330a95b98d2` (zero
migrations, as planned). Phase 6 spans `ce590bd..b36846c`.

**Phase 6 final state**: all 17 planned tasks + 1 consolidated fix wave, 27
commits total (`2182940..b36846c`) plus this buildlog/notes/doc-05
bookkeeping, all committed directly to `main`. Ready to merge.

### 2026-08-05T06:46:38+05:30: Phase 7, execute-plan completed

Doc 10 §Phase 7 DoD, verbatim: *"an unattended weekend: scheduled backups and
an auto-update window run, an induced CPU alert fires and resolves with
notifications both ways, and Monday's job history tells the whole story."*
19 tasks, full details in `docs/notes/phase-7-operate.md`.

**What shipped, per subsystem:**
- **Scheduler**: `jobs/scheduler.py`, `next_fire`/`validate`/`prime`/`due`/
  `fire_one`/`tick(app, now=None)`, `_target()` deriving a fired job's
  target from the job kind's dotted prefix rather than sniffing param key
  names, `SYSTEM_SCHEDULES` seeding "Catalog refresh" (nightly) and "Metrics
  maintenance" (hourly) at boot, one-way past an operator's own edit. A
  `Poller`-shaped `Scheduler` supervisor loop ticks every 30s in the
  lifespan. `api/schedules.py`: `GET`/`POST /schedules`, `PATCH`/
  `DELETE /schedules/{id}`, `POST /schedules/{id}/run`; frontend Schedules
  card in Settings + "Next scheduled" on Backups
- **App updates**: `services/appstore.py`, `pinned_ref`, `mark_updates_
  available` (derived, recomputed wholesale so a rollback un-advertises an
  update), the `app.update` job (re-runs the catalog script pinned to the
  CURRENT upstream commit over the install path, bracketed by CT-must-
  exist-before and no-new-CT-after guards, with a concurrency exclusion so
  an unrelated `app.install` running at the same time isn't blamed for a
  stray). `api/apps.py`: `GET`/`POST /apps/{id}/update` (same pin/diff/
  consent/stream/archive gate as install), `POST /apps/update-all` (one job
  per stale app, per-app skip reasons); frontend update-available badge,
  "Update to `<sha>`" diff+consent dialog, Cluster "Update all"
- **Alerting**: `services/alerts.py`, `evaluate()` (continuous-breach
  `duration_s` semantics, at most one open alert per rule×target, automatic
  recovery, no-samples-is-never-a-breach), `render_message`, `sse_frame`,
  `notify_transitions`. The poll supervisor now evaluates every cycle,
  publishes the `alert` SSE frame, THEN notifies; that order means a
  notifier failure never loses the SSE event. `api/alerts.py`: `GET`/
  `POST /alert-rules`, `PATCH`/`DELETE /alert-rules/{id}`,
  `GET /alert-rules/metrics`, `GET /alerts`, `POST /alerts/{id}/ack`.
  `notifier.py`'s `channels_for`/`notify` widened for a rule's
  `channel_ids` override. `api/cluster.py`'s `GET /cluster/activity` now
  merges jobs + alerts + audit highlights, newest-first. Frontend:
  `/alerts` page (firing list + ack, resolved history, rule CRUD),
  `HealthFooter` bound to `/alerts?state=firing`, SSE `alert` handling,
  alert badge + severity in `ActivityFeed`
- **Metrics maintenance**: `services/metrics.py` gained the
  `metrics.maintain` job (rollup + retention pruning as a real scheduled,
  activity-feed-visible job) and now persists `mem_pct` + host `disk_pct`
  samples the poller had never written before this phase. The old
  `metrics_loop` asyncio loop is gone, replaced by the hourly system
  schedule

**Findings that contradicted the docs** (full detail in the notes doc):
- **APScheduler 4 does not exist.** PyPI's maximum stable is 3.11.3; 4.x is
  `a1`-`a6` pre-releases only, verified 2026-08-01. Docs 00/01/02/03/04/09/10
  all named "APScheduler 4". Shipped on the stable 3.11 line; only
  `CronTrigger` is used, and `jobs/scheduler.py`'s tick loop reads
  `schedules` directly on every pass rather than running APScheduler's own
  scheduler/jobstores, doc 04 already makes that table authoritative, and a
  second in-memory registry synced from it would be two sources of truth to
  reconcile on every CRUD write. Docs 02, 03 and 04 amended this task
  (Step 5); four docs still say "APScheduler 4" and were out of this task's
  amendment scope, `docs/00-decision-brief.md:79`, `docs/01-product-spec.
  md:193`, `docs/09-repository-structure.md:69`,
  `docs/10-build-sequence.md:226`.
- **The poller never wrote `mem_pct` or `disk_pct`.** Doc 04's `alert_
  rules.metric` enum named both; any memory/disk rule created before this
  phase would have sat enabled and never fired, silent, not a crash.
  Fixed in Task 8. `disk_pct` stays host-only: `/cluster/resources`'s
  guest disk figures are either allocated-not-used or routinely zero for
  QEMU, so Task 12 rejects a guest `disk_pct` rule at write time rather
  than accept one that can never honestly fire.
- **Zero migrations, again.** `schedules`, `alert_rules` and `alerts` have
  had full column parity since migration 0001; this phase populates tables
  that were already shaped for it. Alembic head unchanged at
  `2330a95b98d2`.

**Residual limitations** (both recorded, neither blocking the DoD):
- **The community-scripts update path.** A `ct/*.sh` decides install-vs-
  update for itself inside `build.func`; Proxploy cannot see that decision,
  so `app.update` brackets the SSH run with existence guards instead and
  fails loudly, naming any stray container, rather than silently trusting
  the script picked the right branch. `services/classifier.py` classifies
  install feasibility only, classifying update-path safety is separate,
  larger work.
- **No browser on this box.** Every frontend claim rests on Vitest +
  jsdom. `/alerts`, the health footer, the Schedules card and the update
  controls have never been rendered in a real browser here, the same gap
  Phases 5 and 6 recorded.
- **`backup.prune` scheduling is backend-only.** The `HANDLERS` entry and
  `POST /schedules` both accept it via the direct API; it was dropped from
  the frontend's `SCHEDULABLE` list (commit `ae83284`) because the generic
  `ScheduleForm` has no field that can collect the storage+retention spec
  the handler actually needs, and shipping a schedule row with empty
  `params` would fire and no-op forever rather than prune anything. A
  plan defect caught during Task 17, not an oversight; full detail in the
  notes doc.

**Verification:**
- `dod_verify_phase7.py` (task-19 brief, throwaway, not committed): all
  four doc-10 Phase 7 DoD clauses print OK, exit 0, run twice with
  identical output, proved through `tests.support.make_app` + `FakePVE` +
  a fake SSH connect factory driving the real routes, the real
  `JobBackend`, the real `Scheduler.tick` and the real evaluator (no live
  PVE, no browser on this box, the same standing limitation every phase
  has stated)
- Backend: **661 passed, 2 skipped, 4 deselected**; `pytest tests/ -q -m
  "not pve_integration and not e2e"` (baseline going into this phase was
  499 passed, 2 skipped)
- Frontend: **154 passed across 30 files** (baseline going into this phase
  was 121 across 26 files); build clean (same pre-existing chunk-size
  warning, nothing new); lint exit 0 (pre-existing warning classes only,
  no errors)
- Migrations: `alembic heads` = `2330a95b98d2`, unchanged; zero
  migrations this phase, confirmed against the current HEAD

**Phase 7 final state**: `git log --oneline b36846c..HEAD | tail -1`
returns `def0526` (Phase 6's own closing docs commit, landed one commit
after the `b36846c` boundary), the first substantive Phase 7 commit is the
next one, `ec5ccb9` ("feat(scheduler): cron math, due selection and
one-pass firing over the schedules table"), running 26 commits through
`ff73dd4` ("fix(ui): gate Update all on store.update_all entitlement")
before this task's own documentation commit. All 19 planned tasks
committed directly to `main`.

### 2026-08-05T18:55:00+05:30: Phase 8, execute-plan completed

Doc 10 §Phase 8 DoD, verbatim: *"a second admin logs in through SSO with 2FA,
a viewer cannot mutate anything, an API token drives the product, and an app
migrates between two non-clustered hosts with accurate downtime shown."*
22 tasks, full details in `docs/notes/phase-8-scale.md`.

**What shipped, per subsystem:**
- **Authorization**: `services/authz.py`, casbin RBAC-with-domains, a static
  `PERMISSIONS` matrix over (resource, action) → minimum role, and
  `sync_user` rebuilding a user's `g`-lines from `team_members`.
  `api/deps.py::authorize(resource, action, scope_of=…)` is now the single
  authorization path in the product: every router converted, `require_role`
  deleted. Scope resolvers (`scope_host`/`scope_app`/`scope_vm`/
  `scope_backup`) evaluate a role inside a team domain rather than globally.
  The enforcer is built **in memory** from code + `team_members`, not from
  `casbin_rules` via a sqlalchemy adapter, amendment, doc 03/04 updated
- **Teams**: `api/teams.py` teams/members CRUD, `GET /users`,
  `hosts.team_id` assignment; every membership write re-syncs the enforcer so
  a permission change takes effect in the same request sequence, not at the
  next restart. Frontend `TeamsCard` + per-host team select
- **OIDC**: `services/oidc.py`, discovery, S256 PKCE, RS256 ID-token
  validation via `joserfc` (`authlib.jose` is deprecated in Authlib 1.7.x),
  and just-in-time provisioning that is deny-by-default: without an
  explicitly configured role a first-time SSO user is created inactive and
  told why, and an OIDC identity is never auto-linked to a local account by
  matching email. Routes in `api/auth.py`, SSO entry on the login page
- **TOTP + sessions**: enrollment issuing a seed plus ten one-time recovery
  codes in their own table (`totp_recovery_codes`, migration `6cf6a0722d23`
  the plan's zero-migration blob design was rejected mid-implementation as
  racy on burn); two-step login where the password check alone never sets a
  cookie, gated by a single-use, TTL-bounded, 5-attempt-capped pending token
  usable at exactly one route; `GET`/`DELETE /auth/sessions`. Frontend TOTP
  login step + Security card (secret and `otpauth://` URI as text, no QR
  dependency added)
- **API tokens**: `ppk_…` bearer keys, hashed at rest, optionally scoped and
  optionally expiring; `authorize()` folds a key's scopes in ahead of the
  role check, so a key can only ever narrow its owner's rights. Frontend
  `ApiKeysCard` with a show-once secret panel
- **Cross-host migration**: `services/migrate.py` picks strategy from **live**
  Proxmox state (`hosts.cluster_name` was never populated before this phase
  and is written back as a side effect, never trusted as input):
  cluster-native, shared-storage, or vzdump + SFTP + restore. Preflight
  returns strategy, transfer size, estimate, blockers, warnings and a
  verbatim downtime statement; the job records the *measured* `downtime_s`
  so estimate and outcome sit side by side. The source CT is left stopped
  and intact, never deleted. Frontend `MigrateDialog`
- **Invariants**: two suites walk every registered route, one asserting each
  carries an `authorize()` marker or a reasoned allowlist entry, the other
  driving a viewer at every mutating route twice, once by cookie and once by
  bearer token

**Known gaps, stated plainly:**
- **No real IdP here.** Doc 10 says "round-trips against a real Authelia";
  there is none on this box. The substitute is a local mock provider with a
  real discovery document, real S256 PKCE exchange and real RS256 tokens
  verified against a real JWKS endpoint, protocol-complete, but not a
  third-party implementation on the wire. The DoD script prints this
  substitution in its own output rather than hiding it in a notes file
- **No live Proxmox host.** Migration is proven against two `FakePVE`s plus a
  fake SFTP layer driving the real preflight, handler and route
- **Token-authed audit rows still name the user, not the key.** Of 84
  `write_audit` call sites exactly one writes `actor_type="api_key"` (the
  scope-denial path); the rest predate API keys. `request.state.api_key` is
  populated and the upgrade path is an `actor_of(request)` helper threaded
  through the call sites, mechanical, deliberately not bundled here
- **The frontend suite is reliable only run sequentially on this box**, 
  unrelated suites flake under vitest's default file parallelism and pass in
  isolation; `--no-file-parallelism` passes every time
- **F1 (no route-level `errorComponent`)** remains open, a 5xx during route
  load white-screens the app. Phase 9 work per doc 10

**Verification:**
- `dod_verify_phase8.py` (throwaway, not committed): all four doc-10 Phase 8
  DoD clauses print OK, exit 0, run twice; identical output except the
  measured `downtime_s` (0.043819 s vs 0.040807 s), left unrounded because it
  is a real measurement
- Backend: **784 passed, 2 skipped, 4 deselected**; `pytest tests/ -q -m
  "not pve_integration and not e2e"`, run twice, identical (baseline entering
  the phase: 663)
- Frontend: **199 passed across 36 files**, `npx vitest run
  --no-file-parallelism` (baseline 154 across 30); build clean; lint exit 0,
  pre-existing warning classes only
- Frontend e2e: **1 passed**, real Chromium, login plus every nav page, clean
  console
- CI gates: executor isolation OK; backend and frontend license audits clean
  against the exact CI allow-lists
- Migrations: `alembic heads` = **`6cf6a0722d23`**, one migration this phase.
  The plan predicted zero; the recovery-code burn race is why that changed

### 2026-08-06T12:55:00+05:30: Phase 9a, execute-plan completed

Doc 10 §Phase 9's slice carried by 9a, verbatim: *"a stranger installs via the
one-liner on a clean PVE box … and self-updates to the next tagged release, 
without reading source code."* Doc 10's Phase 9 was one undifferentiated
"Deliver" block; the design spec split it into 9a–9d and this is the first.
16 tasks, full details in `docs/notes/phase-9a-install-update.md`.

**What shipped, per subsystem:**
- **Version**: `proxploy.__version__` is the single source of truth at
  `1.0.0`; `build_release.sh` overwrites the staged copy from `--version` so
  artifact, manifest and tag cannot disagree
- **Release format**: `services/release.py`, Ed25519 `verify_manifest` over
  the **raw manifest bytes before any parsing**, `verify_artifact` on sha256
  and size, `is_upgrade` refusing downgrades. Signature → checksum → unpack,
  and the shell side uses the same order deliberately: a format with two
  implementations is where a format drifts
- **Channel client**: `services/updater.py::check` plus `detect_shape()` →
  `systemd` | `docker` | `dev` and a `CAN_SELF_APPLY` table
- **Self-identity**: the lifespan persists `self.ctid`, closing a
  `selfguard.py` hook that had been inert since Phase 4, the app could not
  previously recognise its own container, so "don't destroy the CT you are
  talking to" was a rule with no subject
- **Update API**: `GET /meta/update` reports current/available/can-self-apply;
  `POST /meta/update` launches the updater via `systemd-run` **outside** the
  app's cgroup, because the script restarts `proxploy.service` and anything
  inside that cgroup is killed halfway through, leaving the symlink swapped
  and nothing serving
- **Layout + installer**: immutable `/opt/proxploy/releases/<version>/` each
  with its own venv, `current` as the symlink a switch or rollback moves, data
  and secrets outside the release tree. `install.sh` is both halves of the
  one-liner, CT create and self-push on the PVE host, then packages, service
  user, verified unpack, unit, and Caddy in front with `tls internal` fallback
- **Updater**: `packaging/proxploy-update`, backup *before* download, verify
  *before* unpack, migrate *before* switch, health *after* switch, roll back
  on any failure from the switch onward. The ordering is the design
- **Docker shape**: image + compose file that detect they are a container and
  instruct rather than self-apply
- **Frontend**: Settings update card, check, apply, poll, and a docker branch
  that states the boundary instead of hiding the button

**Known gaps, stated plainly:**
- **No real Proxmox node here.** The PVE half is proven against a fake `pct`
  that asserts the expected create call; `pct create` on real hardware is
  unproven. Same gap every phase since 4 has recorded
- **No real release channel.** Everything ran against a local `file://`
  channel signed with a throwaway key, spec D4 keeps publication out of
  implementation on purpose
- **The release private key does not exist yet** and
  `backend/proxploy/release_pubkey.pem` ships a **placeholder**. Replacing it
  is Step 1 of `docs/runbooks/publishing-a-release.md`. The public key ships
  *inside* the artifact, so rotating it requires publishing a release; the
  same bootstrap property doc 09 records for the entitlement key
- **Docker installs cannot self-apply, by design, not by omission**: 409 with
  the `docker compose pull` instruction
- **Task 8 (Caddy TLS) has no unit test**, by intent; the container harness
  serving real HTTPS is the only assertion that means anything about a TLS front
- **F1 (no route-level `errorComponent`)** carried forward from Phase 8, 9b

**The two bugs worth recording:**
- The installer had **never executed** before its harness; the first real run
  found seven bugs, each fixed at the shared root rather than in the caller
  that surfaced it. The sharpest: `pip install` without `-e` moved `proxploy/`
  into site-packages, so `main.py`'s `parents[2]/frontend/dist` resolved
  *inside the venv* and `/` served nothing while `/meta/health` answered fine.
  The API being up is not the same claim as the app being usable, and only one
  of those was being tested
- **Rollback restored the database as `root:root`.** `cp -a` from a backup
  written by `sqlite3 .backup` running as root, against a unit running as
  `User=proxploy` → crash-loop on `attempt to write a readonly database`. Data
  restored perfectly, box still down; the exact outcome the rollback path
  exists to prevent, reached by way of a rollback that "worked". Now: stop the
  unit before restoring (the poisoned version crash-loops on `RestartSec=3`
  and races it), `reset-failed` to clear systemd's start-limit, plain `cp` +
  explicit `chown`, and drop the stale `-wal`/`-shm` belonging to the database
  being replaced rather than let sqlite replay them over a different file

**Verification:**
- `dod_verify_phase9a.py` (throwaway, not committed; `backend/.gitignore`
  carries `dod_verify_phase*.py`): all four checks OK, exit 0, run **three
  times** (twice by the implementer, once independently), byte-identical every
  time. It surfaces only the harnesses' `OK:` lines, so the runs are identical
  outright rather than "modulo timings"
- Backend: **810 passed, 2 skipped, 4 deselected**; `pytest tests/ -q -m "not
  pve_integration and not e2e"` (baseline entering the phase: 784)
- Frontend: **205 passed across 37 files**, `npx vitest run
  --no-file-parallelism` (baseline 199 across 36); build clean; lint exit 0,
  30 warnings, 0 errors, pre-existing warning classes only
- Shell harnesses, all PASS: `test_install.sh` (unit active, app answers, TLS
  serves, SPA serves, re-run idempotent), `test_upgrade_rollback.sh` (1.0.0 →
  1.0.1 with data intact and a backup taken; poisoned 1.0.2 refused and rolled
  back to 1.0.1, healthy), `test_pve_half.sh` (expected `pct create`). Three
  harnesses, not the four the plan counted; `channel_fixture.sh` is a fixture
  builder they all consume, not a harness
- `shellcheck -x -P SCRIPTDIR` clean, exit 0, over `install.sh`,
  `proxploy-update`, `packaging/lib/*.sh`, `packaging/tests/*.sh`,
  `build_release.sh`
- CI grew three jobs: `scripts`, `install-harness`, `backend-py311`; the last
  because Task 12 lowered `requires-python` to 3.11 for the real Debian 12 LXC
  target, and a supported-version claim nothing tests is not a claim
- Migrations: `alembic heads` = **`6cf6a0722d23`**, unchanged; **zero
  migrations this phase**, as planned

### 2026-08-06T18:06:20+05:30: Phase 9b, execute-plan completed

Doc 10's Phase 9 DoD: a stranger *"completes onboarding, installs an app,
creates a VM, schedules a backup"*; four clauses no test had ever executed
through the UI. 9a shipped how the product gets onto a box; 9b is what a
stranger sees once it's there. 19 tasks, full details in
`docs/notes/phase-9b-onboarding-polish.md`.

**What shipped, per subsystem:**
- **Backend**: `ProxmoxError.kind` (`unreachable`/`auth`/`tls_fingerprint`/
  `refused`/`unknown`) classified once in `_wrap`, returned by `POST
  /hosts/probe` and `POST /hosts`; `POST /hosts/{id}/ssh/verify` proves an
  enrolled key actually opens a root shell instead of trusting a click, and
  sets `HostCredential.ssh_verified_at`; `GET /meta/onboarding` gained
  `ssh_pending` so the wizard can derive its own step from server state
- **Frontend primitives**: `QueryState` renders loading/error/empty/data as
  four different things (`EmptyState` gained an `action` slot to support
  it); 40 `?? []` call sites across 25 page lists, 15 selects and 3
  false-negative single-value queries converted; a themed `RouteError`
  closes Finding F1 (a 5xx used to white-screen the app outside the theme
  entirely); two hardcoded `#1d2733` literals replaced with `bg-elev` /
  `var(--elev)` behind a new static guard
- **Wizard**: `stepFrom(onboarding)` replaces `useState(0)`, so a reload
  resumes where you were instead of restarting and reporting "bad password"
  for an admin account that already exists; host step is skippable with
  errors that name a specific fix; authorize step verifies for real
- **Proof**: `tests/e2e_server.py` serves the real app with `FakePVE` +
  `FakeSSHConnection` (no env-var backdoor); `journey.spec.ts` drives a
  stranger through all four DoD clauses in a real browser for the first
  time ever; `light-theme.spec.ts` asserts nine pages carry no dark-only
  bypass literal; both gated in CI's new `e2e` job so they can't rot after
  passing once

**Two production bugs found by executing things, both hidden by test
fixtures supplying what the product itself never wrote:**
- **SSH passed a URL where asyncssh needs a hostname** (`fa5cce5`).
  `Host.address` (`https://10.0.0.5:8006`) went straight to asyncssh as the
  `host` argument. App install, app update, SSH verify, and both legs of
  cross-host migration **could never have worked against a real Proxmox
  node**, shipped across Phases 4, 7, 8 with passing DoDs every time.
  Invisible because every SSH test's fake ignores or dict-keys on whatever
  `host` string it's given; two `test_migrate_transfer.py` cases even keyed
  by the full URL and passed for the wrong reason. Fixed once at the two
  chokepoints every caller funnels through, `SSHExecutor.run()`,
  `sftp_copy()`: with a new `normalize_ssh_host()` helper
- **`Host.node_name` was write-never** (`fa4c795`). `POST /hosts` cannot
  learn it (PVE's `/version` carries none) and `ingest_cycle()` never
  persisted it either, only `tests/support.py`'s `seed_host_row` test
  helper ever set it. `GET /cluster/nodes` and the VM-create node picker
  both read that column directly, so a host created through the real
  onboarding flow offered no node, **a real user could not create a VM.**
  Found by the journey harness's first real run. Fixed in
  `pollers/__init__.py`: the first poll cycle that sees a node writes it
  once, mirroring `main.py`'s own self-`ctid` write-once pattern

**Smaller findings, each fixed:** `TotpCard`'s plan gate stuck on
"Loading…" forever on an entitlements error (`isPending` goes `false` on
error too); `SessionsCard`'s `Array.isArray` guard existed only to paper
over an incomplete test mock; the hardcoded-colour guard's first run found
a third offender (`StoreCard.tsx`) the manual survey missed; Task 17 found
two real e2e races, `beforeAll` runs per *worker* not per *file*
(fullyParallel let concurrent `seedAdmin()` calls double-post), and
`POST /login` is rate-limited 10/min per source IP (nine independent UI
sign-ins blew through it; fixed by signing in once and sharing the session
cookie).

**Known gaps, stated plainly:**
- **No real Proxmox node.** The journey runs against `FakePVE` +
  `FakeSSHConnection`, proving the product's own logic and UI, not hardware
  behaviour, and this phase is itself the evidence for why that gap
  matters: the journey's first real run found both production bugs above,
  each of which three prior phases' fake-backed DoDs had passed straight
  through
- **Computed-style assertions are not visual review.** "Ugly but correct"
  passes `light-theme.spec.ts` without complaint. **The light theme has not
  been seen by a human on this branch**
- **Environment quirks worked around, not fixed upstream**: this box's
  Chromium reports the deprecated tz alias `Asia/Calcutta`, which its
  minimal tzdata can't resolve (the journey overwrites it with `UTC`); React
  Query's global 15s `staleTime` can serve a stale cache against fresh
  backend state (the journey forces a reload rather than trusting it)
- **22 other `except ProxmoxError` sites** across `api/{consoles,backups,
  network,storage,vms,apps}.py` still format `str(e)` into an opaque
  502/409, now inconsistent with the `kind` taxonomy Task 1 gave
  `hosts.py`. Out of this phase's scope; counted directly (the plan's own
  survey estimated 24)
- **F1 was the last item Phase 8 recorded as open**: now closed by Task 9

**Verification:**
- `dod_verify_phase9b.py` (throwaway, not committed; `backend/.gitignore`
  carries `dod_verify_phase*.py`; the repo-root `.gitignore` does not, the
  pattern is backend-local): all four checks OK, exit 0, run twice,
  byte-identical both times
- Backend: **827 passed, 2 skipped, 4 deselected**; `pytest tests/ -q -m
  "not pve_integration and not e2e"` (baseline entering the phase: 810)
- Frontend: **268 passed across 43 files**, `npx vitest run
  --no-file-parallelism` (baseline 205 across 37); build clean; lint exit 0,
  30 warnings, 0 errors, pre-existing warning classes only
- Frontend e2e: **11 passed** (baseline 1), `npx playwright test`: smoke +
  the stranger journey + 9 light-theme pages, all real Chromium
- Migrations: `alembic heads` = **`01f962e7a491`**, **one migration this
  phase** (`ssh_verified_at` on `host_credentials`, Task 2), unlike 9a which
  shipped zero
- Commit range: `a7bbf3d..fa4c795` (design spec through the last
  implementation commit)

### 2026-08-06T20:20:00+05:30: Phase 9c, execute-plan completed

Goal, verbatim from the plan: *"Build a documentation site and a marketing
site for Proxploy from the material the project already has, fix the three
defects that would make them publish falsehoods, and deploy neither."* 17
tasks across three repos, full details in
`docs/notes/phase-9c-web-and-docs.md`.

**What shipped, per subsystem:**
- **`proxploy-app` fixes (Tasks 1-3), landed before any docs content:**
  `FastAPI(version=__version__)` so the OpenAPI schema reports `1.0.0`
  instead of FastAPI's `0.1.0` default; `backend/scripts/
  export_openapi.py` writes the schema to a file as a pure function of the
  app (inlines `make_app`'s body rather than importing `tests.support`,
  because `packaging/build_release.sh` excludes `tests/` from the release
  tarball but not `scripts/`); `install.sh` fixed so the bare `curl -fsSL
  https://proxploy.com/install.sh | bash` actually works, release public
  key compiled in, `--channel`/`--version` defaulted (the latter read off
  the fetched `manifest.json`), `--dry-parse` added so the defaulting is
  testable without root or network
- **`proxploy-docs`** (new repo, no remote): Astro 6 + Starlight, `layerr-
  docs`' content test suite (frontmatter/links/build, plus a rewritten
  content-consistency check), install/getting-started/trust/15 feature
  guides, and an OpenAPI-generated API reference; 49 pages, 199 tests
- **`proxploy-web`** (new repo, no remote): single-package Vite + React +
  Tailwind, Proxploy's own tokens, no Replit scaffolding, real paths only
  (no hash anchors), prerendered to 6 static routes, folderr-web-style
  nginx image

**Findings that mattered:**
- **The advertised one-liner did not work.** `install.sh` hard-required
  `--channel`/`--version`/`--pubkey` with no defaults, so the exact command
  in its own header, and the one doc 10's DoD is phrased around, died on
  `--channel is required`. Every 9a harness passed explicit flags, so the
  form every real user would run was the one form never executed. **Third
  instance this phase-group of tested path ≠ advertised path**, the other
  two, both from 9b, were SSH handed a URL where asyncssh needs a hostname,
  and `Host.node_name` never being written by the real onboarding path.
- **The OpenAPI schema reported `0.1.0`** while `__version__` was `1.0.0`, 
  would have contradicted the product on the reference's first page. Now
  confirmed `1.0.0` end to end.
- **`starlight-openapi` was evaluated and rejected on evidence.** The
  current release doesn't support this repo's pinned Starlight/Astro; an
  older release does, but generates ~130 virtual routes that break the
  page-count invariant and bypass the content test suite for the whole
  reference section, plus pulls a high-severity dependency chain. Fell back
  to a real-`.md`-file generator instead, covered by the same tests as
  every other page. `layerr-docs`, the template for the whole site, has no
  OpenAPI plugin at all, new ground, not a copied pattern.
- **A `# ponytail:` code comment leaks into the public API docs** via a
  route docstring (`backend/proxploy/api/network.py:159`,
  `GET /network/bridges`), visible today at `/api/docs`. The reference
  generator now escapes it so it doesn't render as a markdown heading, but
  the comment itself is still in the docstring, recorded as an open
  follow-up, not fixed here.
- **99 unique paths, not 127 routes**: `openapi()["paths"]` is keyed by
  path, so multiple methods on one path collapse to one key. The real
  count: 99 paths, 129 operations, measured directly.
- Two judgement calls, both stated in their commits: **`/screenshots`
  omitted entirely** (no browser here, a placeholder is worse than no
  route) and **the refund policy omitted** (no purchase path exists
  anywhere in the product, so there's nothing for a policy to describe).

**Known gaps, stated plainly:**
- **Nothing is deployed and no page has been seen by a human.** No browser
  in this environment; passing builds and link tests are not visual review.
- **The documented install path is unreachable end to end**: the release
  channel is unpublished and the repo is private, so nothing exists at the
  advertised URL yet.
- **The feature guides are assembled from phase notes, not from using the
  product against real hardware**, and 9b is direct evidence that gap
  hides real defects (its journey harness's first real run found two
  production bugs three prior phases' fake-backed DoDs had missed).
- **`proxploy-web` and `proxploy-docs` have no git remote**: both exist
  only on this machine.
- **Doc 11's §6 amendment records a contradiction, not a resolution.** The
  repository went private 2026-08-06, an owner decision outside this
  phase's scope; §6's source-available framing was left as originally
  written (per the doc's own rule against silently rewriting history), and
  the amendment records that its premise no longer matches the product.
  Which side resolves it, amend §6, or make the repo public; is owned by
  Aspyre Labs.

**Verification:**
- Backend: **829 passed, 1 failed, 2 skipped, 4 deselected**; 
  `pytest tests/ -q -m "not pve_integration and not e2e"` (baseline
  entering the phase: 827); the one failure,
  `test_backups_sync.py::test_concurrent_stale_reads_enqueue_only_one_sync`,
  is a known timing/thread-race flake under concurrent full-suite load
  (also seen in Phase 6/9b), passed 3/3 in isolation, re-run directly in
  this session
- `proxploy-docs`: **199 passed** (4 test files), `npm test`; **49 pages**
  built, Pagefind index built; `npm run build`
- `proxploy-web`: **6 routes prerendered** (`/`, `/features`, `/install`,
  `/about`, `/privacy-policy`, `/terms-of-service`); `npm run build`;
  typecheck clean, `npm run typecheck`
- Migrations: `alembic heads` = **`01f962e7a491`**, unchanged; zero
  migrations this phase
- Commit ranges: `proxploy-app` `8e67985..94a4326` (5 commits: `7ddde31`,
  `f8679f2`, `92d86db`, `064a5b2`, `94a4326`; this task's own doc/buildlog
  commit follows); `proxploy-docs` `a2af925..987a6c7` (full history, 10
  commits); `proxploy-web` `6b3608c..3b987cd` (full history, 5 commits)

### 2026-08-06T23:47:23+05:30: Phase 9d, execute-plan completed

Goal, verbatim from the plan: *"Make the licensing service ready to deploy
Postgres, rate limits, a real license-key format, install binding that
survives a reinstall, a health check that checks something, structured
logs, and a rotation runbook; without deploying it."* 9 tasks, 8 in
`proxploy-api`, 1 (Task 8) in `proxploy-app`, full details in
`docs/notes/phase-9d-api-hardening.md`.

**This closes Phase 9 in full**: 9a (install/update), 9b (onboarding
polish), 9c (docs + marketing sites), 9d (this). All four sub-phases are
now shipped and committed to `main` in their respective repos.

**What shipped, per subsystem (all in `proxploy-api` unless noted):**
- **Postgres replaces SQLite.** `db_url`/`make_engine` point at Postgres
  unconditionally; `tests/conftest.py` starts a throwaway `postgres:16`
  container per session (or reuses `PROXPLOY_API_TEST_DSN` in CI), this
  box has no Postgres binaries at all, so skip-when-absent would have
  proven nothing
- **A real license-key format.** `PPL-XXXXX-XXXXX-XXXXX-XXXXX-XXXXX`,
  Crockford Base32, 120-bit payload plus a mod-37 check symbol, validated
  in `canonical()` before any database lookup; no dual-accept path for the
  old 64-bit format
- **`install_id` binding on `refresh`/`revoke`**, and a rebind path on
  `activate`: a mismatched install gets 403 without any mutation; a
  reactivation from a *new* `install_id` now rebinds cleanly (200, fresh
  credential) instead of the old 409
- **Rate limiting**: `proxploy-app`'s `slowapi` idiom, `activate` at
  10/minute (the only guessable surface), `refresh`/`revoke` at 20/minute,
  `/v1/health` unlimited
- **Structured JSON logging**, from a zero-logging baseline; secrets never
  appear, a SHA-256 prefix (`handle()`) is used where correlation is
  genuinely needed
- **A health check that checks something**: `/v1/health` now runs
  `SELECT 1` and checks the signing key independently, 503s on either
  failure; the startup path that used to crash on a missing signing key
  now catches it and reports through health instead
- **Key rotation code + runbook**: `gen_signing_key.py` refuses to clobber
  an existing key without `--force`; `docs/runbooks/
  rotating-the-signing-key.md` documents the two-step sequence the
  bundled-trust-set design requires, plus the inverted emergency case
- **Two `proxploy-app` gaps (Task 8)**: `LicenseClient.revoke()` added,
  `refresh()` now sends `install_id` (using an install identity
  `proxploy-app` already had, `entitlements.py::set_license`'s persisted
  `AppSetting("license.install_id")`); the never-imported
  `signing.py::load_private_pem` helper deleted

**Findings that mattered:**
- **All four endpoints had zero authentication when this phase started,
  and still do, by design.** A shared secret would have to live in
  `proxploy-app`, the repo that goes public, so it would be extractable
  with one `grep`; rate limits, key entropy and install binding are the
  actual defence
- **License keys were ~64 bits with unlimited guesses**, no rate limiting
  anywhere, now 120 bits, checked before any lookup touches the database
- **`refresh`/`revoke` had no install binding at all**: possession of a
  credential was the whole check
- **`revoke` had no status filter**, so a revoked licence could be revoked
  again, inconsistent with `refresh`, now fixed to match
- **There was no logging whatsoever**: zero hits for `logging` in the
  package before this phase
- **`/v1/health` could only ever detect a dead process**, and **a missing
  signing key crashed startup** with an uncaught `FileNotFoundError`, 
  both fixed together, since the health check is what makes the crash fix
  debuggable rather than just quieter
- **Re-activating from a new `install_id` returned 409**: every reinstall,
  CT rebuild or restore was a support ticket
- **`test_unknown_license_404` was testing a malformed key**, not an
  unknown one, the 404 path was never actually exercised until this phase
  split the test in two
- **Found during execution:** `slowapi`'s `Limiter` is a module-level
  singleton, so its counters leaked across tests until `limiter.reset()`
  was added to the `client` fixture (same fix `proxploy-app` already
  needed); `RateLimitExceeded` subclasses `HTTPException`, so no custom
  429 handler was needed here, for a simpler reason than the identical
  pattern needed one to be checked in `proxploy-app`; two bugs in the
  plan's own draft tests were caught and fixed by implementers (a
  `str.replace` that stripped the prefix's dash, and a confusables test
  that could silently `pytest.skip()` instead of running)

**Known gaps, stated plainly:**
- **The service has still never run outside tests.** No Dockerfile, no
  host, no deployment; rate limits, health checks and logs are verified
  by tests and this phase's DoD script, not by a deployed instance under
  real traffic
- **Rotation is proven mechanically, never operationally**: the runbook's
  two-step sequence has never been executed against a real install,
  because there are no real installs yet
- **Everything here protects a system whose protections are currently
  moot**, `tiers.yaml` keeps `all_entitled: true`, so a stolen token
  grants exactly what `DEFAULT_FEATURES` already grants unconditionally.
  It all becomes live the day tiers arm
- **No deployment, Dockerfile, monitoring backend, or error reporting**; 
  deliberately out of scope, same as every phase before it

**Verification:**
- `proxploy-api`: **35 passed, 0 skipped**; `.venv/bin/python -m pytest
  tests/ -q` (baseline entering the phase: 4)
- `proxploy-app` backend: **831 passed, 2 skipped, 4 deselected**; 
  `.venv/bin/python -m pytest tests/ -q -m "not pve_integration and not
  e2e"`
- `dod_verify_phase9d.py` (throwaway, not committed; `proxploy-api/
  .gitignore` gained a `dod_verify_*` line this phase, it had none before):
  all four checks OK (key format, install binding, rate limiting,
  Postgres-not-SQLite), exit 0, run twice, identical output both times
- Commit ranges: `proxploy-api` `5b933d9..b2253e1` (8 commits; this task's
  own `.gitignore` commit follows); `proxploy-app` `e574b88..4374251`
  (4 commits; this task's own notes/buildlog commit follows)

**Phase 9, closed.** 9a made install/update work end to end; 9b polished
onboarding and proved the stranger journey through a real browser; 9c
built the docs and marketing sites without deploying them; 9d hardened the
licensing API for a deployment that, per every phase's own residual-gaps
section, still hasn't happened. What Phase 9 has not done, cumulatively:
run anything outside a test process, seen any page with a human eye, or
exercised any of this against real Proxmox hardware. Those are the honest
boundaries of what "9-phase SDD build, done" means here.

### 2026-08-08T14:59:23+05:30: Phase 9d addendum, observability + error reporting

Closes the last two open items on PXP-13, which the 9d plan had ruled out by
its own global constraints and the tracker then listed as "genuinely still to
build". Not a re-run of the plan; follow-up against the tracker item.

**What shipped:**
- **Error reporting, both services.** `sentry-sdk[fastapi]`, one guarded
  `sentry_sdk.init()` each, DSN empty by default:
  `PROXPLOY_API_SENTRY_DSN` / `PROXPLOY_SENTRY_DSN`. Init runs before the app
  is built so lifespan startup failures still report. `environment` from
  `PROXPLOY_ENV`, `release` from the package version. `send_default_pii=False`
  on both, set in code rather than inherited: these processes hold licence
  keys, Proxmox tokens, SSH keys and LAN topology, and none of that needs to
  travel with a stack trace
- **The empty default is load-bearing twice.** In `proxploy-api` it keeps the
  suite's deliberate 500s out of the tracker. In `proxploy-app` it is a
  consent boundary: that app runs on someone else's hardware, so the installer
  does not set the DSN and never should
- **`platform.error_report` stays decorative**, now with a comment saying so.
  Gating crash reporting on an entitlement would let a billing state change
  what leaves an operator's network
- **Monitoring via GlitchTip** (`errors.aspyrelabs.com`), nothing new
  deployed: projects `proxploy-api`/`proxploy-app`, a 60s GET monitor on
  `https://api.proxploy.dev/v1/health` expecting 200, email alerts on both
  projects with downtime on the API. Prometheus and a `/metrics` endpoint
  skipped rather than deferred, one service with a health check and an uptime
  monitor has nothing left to scrape
- **`proxploy-docs` trust page** gained a "crash reporting is off, and stays
  off unless you turn it on" section, naming exactly what is and isn't sent

**Fixed while verifying, not planned:**
- `test_e2e_entitlement.py`, the only test running a real `proxploy-api`
  process and so the only guard on the cross-service contract, had been
  failing since Task 1: a `--out` flag `gen_signing_key.py` no longer accepts,
  the renamed `PROXPLOY_API_SIGNING_KEY_FILE`, and a SQLite URL after
  `f134e77` removed the fallback. Now generates the keypair in-process and
  starts a throwaway `postgres:16`, same reasoning as Task 1's fixture
- Bare `pytest` in `backend/` died during collection on mutmut's gitignored
  `mutants/` tree copy (two `tests.conftest`). `testpaths = ["tests"]`
- The audit's "proxploy-api CI license check is broken" was already fixed in
  `a32624d`; the exact CI command exits 0, and `sentry-sdk` (MIT) clears it

**Verification:**
- `proxploy-api`: **66 passed**
- `proxploy-app` backend: **839 passed, 5 skipped, 0 failed** (from 838 passed
  + 1 failed; the +1 is the repaired e2e test)
- `proxploy-docs`: **199 passed**
- Live events through each service's real `create_app()` reached GlitchTip and
  filed as `PROXPLOY-API-1` / `PROXPLOY-APP-1`, both resolved after
- Uptime monitor returned `isUp: true` on its first check

**Correction to the Phase 9 closing note above:** it says nothing had run
outside a test process. That is no longer true, `api.proxploy.dev` and
`docs.proxploy.dev` are deployed and serving, and `/v1/health` returns 200,
which means the database and signing key both loaded in a real container.
Still true: no page has been checked against real Proxmox hardware, which
remains the gate (PXP-18).

### 2026-08-12T15:50:00+05:30: host page redesign, chrome icons, and a correction to PXP-18

Two branches merged to `main` (`d5d3df0..5991635`), and a standing claim in
this log corrected.

**What shipped:**
- **The host page is two columns.** `HostFacts`' flat 17-row strip became
  `NodeIdentityRail`: four labelled groups, and no heading at all for a group
  whose rows the node refused to report — without that rule, a refused
  `/status` would have left a "Processor" label over nothing, making the
  degraded case worse than the strip it replaced. The `AppCard` grid and the
  bare VM table became one `GuestList`, unifying *upward*: VMs gained the CPU
  bar, lifecycle controls and console that apps already had. A non-entry node
  now names the node that holds its metrics instead of silently rendering less
- **The chrome has real icons.** Heroicons (24/outline at 18px) on the ten nav
  items and on search/activity/theme, which were emoji — glyphs that render
  per-OS, ignore `currentColor` so they cannot follow the theme, and carry no
  accessible name. The header became the shell's first row at full width, so
  the mark sits in the window's corner rather than inside the pane that
  collapses; the sidebar collapses to a 64px rail with Radix tooltips and
  remembers the choice. Two dependencies bought deliberately:
  `@heroicons/react`, `@radix-ui/react-tooltip`
- **Verification:** frontend 65 files / 470 passed / 5 skipped; backend 985
  passed with `-m "not pve_integration and not e2e"`; `tsc -b` clean; oxlint 45

**Two defects the per-task reviews could not see, both caught by whole-branch
review:**
- The merged guest list was gated on the apps query alone, so a host with VMs
  and no adopted apps showed "Guests on this host (1)" above "No guests on
  this node" with the VM nowhere. No page-level test had ever rendered
  `GuestList` inside `NodeOverview` — the seam had zero coverage in either
  direction, which is exactly why it survived four task reviews
- `HealthFooter` was never made collapse-aware; in a 64px rail its two lines
  wrapped to ~8 fragments and painted out over the page. Invisible because
  every sidebar test mocked that component to `null`

**Correction to PXP-18.** The Phase 9d addendum above says the remaining gate
is that nothing "has been checked against real Proxmox hardware". That stopped
being true on **2026-08-10**, when the `pve_integration` suites ran against a
real node from the Linux workspace. The evidence is in `tests/livepve.py`'s own
docstring, which records what was learned there: "a host that looks idle can
hold real data. The PBS datastore used for these tests held 121 archives
belonging to six other guests." Nine live tests cover the app lifecycle, VM
create/start/console/snapshot/clone/delete, console tickets over a real WS,
ISO upload, and backup sync/restore/prune against a real datastore.

**The residual gap is one endpoint, not the product.** `apply_network`
(`proxploy/api/network.py:350`, `PUT /nodes/{node}/network` → `ifreload -a`)
has never run against real hardware. It is covered by 28 fake-node tests
across `test_network_api.py` and `test_network_hostconfig.py` for request
shape and the typed node-name confirmation, but the reload itself has not
happened on a real node. Note that
`test_network_apply_is_gated_behind_an_explicit_opt_in` **skips
unconditionally even when `PROXPLOY_TEST_PVE_ALLOW_NETWORK_APPLY=1` is set** —
its second `pytest.skip` is not behind a condition. It exists to make the gate
visible in the run, not to exercise the apply. Setting that variable therefore
proves nothing; closing this gap means a supervised manual apply on a node
with confirmed out-of-band access (IPMI or a physical console), because a
wrong bridge write cuts the node off with no in-band undo.

### 2026-08-12T22:30:00+05:30: notifications rebuilt three times, icons reversed twice, host power onto the job engine

44 commits on `main` since the last entry (`6b80b60..7142831`), one long day.
Three small branches merged (`notifications-toasts`, `animated-theme-toggle`,
`bell-popover`); everything else landed as direct commits: icons, loading
indicators, migrate progress, a host actions menu, an em dash sweep held back
from the earlier one, and the tray that finally replaced every notification
surface above it at once.

**Notifications were rebuilt three times**, each time in response to what the
user actually saw next.
1. Plain `sonner` toasts (`toast.success`/`toast.error`) became ReUI-style
   severity cards (`notification-card.tsx`, vendored by hand: no shadcn CLI,
   no `cva`, colors mapped onto this app's own `--blue`/`--green`/`--amber`/
   `--red` tokens). The bell still opened a job-list popover underneath.
2. The bell popover was made to show the same cards instead of a list, and
   still shipped as a list once more before it stuck (`0de311d`), because the
   popover kept its own bespoke row markup; once fixed, the cards sat inside
   a bordered panel titled "Activity" (`cdb2fc9`), which read as a list
   regardless of what was rendered inside it.
3. Both surfaces collapsed into one tray (`d3ff15c`): a client-side store
   (`lib/notificationStore.ts`) that both `notify.tsx` and `LiveProvider`
   push into, merged with `GET /jobs` in `BellPopover` so job history still
   survives a reload, deduped by job id (`lib/notificationMerge.ts`, tested
   directly, since a duplicate delivered once over SSE and again on the next
   `/jobs` poll is exactly the failure most likely to happen). `sonner`'s
   `<Toaster>` and `ClearAllToasts` left `AppShell` entirely; "Clear all"
   survives as a tray affordance instead.

The badge changed meaning three times to match: running jobs alone (before
this arc), then running jobs plus an unread count of the store (`d3ff15c`),
then, because that still didn't describe what the tray held, the tray's own
length (`11a45ef`), red instead of amber, hidden at zero, capped at 99+.

Smaller fixes along the way: cancel came back on the activity feed rows after
the drawer's deletion had taken it as uncaught dead code (`174d257`); a job's
transcript became reachable again through a "View log" action on each card,
restoring what the drawer's removal had quietly cut, with its own test
because "this gap was lost once already and shipped" (`837ed49`); the card
count that follows window height had to be taught to grow back, not just
shrink, when the window did (`b1ca75b`); and the cards' position relative to
the bell needed two separate fixes, one for being pinned to the wrong
trigger's edge (`758070d`) and one for `alignOffset`'s sign running the
opposite way, pushing the cards further into the window instead of toward
its edge (`1d30958`).

**Two live regressions shipped and were then fixed.** The tray landed with no
`<Toaster>` mounted anywhere, so the seven remaining `toast.success`/
`toast.error` calls still living in `HostPowerDialog.tsx`, `HostEditDialog.tsx`
and `routes/hosts.tsx` (held back because another agent was mid-edit on those
files) rendered nothing at all; saving a host edit gave silence (`a173d29`
fixed it, routing all seven through `notify`). And the Hardware tab's pending
branch was a bare `return null`, so for however long the real fetch took
against a live node the tab showed a blank pane, which reads as broken rather
than slow (`7142831`: a card-shaped skeleton under the existing loading veil
instead).

**The theme toggle** became MagicUI's `animated-theme-toggler`, vendored by
hand rather than pulled through the shadcn CLI, because this repo has no
`components.json`, no `cn`, no `@/` alias, and `shadcn init` would have
rewritten `tokens.css`. Adapted to drive `data-theme` on `<html>` through
`lib/theme.ts` rather than a `dark` class next-themes would own (there is no
Tailwind `dark:` variant here), Heroicons instead of lucide, and a
`prefers-reduced-motion` escape hatch upstream does not have. Also closed a
gap in what MagicUI itself ships: its component sets a
`--magicui-theme-vt-clip-from` custom property with a comment claiming it
pins the wipe's starting clip so Firefox doesn't flash the new theme
unclipped for a frame, but no stylesheet upstream ships, registry JSON or the
compiled docs site, actually reads that property. The consuming rule was
added here, on this app's own tokens.

**Icons went through five states in one day.** Heroicons (already the app's
icon set from the earlier chrome pass) picked up two lucide-react imports for
the notification card's corner controls (`8dddae3`), then lost them back to
Heroicons once two icons turned out not to be worth a second icon dependency
(`8e1310e`). Then the whole app moved off Heroicons entirely, to a
self-hosted, build-time-subset Material Symbols font (`f774d29`): Heroicons'
~300 icons had become limiting, but full Material Symbols is one shared GSUB
decision tree across roughly 3,600 ligatures, so subsetting by ligature name
barely shrinks it once a modest vocabulary of real English words is in play;
subsetting by Private Use Area codepoint instead, no GSUB involved, got the
23 icons this app uses down to 2.4KB. It was kept self-hosted specifically on
the assumption that an install might have no internet at all. That assumption
was then retired (`707a7ef`): the user pointed out that the app store already
downloads container templates over the internet, so air-gapped was never a
real constraint on this install, and the self-hosting, the build-time
subsetting, and a hand-maintained codepoint table were complexity bought for
a constraint that never applied. Icons now load from `fonts.googleapis.com`,
scoped to exactly the names in use via the CDN's own `icon_names` parameter,
injected by a small Vite plugin. A new `reveal-icons-when-ready.ts` keeps
every icon invisible until the CSS Font Loading API confirms the font
settled, since Google's CSS2 response carries no `font-display` the way the
old subset build did, and a slow or blocked CDN should never flash a literal
icon name where a glyph belongs.

**Loading indicators** got a shared ring, wired to whatever real signal
exists and nothing pretending to have one it doesn't. The determinate half
(`168330d`) covered the three places with a genuine completion figure: app
install/update, the backup sweep (the only per-host granular progress the
backend had, polled from the existing stale banner since `GET /backups`
never returns a job id to follow directly), and the bell popover's
running-job rows, which used to render `progress_pct` as bare text instead
of the ring. The indeterminate half (`a405b69`) covered six more spots that
had no honest completion signal and were previously either silent or showed
static "Loading..." text with no `role=status`. A card-level blur overlay
(`35199b8`, `CardLoadingOverlay`, vendored from ReUI's paid-tier spinner
example with a Heroicons arrow standing in for the licensed primitive) went
on `ApiKeysCard`, `TeamsCard`, `TotpCard` and two settings sections,
deliberately keyed off `query.isPending` rather than `isFetching`, so a
background poll or a post-mutation refetch never flashes the veil over
content that's already there.

**A wrong call from that same pass was corrected minutes later.**
`MigrateDialog` had been wired indeterminate on the premise that nothing in
the migrate path reports real progress. That premise was wrong: the SFTP
transfer hop already reports byte-level progress, the most granular signal
anywhere in the product, and every job row already carries whatever
`ctx.progress()` last wrote. `9199710` gave it back its determinate ring,
seeded from the job row rather than assumed zero, kept live over the same
SSE connection `JobLog` already had.

**Migrate progress was also climbing to 100 and dropping back** (`356f240`),
a separate defect from the ring-type mistake above: a cross-host migration
chains several PVE tasks (stop, vzdump, the SFTP hop, restore, start), and
`await_task`'s progress bracket defaults to (10, 100) for a single task, so
every phase of a migration was reporting as though it were the whole job.
vzdump finishing would hit 100 for a migration maybe 40% done, then the SFTP
hop's honest byte climb would resume from ~10, reading as progress running
backwards once the frontend started rendering it as a ring instead of a
spinner. Fixed by giving each phase its own band within 0-100, plus a
monotonic clamp added to `JobContext.progress` as a safety net for a future
handler bug, not as the fix itself.

**Host actions.** An Edit/Reboot/Power off menu on the host page (`ab41f8f`),
backed by new endpoints: `PATCH /hosts/{id}` gained optional `name`/`address`,
and a new `POST /hosts/{id}/nodes/{node}/power` calls Proxmox's own
node-status endpoint. Reboot and power off both go through the same typed
name-confirmation dialog the remove flow already uses, and the self-guard
that stops Proxploy from powering off its own node was extended from
`app`/`vm` targets to host+node, since a `Host` row can be a whole cluster
and only the recorded entry node can ever be the machine Proxploy runs on.
`host.power` was set to the `owner` permission tier, matching
`host.remove`/`host.credentials`, flagged in its own commit as a judgment
call with no doc precedent behind it; an argument exists for `admin` instead,
since a reboot destroys no data the way a remove does. It landed synchronous
at first (fire the command, hand back a bare UPID) because the job engine
files were mid-edit by a concurrent agent, then moved onto the job engine
once that cleared (`716e664`), enqueuing `host.reboot`/`host.shutdown` so
both actions leave a transcript in the bell popover like every other
destructive action, instead of a toast with no way to follow what happened
next. No progress percentage is reported for either: the honest signal
available is "Proxmox accepted the command," not "the node finished
rebooting," and a percentage would have claimed certainty the job doesn't
have. If Proxploy runs on the node being powered off, the process, job
engine included, disappears mid-poll; nothing special-cases this, the
existing orphan sweep marks the row interrupted at next boot, same as any
other job an ungraceful restart catches mid-flight.

**Also landed, smaller:** every remaining plain-text toast call site (59
across 26 files, outside the three held back for the tray work) now goes
through one `notify.tsx` helper instead of calling `sonner` directly
(`07ce817`); a host's recorded PVE version now refreshes on an in-place
Proxmox upgrade instead of waiting for a manual Test click, and the identity
rail's Load/IO delay values poll every 30 seconds instead of freezing at
page load (`f48631d`); the topbar stopped overrunning a 375px phone, mostly
the tier pill, by dropping the "ALL FEATURES" qualifier below the `sm`
breakpoint (`54ec9af`); and the em dashes remaining in `hosts.tsx` and
`HostForm.tsx`, held back from the earlier sweep because they were being
actively edited, are gone (`a57f0ca`, following `f472511`'s sweep of 60 em
dashes and 2 en dashes across 24 other files).

**Verification, two things that both matter, not one deficiency.**

What the machine checked: frontend, 84 test files, 620 passed, 5 skipped;
`npx tsc -b` clean; `npx oxlint`, 44 warnings, 0 errors, all in categories
(fast-refresh export shape, hook dependency arrays) that predate this range.
Backend: 1024 passed, 2 skipped, 10 deselected, `pytest tests/ -q -m "not
pve_integration and not e2e"`. That is real coverage, and it has a real edge:
jsdom does not evaluate CSS, so the theme wipe, the card veil, and the tray's
arrival behavior are invisible to the suite by construction, and the
`run-proxploy` driver has no login step, so every one of these authenticated
surfaces is out of its reach too.

What the human review caught, which the suite was structurally blind to: the
bell popover rendering a job list when cards had been asked for, twice; the
notification cards sitting inside a bordered "Activity" panel that still
read as a list regardless of what was in it; the badge counting running jobs
plus an unread tally instead of the tray's own contents, so it sat at zero
while the tray plainly held something; the Hardware tab rendering nothing at
all while it loaded; Clear All not surviving a reload because dismissal
lived only in React state; the popover's `alignOffset` pushing the cards
further into the window instead of out toward its edge; and the icon
self-hosting and build-time subsetting solving a constraint, air-gapped
installs, that does not exist for this product. None of those are things a
passing test suite would have shown. The user ran the dev session alongside
this work all day and reviewed every change as it landed, and that loop
caught a class of defect the suite cannot see, several times in one day.

**Known gaps, stated plainly:**
- The tray's arrival behavior (`NotificationSurface`, the brief
  under-the-bell appearance before a new item settles into the tray) has not
  been seen in a browser by anything except the user.
- The badge has a roughly 30-second double-count window: a job that just
  turned terminal stays in the stale `running` count until its next poll
  while it is already counted fresh in the unread store. Self-corrects, only
  visible while the tray is closed.
- Action notifications and alerts do not survive a page reload, by design:
  there is nothing server-side to reload them from. Job history still does,
  through `GET /jobs`.
- `apply_network`'s `ifreload -a` (`PUT /nodes/{node}/network`) still has
  never run against real hardware, unchanged from the last entry's note; 28
  fake-node tests cover the request shape, not the reload itself.
- `host.power`'s `owner` permission tier is a judgment call with no doc
  precedent, flagged in its own commit, not resolved here.
- `migrate.py` keeps its `cluster_resources()` reads on the monitoring
  capability rather than lifecycle or backup, reasoned from PVE's documented
  ACL filtering but never checked on hardware. Verify a monitoring-only token
  can still enumerate what migration needs, on a real cluster.
- Lifecycle now grants `Sys.Modify`, `Datastore.Allocate` and
  `Datastore.AllocateSpace`. None of those paths (bridge apply, storage pool
  attach and edit, ISO upload, stray volume delete) has run against real
  hardware under a lifecycle-scoped token.
