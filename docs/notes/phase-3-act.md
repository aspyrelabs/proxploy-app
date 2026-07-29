# Phase 3 (Act) — verification notes

## What shipped, per subsystem

**JobBackend (in-process asyncio runner)** — `backend/proxploy/jobs/backend.py`,
`backend/proxploy/jobs/__init__.py`. `app.state.jobs`, built in `main.py`'s
lifespan alongside the Poller. `enqueue()` writes the `jobs` row in the
caller's (threadpool) session, then hops to the loop via
`call_soon_threadsafe` to spawn one `asyncio.Task` per job behind a
`Semaphore(4)`, so `queued` is a real, observable status. Handlers are
`async def h(ctx, params) -> dict` registered by kind in `HANDLERS`; `ctx.log()`
/ `ctx.progress()` write a `job_events` row (or the `jobs.progress_pct`
column) to the DB *before* fanning out to SSE subscribers — the DB is the
transcript, SSE is a follower. `sweep_orphans()` runs once at boot and flips
every `queued`/`running` row to `interrupted` (never resumed). `stop()`
cancels every in-flight task at shutdown.

**Jobs REST + per-job SSE** — `backend/proxploy/api/jobs.py`. `GET /jobs`,
`GET /jobs/{id}`, `GET /jobs/{id}/events` (DB backlog), `GET
/jobs/{id}/events/stream` (SSE: `line`/`progress`/`status` frames per doc 05
§Streaming 1, `line` carries `id:` as the `Last-Event-ID` resume cursor),
`POST /jobs/{id}/cancel`.

**Lifecycle handlers + guardrail** — `backend/proxploy/services/lifecycle.py`
(`app.*`/`vm.*` handlers over `ProxmoxClient.guest_action`/`task_status`/
`task_log`, verb-to-Proxmox-action map, `TASK_POLL_S`/`TASK_TIMEOUT_S`),
`backend/proxploy/services/selfguard.py` (`is_self()`, `DESTRUCTIVE` verb
set — doc 02 §9 / doc 08 §1). `backend/proxploy/services/proxmox.py` gained
`guest_action`, `task_status`, `task_log` (Task 1).

**Lifecycle routes** — `backend/proxploy/api/apps.py` (`POST
/apps/{id}/{action}`), `backend/proxploy/api/vms.py` (`POST
/vms/{id}/{action}`), sharing `enqueue_lifecycle()` for the guardrail-check +
enqueue + audit-write shape.

**Notifier + routing** — `backend/proxploy/services/notifier.py`
(`send_one` is the one Apprise call site; `kind_for` is an allowlist-only
scheme→label lookup, never echoes caller text; `channels_for`/`notify` fan a
terminal event out to every subscribed, enabled channel). `JobBackend._finish`
calls `_notify` → `_notify_async`, which runs `notifier.notify` in
`asyncio.to_thread` off the event loop, fire-and-forget, tracked in `_side`
so the task isn't GC'd mid-flight.

**Notification channels CRUD** — `backend/proxploy/api/notifications.py`:
list/create/patch/delete/test. The Apprise URL is write-only — encrypted via
`SecretStore` into `url_enc`, never returned by any endpoint, never audited,
never logged.

**Activity feed** — `backend/proxploy/api/cluster.py`, `GET
/cluster/activity`: merges `jobs` + `audit_events`, deduped by
`audit_events.job_id` so a lifecycle action doesn't appear twice, sorted
newest-first, `limit` honoured and capped.

**Frontend** — `frontend/src/api/jobs.ts` (types + hooks), `frontend/src/api/live.ts`
(`applyJob`: SSE `job` delta → cache patch + toast), `frontend/src/components/TerminalPanel.tsx`,
`JobLog.tsx`, `ActivityDrawer.tsx`, `ActivityFeed.tsx`, `LifecycleActions.tsx`,
`ConfirmSelfDialog.tsx`, `ChannelForm.tsx`; `Topbar.tsx` activity bell;
`AppShell.tsx` mounts `<Toaster>` + `<ActivityDrawer>`; dashboard
(`routes/cluster.tsx`) renders the real feed; `routes/settings.tsx` gained the
Notifications card.

## DoD verification map (doc 10 Phase 3)

DoD: *"start/stop/restart from Apps and VMs pages works end-to-end with
optimistic UI + reconciliation; a cancelled job stops cleanly; every action
appears in audit and the feed; a Telegram/ntfy channel receives a
job-failure notification."*

| Clause | Proving artifact | Verdict |
|---|---|---|
| start/stop/restart works end-to-end (backend half) | `dod_verify.py` (below): `POST /apps/{id}/start` → 202 → polled to `succeeded` via `GET /jobs/{id}` | PROVED |
| start/stop/restart works end-to-end (UI half: optimistic patch + reconciliation) | `frontend/src/tests/lifecycle.test.tsx` (`LifecycleActions` — action routing, running/stopped verb sets, self-target 409 → typed-confirm dialog + retry), `frontend/src/tests/jobs.test.ts` (`applyJob` — cache patch on `running`, invalidate + toast on terminal, dedupe on duplicate delivery) | PROVED BY TEST, NOT BY BROWSER — see "What was NOT verified" |
| a cancelled job stops cleanly | `dod_verify.py`: slow job (`FakePVE(running_ticks=10_000)`) cancelled mid-poll via `POST /jobs/{id}/cancel` → settles `canceled` with `finished_at` set; backend unit coverage in `tests/test_lifecycle_jobs.py::test_cancel_mid_poll_reports_the_proxmox_task_is_still_running` (asserts the Proxmox-side action already fired and is never claimed undone) and `test_job_backend.py`'s cancel-while-queued/cancel-while-running matrix | PROVED |
| every action appears in audit and the feed | `dod_verify.py`: audit row with matching `job_id` exists after `start`; `GET /cluster/activity` shows the job exactly once (dedup by `job_id`) | PROVED |
| a Telegram/ntfy channel receives a job-failure notification | `dod_verify.py`: channel registered with `events=["job.failed"]`, `notifier.send_one` monkeypatched to a recorder, forced failure via `FakePVE(task_exit="CT is locked")` → recorder saw exactly one send | PROVED |

### `dod_verify.py` — real output

Run against `tests.support.make_app` + `tests.fakes.pve.FakePVE`, from
`backend/` with the project venv. Script was written to the scratchpad
(not committed — throwaway per Task 14's brief).

```
--- Clause 1: start -> 202, settles succeeded, audit row, feed shows once ---
[PASS] POST /apps/{id}/start returns 202
  job id = 1, initial status = queued
[PASS] job settles to succeeded
[PASS] an audit row exists carrying this job id
  audit row(s): [('app.start', 1)]
[PASS] GET /cluster/activity shows the job exactly once
  activity rows matching job 1: [{'kind': 'job', 'id': 1, 'at': '2026-07-29T14:30:48.116979Z',
  'title': 'app.start', 'status': 'succeeded', 'target_type': 'app', 'target_id': 1,
  'actor': 'admin@example.com', 'job_id': 1, 'progress_pct': 100}]

--- Clause 2: cancel a slow job -> settles canceled, finished_at set ---
[PASS] POST /apps/{id}/stop (slow) returns 202
[PASS] POST /jobs/{id}/cancel returns 200
[PASS] cancelled job settles to canceled
[PASS] cancelled job has finished_at set
  final job row: {'id': 2, 'kind': 'app.stop', 'status': 'canceled', 'target_type': 'app',
  'target_id': 1, 'params': {'target_id': 1, 'action': 'stop'}, 'result': None,
  'error': 'canceled by user', 'progress_pct': 50, 'requested_by': 1, 'schedule_id': None,
  'started_at': '2026-07-29T14:30:48.344846Z', 'finished_at': '2026-07-29T14:30:48.456479Z',
  'created_at': '2026-07-29T14:30:48.338345Z'}

--- Clause 3: notification channel receives exactly one job.failed send ---
[PASS] channel registered (201)
[PASS] POST /apps/{id}/restart (forced failure) returns 202
[PASS] job settles to failed
[PASS] recorder saw exactly one send
  recorder calls: [('ntfy://ntfy.sh/proxploy-test', 'Proxploy: app.restart failed',
  'restart failed: CT is locked')]

RESULT: ALL DoD CLAUSES PROVED
```

## Gate numbers (real, captured this run)

| Gate | Command | Result |
|---|---|---|
| Backend tests | `pytest tests/ -q -m "not pve_integration and not e2e"` | **190 passed, 1 skipped, 2 deselected** |
| Executor isolation | `scripts/check_executor_isolation.py` | **OK** — no module outside `executor/` imports asyncssh/an SSH-key accessor (Phase 3 touches no SSH) |
| Backend license audit | `pip-licenses --partial-match --allow-only "..."` (doc 03 protocol) | **OK, exit 0** — no disallowed licenses |
| Frontend tests | `npm test` | **33 passed (11 files)** |
| Frontend build | `npm run build` | **clean** (`tsc -b` + vite build) |
| Frontend license audit | `license-checker-rseidelsohn --production --excludePackages "frontend@0.0.0" --onlyAllow "..."` | **OK, exit 0** (root `package.json` has no `license` field — pre-existing, expected, excluded by name) |

## Every endpoint added this phase

| Method + path | Role | Entitlement | Notes |
|---|---|---|---|
| `GET /api/v1/jobs` | viewer | `jobs.history` | list, filterable by `status`/`kind` |
| `GET /api/v1/jobs/{id}` | viewer | `jobs.history` | job detail row |
| `GET /api/v1/jobs/{id}/events` | viewer | `jobs.history` | DB backlog, `after`/`limit` |
| `GET /api/v1/jobs/{id}/events/stream` | viewer (checked inside the generator) | `jobs.stream` | SSE, `line`/`progress`/`status` frames |
| `POST /api/v1/jobs/{id}/cancel` | operator | *(ungated — you may always stop what you started)* | idempotent-safe via conditional UPDATE |
| `POST /api/v1/apps/{id}/{action}` | operator | `apps.lifecycle` | `action` ∈ `start,stop,restart,shutdown`; self-target guardrail |
| `POST /api/v1/vms/{id}/{action}` | operator | `vms.lifecycle` | `action` ∈ `start,stop,restart,shutdown,pause,resume` |
| `GET /api/v1/cluster/activity` | viewer | `cluster.activity_feed` | merged jobs+audit feed, `limit` |
| `GET /api/v1/notifications/channels` | admin | `notify.channels` | list (URL never returned) |
| `POST /api/v1/notifications/channels` | admin | `notify.channels` | create; audits `{name, kind}` only |
| `PATCH /api/v1/notifications/channels/{id}` | admin | `notify.channels` | partial update |
| `DELETE /api/v1/notifications/channels/{id}` | admin | `notify.channels` | 204 |
| `POST /api/v1/notifications/channels/{id}/test` | admin | `notify.channels` | test-send, stamps `last_notified_at` on success |

## Deviations from the plan (controller decisions during the build)

- **Lifecycle verbs are a superset of doc 05's paths.** Doc 05 lists `POST
  /apps/{id}/start|stop|restart` and `POST /vms/{id}/start|stop|restart|pause`;
  apps also accept `shutdown`, and VMs also accept `shutdown`/`resume`,
  covering doc 10 Phase 3's and doc 01 §2's fuller verb lists. No documented
  path was removed — every doc-05 path still exists and behaves as specified.
- **Jobs endpoints are entitlement-gated** (`jobs.history` on list/detail/
  events, `jobs.stream` on the SSE route) and `GET /cluster/activity` is
  gated on `cluster.activity_feed`, although doc 05's tables leave those
  entitlement columns blank. This is a deliberate superset — doc 01 §11
  defines both flags as real features, and an unchecked key can never be
  armed later. Behaviourally invisible today since all 81 flags resolve ON.
  `POST /jobs/{id}/cancel` was deliberately left ungated — you may always
  stop what you started.
- **`docs/05-api-surface.md` §Streaming 4 was AMENDED**: `target_type` was
  added to the documented `job` SSE event payload. The plan's frontend
  `applyJob` code read a `target_type` field the spec never promised;
  without it, job-driven cache invalidation only worked for the browser tab
  that started the job, with no path to correctness for Phase 7's
  scheduler-driven jobs (no initiating tab exists for those). Backend
  `_publish` now threads `target_type` through every call site (spawn,
  running, cancel, `JobFailed`, generic exception, success); `target_type=None`
  for system-originated jobs flows through as an explicit JSON `null`.
- **Job row and `job_events` writes happen inline on the event loop**, not in
  `asyncio.to_thread`. Each write is a small SQLite insert/update, and the
  cancellation path must persist its terminal row without an `await`
  (awaiting inside a cancelled task's `except` block is a re-cancellation
  hazard).
- **`GET /hosts/{id}/tasks` and `POST /hosts/{id}/sync` were deliberately NOT
  built.** Doc 10 Phase 3 names JobBackend, lifecycle, activity feed and
  notifications; those two doc-05 rows belong to host management and have no
  Phase 3 dependency. Left unbuilt rather than half-built.
- **The activity bell's running-job count uses a dedicated
  `['jobs', 'running-count']` query** rather than `useJobs({status: 'running'})`,
  because `useJobs` couples `enabled` to `refetchInterval` — the brief's
  original version would have left a permanent 10s `['jobs']` poll running on
  every page, violating doc 06 §(d)'s "polling is fallback, SSE is primary,
  and only while the drawer is open" rule.

## Known ceilings (`ponytail:` comments this phase, plus undocumented-but-real ones)

- `backend/proxploy/jobs/backend.py:26` — `MAX_CONCURRENT = 4` is a fixed
  `Semaphore`, not a settings knob. Upgrade path: a knob belongs with Phase
  7's scheduler UI, where a user would actually go looking for it.
- `backend/proxploy/jobs/backend.py:49` — job-row/`job_events` writes are
  inline on the event loop (tens-of-microseconds SQLite inserts). Upgrade
  path: Phase 4's multi-thousand-line install transcripts are the trigger to
  move line writes onto a batched writer thread.
- `backend/proxploy/services/lifecycle.py:35` — `TASK_TIMEOUT_S = 300.0` is
  one flat wall-clock ceiling for every lifecycle action. Upgrade path: a
  per-kind timeout table, worth building once a real workload proves one
  action needs longer.
- `channels_for()` (`backend/proxploy/services/notifier.py`) is O(all enabled
  channels) per terminal job — it loads every enabled row and filters
  "empty events means all" in Python rather than pushing the filter into
  SQL. Fine at the channel counts a self-hosted install will ever have;
  revisit if that assumption breaks.
- `JobBackend.stop()` does not drain `_side` — jobs cancelled at process
  shutdown (via `stop()`'s `task.cancel()` loop) lose their courtesy
  `job.canceled` notification, because the fire-and-forget notify task in
  `_side` is never awaited before the process exits. Acceptable: a
  notification about a shutdown-time cancellation competes with the process
  actually going down.

## Doc-accuracy note (fold into a future doc pass, not introduced this phase)

Doc 05's `job` SSE event example bundles `status` and `progress_pct` in one
payload, but the code emits them as two separate `EventBus` events:
`JobBackend._run`/`_finish` publish `{id, status, kind, target_type}` and
`JobContext.progress` publishes `{id, progress_pct}` separately. This
mismatch predates Phase 3 (noted during Task 9's review) and is recorded
here per that task's carry-forward, not fixed — Phase 9 (docs) should decide
whether to change the doc or the wire shape.

## What was NOT verified

- **No live PVE.** Every proof above runs against `tests/fakes/pve.py`'s
  `FakePVE`. The Task 1 live-PVE integration test stays behind the
  `pve_integration` marker as designed.
- **No Docker.** Not needed by anything in this phase (no executor, no
  installs — those are Phase 4/5).
- **No browser on this box.** Clause 1's UI half (optimistic status patch on
  click, reconciliation on the job's terminal SSE delta or the next 30s
  poll, the typed self-target confirmation dialog) is proved by
  `frontend/src/tests/lifecycle.test.tsx` and `frontend/src/tests/jobs.test.ts`
  under jsdom, **not by a visual run in an actual browser**. No screenshot,
  no manual click-through happened or is claimed to have happened.
- Postgres-backend behavior for the new tables (`jobs`, `job_events`,
  `notification_channels`) — Phase 1/2's Postgres CI leg covers schema
  portability generically; nothing in Phase 3 added Postgres-specific
  exercises.

## What Phase 9 (docs) should write

- User-facing docs for the Notifications settings card: supported Apprise
  URL schemes/examples (ntfy, gotify, Telegram, Slack, generic webhook),
  and that the URL is write-only and cannot be retrieved once saved.
- The self-management guardrail's typed-confirmation UX (why Proxploy asks
  you to type the container's name before a destructive self-targeted
  action) and its known blind spot: a Proxploy deployed inside a VM rather
  than the documented LXC CT has no backstop (doc 02 decision, out of scope
  for Phase 3 — VM routes are deliberately unguarded).
- Resolve the doc 05 `job`-event `status`/`progress_pct` split noted above —
  either document the two-event wire shape or change the code to match the
  single-payload example.
