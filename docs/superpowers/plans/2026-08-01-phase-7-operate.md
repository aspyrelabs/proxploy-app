# Phase 7 (Operate) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Proxploy run itself unattended — apps update on a schedule, backups run on a schedule, and threshold alerts fire and resolve with notifications — so that Monday morning's job history tells the whole weekend's story.

**Architecture:** Three subsystems land on top of Phase 1–6 infrastructure with **zero new tables and zero Alembic migrations** (`schedules`, `alert_rules`, `alerts` and `notification_channels` have existed unused since migration 0001). (1) The **update pipeline** reuses `services/appstore.py`'s pinned-SSH-execute-stream-archive path, adding an `app.update` handler plus per-app and update-all routes. (2) The **scheduler** is a `schedules`-table-driven tick loop in `proxploy/jobs/scheduler.py` that enqueues into the existing `JobBackend`; APScheduler contributes only its `CronTrigger` cron math. (3) The **alert evaluator** rides the existing poll loop, reading the `metric_samples` rows the poller already writes and fanning firing/resolved transitions out through the existing `Notifier` and `EventBus`.

**Tech Stack:** Python 3.12+ / FastAPI / SQLAlchemy 2.x / Alembic / SQLite (WAL) / APScheduler **3.11.3** (cron math only) / Apprise / pytest — React 19 / Vite / TanStack Router + Query / Tailwind v4 / Vitest.

---

## Global Constraints

Every task's requirements implicitly include this section. Values are copied verbatim from the specs and from verification runs performed while writing this plan.

**Repository / process**

- All work lands on `main` directly. Never create a branch (standing project rule; every prior phase did the same).
- Working directory for backend commands is `backend/`; for frontend commands, `frontend/`.
- Backend tests: `./.venv/bin/python -m pytest tests/ -m "not pve_integration and not e2e"`. Frontend tests: `npm test`.
- Phase 6 finished at `b36846c` with backend **499 passed / 2 skipped / 4 deselected**, frontend **121 passed across 26 files**. Any task that leaves either suite below its starting count has broken something.
- Commit after every task, message prefix `feat(...)` / `fix(...)` / `test(...)` / `docs(...)` matching the touched area.

**Schema**

- **Zero Alembic migrations this phase.** Alembic head stays at `2330a95b98d2`. Verified: migration `9f3cd187d023_0001_full_entity_list.py` already creates `schedules` (line 241), `alert_rules` (line 24), `alerts` (line 187) and index `ix_alerts_state`, with column-for-column parity against `proxploy/models/__init__.py`. If any task appears to need a migration, stop and re-read the model — it does not.
- `utcnow()` returns a **naive** UTC datetime (`datetime.now(timezone.utc).replace(tzinfo=None)`). Every `DateTime` column in this codebase is naive UTC. Anything that touches an aware datetime (APScheduler's `CronTrigger`) must convert on both edges.

**Dependencies**

- **APScheduler 3.11.3, not 4.** Verified against PyPI on 2026-08-01: `pip index versions APScheduler` returns a maximum stable of **3.11.3**; the only 4.x artifacts published are `4.0.0a1`–`4.0.0a6`, all alphas. Docs 02/03/04/09/10 all say "APScheduler 4"; that version does not exist as a release and an alpha scheduler must not ship in a self-hosted product. Doc 03 marks Scheduling **"Provisional (seam: `Scheduler`)"**, which is exactly the licence to make this call. Task 19 records the amendment in doc 03.
- New runtime dependencies this phase: `APScheduler>=3.11,<4` (MIT) which pulls `tzlocal` (MIT). Both clear the CI allowlist in `.github/workflows/ci.yml:19` (`"MIT;MIT License;…"`). No other new dependency, backend or frontend.
- APScheduler is used for **`CronTrigger` only** — cron parsing and DST-correct next-fire arithmetic, the one part of scheduling that must never be hand-rolled. Its `BaseScheduler`/`AsyncIOScheduler`/jobstores are deliberately unused: doc 04 says the `schedules` table "is authoritative" and APScheduler state "is reconstructed from these rows at boot", so running a second in-memory job registry alongside it would be two sources of truth to reconcile on every CRUD write. The tick loop in Task 1 replaces all of that with one query.

**Verified `CronTrigger` behaviour** (all confirmed by running it, not assumed):

```
CronTrigger.from_crontab('0 3 * * *', timezone='America/New_York')  # 5 fields, IANA tz string
  .get_next_fire_time(None, <aware datetime>)  -> aware datetime in that tz, or None
bad cron ('bogus', '0 3 * * * *', '99 3 * * *', '')  -> ValueError
bad tz   ('Not/AZone')                               -> zoneinfo.ZoneInfoNotFoundError (subclasses KeyError)
```
So `except (ValueError, KeyError)` catches every malformed-input case. Passing `after == the fire time itself` advances to the *next* occurrence rather than returning the same instant — which is what stops a schedule from re-firing inside one tick.

**Error shape**

- `main.py::problem_handler` does `body.update(exc.detail)` when `detail` is a dict, so a dict-bodied `HTTPException` serialises **flat**, not nested under `detail`. Tests assert `r.json()["error"]`; frontend reads `e.body.error`. (Same finding that governed Phase 6.)

**Route ordering and auth invariants**

- On every gated route, list the role dependency **before** the entitlement dependency: `dependencies=[Depends(_require_admin), Depends(require_entitlement("k"))]`. A bare `Depends(require_entitlement(k))` alone lands at position 0 and 403s an anonymous caller who should get 401. `tests/test_route_auth_invariant.py` walks every registered route and fails on this; it needs no new entries for Phase 7 (nothing new here is public).
- Reuse one module-level `_require_admin = require_role("admin")` singleton per router so FastAPI's dependency cache collapses the route-level and parameter-level uses into one call.
- Literal-segment paths must be registered **before** any `/{id}/{wildcard}` route in the same router. In `api/apps.py` the `POST /{app_id}/{action}` lifecycle wildcard already carries a WARNING comment about this; `POST /apps/update-all` and `POST /apps/{app_id}/update` both go above it.

**Secrets**

- Apprise channel URLs are write-only: never in a response, never in an audit row, never in a log line. `services/notifier.py::redact_url` is the only safe rendering.
- `write_audit` redacts by key name (`services/audit.py::REDACT_SUBSTRINGS`). Never hand it a raw URL under any key.

**Job conventions**

- A handler is `async def h(ctx: JobContext, params: dict) -> dict`, registered at module bottom via `HANDLERS["kind"] = h`, and imported for its side effect in `main.py`'s lifespan with a `# noqa: F401` comment.
- Blocking work (SQLAlchemy, proxmoxer, SSH setup) goes in `asyncio.to_thread`. `ctx.log` / `ctx.progress` are called from the event loop only.
- Expected failures raise `JobFailed`; a `ProxmoxError` escaping a handler must be translated to `JobFailed` (the pattern every Phase 6 handler follows).
- Long PVE tasks pass `timeout_s=app.state.settings.pve_task_timeout_s` to `await_task`.

**Entitlement keys** — all already in `proxploy/entitlements/registry.py`; no key is added this phase:
`store.update`, `store.update_all`, `store.auto_update`, `sched.windows`, `alerts.rules`, `alerts.manage`, `notify.channels`, `notify.routing`, `notify.inapp`, `metrics.collect`, `backups.schedule`, `backups.notify`.

**Frontend**

- `api<T>(path, opts)` from `src/api/client.ts` prefixes `/api/v1`, sets `X-CSRF-Token` on mutating verbs, and throws `ApiError { status, body }`.
- Query keys follow doc 06 §(d): `['alerts','firing']` (60 s refetch), `['schedules']`, `['jobs', …]`. SSE handlers live in `src/api/live.ts` and are wired in `components/LiveProvider.tsx`.
- Tests mock `../api/client` with `vi.mock` and render inside a `QueryClientProvider` — copy the shape from `src/tests/channels.test.tsx`.
- Entitlement-gated UI waits for the first entitlements fetch (`ent.data != null && ent.has(key)`) before deciding, or it flashes a form that always 403s.

**Honesty rules (brief §8, and this codebase's established practice)**

- Never fabricate a capability. `api/apps.py::app_logs` returns a deliberate `501` with a written explanation rather than invent log lines; Phase 4 documented its transitive-vendoring limitation in `docs/notes/phase-4-store.md` rather than paper over it. Phase 7 has one such limitation (the community-scripts update path, Task 5) and it gets the same treatment.
- Mark deliberate simplifications that cut a real corner with a `ponytail:` comment naming the ceiling and the upgrade path.

---

## File Structure

**Backend — new files**

| File | Responsibility |
|---|---|
| `backend/proxploy/jobs/scheduler.py` | `next_fire()` cron math, `due()` selection, `fire_due()` one-tick core, `Scheduler` loop. The only module that imports APScheduler. |
| `backend/proxploy/api/schedules.py` | `/schedules` CRUD + run-now. |
| `backend/proxploy/services/alerts.py` | Rule evaluation, firing/resolved transitions, notification fan-out. No HTTP, no APScheduler. |
| `backend/proxploy/api/alerts.py` | `/alert-rules` CRUD + `/alerts` list/ack. |

**Backend — modified files**

| File | Change |
|---|---|
| `backend/pyproject.toml` | Add `APScheduler>=3.11,<4`. |
| `backend/proxploy/main.py` | Import `app.update` handler for registration; start the `Scheduler` task; seed system schedules; retire `metrics_loop`. |
| `backend/proxploy/config.py` | `scheduler_enabled`, `scheduler_tick_s`, `alerts_enabled`. |
| `backend/proxploy/services/appstore.py` | `run_update` handler + `mark_updates_available`; `run_install` clears `update_available`. |
| `backend/proxploy/services/catalog.py` | Call `mark_updates_available` at the end of `refresh_catalog`. |
| `backend/proxploy/api/apps.py` | `GET /{id}/update`, `POST /{id}/update`, `POST /update-all`. |
| `backend/proxploy/pollers/__init__.py` | Emit `mem_pct` (host/app/vm) and `disk_pct` (host) samples; run the alert evaluator per cycle. |
| `backend/proxploy/services/metrics.py` | Expose `rollup_and_prune` as a job handler; delete `metrics_loop`. |
| `backend/proxploy/api/cluster.py` | Merge alerts into `/cluster/activity`. |
| `backend/proxploy/api/__init__.py` | Register the two new routers. |

**Frontend — new files**

| File | Responsibility |
|---|---|
| `frontend/src/api/schedules.ts` | Schedule row type + CRUD hooks. |
| `frontend/src/api/alerts.ts` | Alert + rule types, hooks, `useFiringAlerts`. |
| `frontend/src/components/ScheduleForm.tsx` | Create/edit a schedule (name, kind, cron, timezone, params). |
| `frontend/src/components/AlertRuleForm.tsx` | Create/edit an alert rule. |
| `frontend/src/components/HealthFooter.tsx` | The sidebar health footer, bound to real data. |
| `frontend/src/routes/alerts.tsx` | `/alerts` — firing + history + rules. |
| `frontend/src/tests/schedules.test.tsx`, `alerts.test.tsx`, `updates.test.tsx`, `healthfooter.test.tsx` | Coverage for the above. |

**Frontend — modified files**

`src/api/live.ts` (alert event), `src/components/LiveProvider.tsx` (wire it), `src/components/SidebarNav.tsx` (nav entry + real footer), `src/router.tsx` (route), `src/routes/settings.tsx` (Schedules card, General card), `src/routes/backups.tsx` ("New job"), `src/routes/apps.tsx` (update button/badge), `src/routes/cluster.tsx` ("Update all").

---

## Task Order and Dependencies

```
1  scheduler core (cron math + due/fire, pure)
2  └─ Scheduler loop + config + lifespan wiring + metrics.maintain + system schedules
3     └─ /schedules CRUD API
4  update_available detection (independent of 1–3)
5  └─ app.update job handler
6     └─ /apps/{id}/update routes
7        └─ /apps/update-all
8  poller emits mem_pct + disk_pct (independent)
9  └─ alert evaluator core (pure)
10    └─ alert notification fan-out + SSE
11       └─ evaluator wired into the poll loop
12    └─ /alert-rules CRUD API
13    └─ /alerts list + ack
14 activity feed merges alerts (needs 13)
15 frontend: live.ts alert handling + HealthFooter (needs 13)
16 frontend: /alerts page (needs 12, 13)
17 frontend: Schedules card + Backups "New job" (needs 3)
18 frontend: update badge/button + "Update all" (needs 6, 7)
19 DoD verification + notes + doc amendments + buildlog
```

Tasks 1–3, 4–7 and 8–13 are three independent chains; they can be worked in any interleaving. Task 19 is last.

---

## Task 1: Scheduler core — cron math, due selection, firing

**Files:**
- Modify: `backend/pyproject.toml` (dependency list, after `"requests-toolbelt>=1.0",`)
- Create: `backend/proxploy/jobs/scheduler.py`
- Test: `backend/tests/test_scheduler_core.py`

**Interfaces:**
- Consumes: `proxploy.models.Schedule`, `proxploy.models.utcnow`, `proxploy.jobs.HANDLERS`, `proxploy.services.audit.write_audit`, `tests.support.make_job_app`.
- Produces, for Tasks 2 and 3:
  - `BadSchedule(ValueError)` — malformed cron, unknown timezone, or unregistered job kind.
  - `next_fire(cron: str, tz: str, after: datetime) -> datetime` — naive-UTC in, naive-UTC out; strictly after `after`.
  - `validate(cron: str, tz: str, job_kind: str) -> None` — raises `BadSchedule`.
  - `prime(db, now: datetime) -> int` — fills `next_run_at` on enabled rows that have none; returns how many.
  - `due(db, now: datetime) -> list[Schedule]` — enabled rows whose `next_run_at <= now`, oldest first.
  - `fire_one(app, db, s: Schedule, now: datetime) -> dict | None` — enqueues one job, advances the row; `{"schedule_id", "job_id", "kind"}` or `None` if the row was disabled as broken.
  - `tick(app, now: datetime | None = None) -> list[dict]` — blocking; one full pass. This is what Task 2's loop calls.

- [ ] **Step 1: Add the dependency**

In `backend/pyproject.toml`, inside `[project] dependencies`, after the `"requests-toolbelt>=1.0",` line, add:

```toml
  # Cron math ONLY (proxploy/jobs/scheduler.py) — CronTrigger's parsing and
  # DST-correct next-fire arithmetic. Its BaseScheduler/jobstores are unused:
  # doc 04 makes the `schedules` table authoritative, so a second in-memory
  # registry would be two sources of truth. Docs say "APScheduler 4"; no 4.x
  # release exists (alphas only, verified 2026-08-01) and doc 03 marks
  # Scheduling "Provisional (seam: Scheduler)" — see docs/notes/phase-7-operate.md.
  "APScheduler>=3.11,<4",
```

Then install it:

```bash
./.venv/bin/pip install -e ".[dev]"
```

- [ ] **Step 2: Confirm the licence gate still passes**

Run:

```bash
./.venv/bin/pip-licenses --partial-match --ignore-packages proxploy --allow-only "MIT;MIT License;BSD;BSD License;Apache;Apache Software License;ISC;Python Software Foundation;PSF-2.0;PostgreSQL;Public Domain;Mozilla Public License 2.0;Eclipse Public License v2.0;EPL-2.0;The Unlicense;CMU License (MIT-CMU)"
```

Expected: exit 0, no output naming `APScheduler` or `tzlocal`. Both are MIT. If this fails, stop — a dependency outside brief §3 does not ship.

- [ ] **Step 3: Write the failing test**

Create `backend/tests/test_scheduler_core.py`:

```python
"""Scheduler core (doc 10 Phase 7, doc 04 `schedules`).

These are the pure pieces — cron math, due selection, one firing pass. The
loop that calls `tick` lives in Task 2 and is tested separately.
"""
import asyncio
from datetime import datetime

import pytest

from proxploy.jobs.scheduler import (
    BadSchedule, due, fire_one, next_fire, prime, tick, validate,
)
from proxploy.models import AuditEvent, Job, Schedule
from tests.support import make_db, make_job_app


def _sched(db, **kw):
    kw.setdefault("name", "nightly")
    kw.setdefault("job_kind", "catalog.refresh")
    kw.setdefault("cron", "0 3 * * *")
    kw.setdefault("timezone", "UTC")
    kw.setdefault("enabled", True)
    row = Schedule(**kw)
    db.add(row)
    db.commit()
    return row


# --- next_fire --------------------------------------------------------------

def test_next_fire_is_naive_utc_in_and_out():
    got = next_fire("0 3 * * *", "UTC", datetime(2026, 8, 1, 12, 0))
    assert got == datetime(2026, 8, 2, 3, 0)
    assert got.tzinfo is None


def test_next_fire_converts_a_local_timezone_to_utc():
    # 03:00 America/New_York on 2026-08-02 is 07:00 UTC (EDT, UTC-4).
    assert next_fire("0 3 * * *", "America/New_York",
                     datetime(2026, 8, 1, 12, 0)) == datetime(2026, 8, 2, 7, 0)
    # 03:00 Asia/Kolkata is 21:30 UTC the previous day (UTC+5:30).
    assert next_fire("0 3 * * *", "Asia/Kolkata",
                     datetime(2026, 8, 1, 12, 0)) == datetime(2026, 8, 1, 21, 30)


def test_next_fire_at_the_boundary_advances_rather_than_repeating():
    """`after` == a firing instant must yield the NEXT one. Without this a
    schedule fires again on every tick until the minute rolls over."""
    assert next_fire("0 3 * * *", "UTC",
                     datetime(2026, 8, 2, 3, 0)) == datetime(2026, 8, 3, 3, 0)


@pytest.mark.parametrize("cron", ["bogus", "0 3 * * * *", "99 3 * * *", ""])
def test_next_fire_rejects_malformed_cron(cron):
    with pytest.raises(BadSchedule):
        next_fire(cron, "UTC", datetime(2026, 8, 1, 12, 0))


def test_next_fire_rejects_an_unknown_timezone():
    # zoneinfo raises ZoneInfoNotFoundError, which subclasses KeyError, not
    # ValueError — both have to be caught or this escapes as a 500.
    with pytest.raises(BadSchedule):
        next_fire("0 3 * * *", "Not/AZone", datetime(2026, 8, 1, 12, 0))


def test_validate_rejects_an_unregistered_job_kind():
    validate("0 3 * * *", "UTC", "catalog.refresh")  # registered, no raise
    with pytest.raises(BadSchedule) as e:
        validate("0 3 * * *", "UTC", "app.doesnotexist")
    assert "app.doesnotexist" in str(e.value)


# --- prime / due ------------------------------------------------------------

def test_prime_fills_next_run_at_only_where_it_is_missing(tmp_path):
    db = make_db(tmp_path)
    fresh = _sched(db, name="fresh")
    already = _sched(db, name="already", next_run_at=datetime(2030, 1, 1))
    off = _sched(db, name="off", enabled=False)

    assert prime(db, datetime(2026, 8, 1, 12, 0)) == 1
    db.refresh(fresh); db.refresh(already); db.refresh(off)
    assert fresh.next_run_at == datetime(2026, 8, 2, 3, 0)
    assert already.next_run_at == datetime(2030, 1, 1)   # untouched
    assert off.next_run_at is None                        # disabled rows are not primed


def test_prime_disables_a_row_whose_cron_no_longer_parses(tmp_path):
    """A hand-edited DB, or a tz dropped from the host's tzdata. One bad row
    must not make prime() raise and take the whole tick with it."""
    db = make_db(tmp_path)
    bad = _sched(db, name="bad", cron="not a cron")
    assert prime(db, datetime(2026, 8, 1, 12, 0)) == 0
    db.refresh(bad)
    assert bad.enabled is False
    assert bad.next_run_at is None


def test_due_returns_only_enabled_rows_that_are_ripe_oldest_first(tmp_path):
    db = make_db(tmp_path)
    now = datetime(2026, 8, 1, 12, 0)
    late = _sched(db, name="late", next_run_at=datetime(2026, 8, 1, 10, 0))
    ripe = _sched(db, name="ripe", next_run_at=now)
    _sched(db, name="future", next_run_at=datetime(2026, 8, 1, 13, 0))
    _sched(db, name="disabled", enabled=False, next_run_at=datetime(2026, 1, 1))
    _sched(db, name="unprimed", next_run_at=None)

    assert [s.id for s in due(db, now)] == [late.id, ripe.id]


# --- fire_one ---------------------------------------------------------------

def test_fire_one_enqueues_stamps_and_advances(tmp_path):
    async def go():
        app = make_job_app(tmp_path)
        from proxploy.jobs import JobBackend
        app.state.jobs = JobBackend(app)
        now = datetime(2026, 8, 1, 12, 0)
        with app.state.sessionmaker() as db:
            s = _sched(db, next_run_at=now)
            out = fire_one(app, db, s, now)
            assert out["schedule_id"] == s.id
            assert out["kind"] == "catalog.refresh"

            job = db.get(Job, out["job_id"])
            assert job.kind == "catalog.refresh"
            assert job.schedule_id == s.id
            assert job.requested_by is None        # system-spawned, doc 04
            assert job.target_type == "system"

            db.refresh(s)
            assert s.last_run_at == now
            # advanced from `now`, NOT from the stale next_run_at — a week of
            # downtime must produce one catch-up run, not one per missed day.
            assert s.next_run_at == datetime(2026, 8, 2, 3, 0)

            row = (db.query(AuditEvent)
                   .filter_by(action="schedule.fire", target_id=s.id).one())
            assert row.actor_type == "system"
            assert row.actor_id is None
            assert row.job_id == out["job_id"]

    asyncio.run(go())


def test_fire_one_derives_the_job_target_from_params(tmp_path):
    async def go():
        app = make_job_app(tmp_path)
        from proxploy.jobs import JobBackend
        app.state.jobs = JobBackend(app)
        now = datetime(2026, 8, 1, 12, 0)
        with app.state.sessionmaker() as db:
            s = _sched(db, job_kind="backup.run", params={"host_id": 7},
                       next_run_at=now)
            out = fire_one(app, db, s, now)
            job = db.get(Job, out["job_id"])
            assert (job.target_type, job.target_id) == ("host", 7)
            assert job.params == {"host_id": 7}

    asyncio.run(go())


def test_fire_one_disables_a_schedule_whose_handler_vanished(tmp_path):
    """A job kind can disappear across an upgrade. Enqueue would raise KeyError
    and kill the tick; instead the row is disabled with an audit trail."""
    async def go():
        app = make_job_app(tmp_path)
        from proxploy.jobs import JobBackend
        app.state.jobs = JobBackend(app)
        now = datetime(2026, 8, 1, 12, 0)
        with app.state.sessionmaker() as db:
            s = _sched(db, job_kind="gone.forever", next_run_at=now)
            assert fire_one(app, db, s, now) is None
            db.refresh(s)
            assert s.enabled is False
            row = (db.query(AuditEvent)
                   .filter_by(action="schedule.disable", target_id=s.id).one())
            assert row.result == "error"
            assert db.query(Job).count() == 0

    asyncio.run(go())


# --- tick -------------------------------------------------------------------

def test_tick_primes_then_fires_and_is_idempotent_within_the_minute(tmp_path):
    async def go():
        app = make_job_app(tmp_path)
        from proxploy.jobs import JobBackend
        app.state.jobs = JobBackend(app)
        with app.state.sessionmaker() as db:
            _sched(db, name="hourly", cron="0 * * * *")

        # 11:59 — primed to 12:00, nothing due yet.
        assert tick(app, datetime(2026, 8, 1, 11, 59)) == []
        # 12:00 — fires once.
        first = tick(app, datetime(2026, 8, 1, 12, 0))
        assert len(first) == 1
        # 12:00:30 — the row now points at 13:00, so the same tick does not
        # re-fire it. This is the regression the boundary rule above prevents.
        assert tick(app, datetime(2026, 8, 1, 12, 0, 30)) == []

        with app.state.sessionmaker() as db:
            assert db.query(Job).count() == 1

    asyncio.run(go())
```

- [ ] **Step 4: Run it to make sure it fails**

Run: `./.venv/bin/python -m pytest tests/test_scheduler_core.py -q`
Expected: collection error — `ModuleNotFoundError: No module named 'proxploy.jobs.scheduler'`.

- [ ] **Step 5: Write the implementation**

Create `backend/proxploy/jobs/scheduler.py`:

```python
"""Scheduler seam (brief §5, doc 02 §3, doc 04 `schedules`) — cron triggers
feeding the JobBackend.

Doc 04, verbatim: "APScheduler's own state is reconstructed from these rows at
boot; this table is authoritative." Taken literally there is no second registry
to reconstruct — this module reads `schedules` on every tick and enqueues what
is ripe. APScheduler contributes `CronTrigger` and nothing else: cron parsing
and DST-correct next-fire arithmetic, the one part of scheduling that must
never be hand-rolled. Its BaseScheduler/AsyncIOScheduler/jobstores would be a
second source of truth to reconcile on every CRUD write, which is exactly what
doc 04's sentence rules out.

Docs 02/03/04/09/10 name "APScheduler 4". No 4.x release exists — only
4.0.0a1..a6 (verified against PyPI 2026-08-01) — and doc 03 marks Scheduling
"Provisional (seam: `Scheduler`)", so this ships on the stable 3.11 line. See
docs/notes/phase-7-operate.md.

Failure policy: one malformed row must never stop the other schedules. A row
whose cron/timezone no longer parses, or whose `job_kind` has no registered
handler, is DISABLED with an audit row rather than retried forever or allowed
to raise out of the tick.
"""
from __future__ import annotations

from datetime import datetime, timezone

from apscheduler.triggers.cron import CronTrigger

from proxploy.jobs import HANDLERS
from proxploy.models import Schedule, utcnow
from proxploy.services.audit import write_audit


class BadSchedule(ValueError):
    """Malformed cron expression, unknown timezone, or unregistered job kind."""


def next_fire(cron: str, tz: str, after: datetime) -> datetime:
    """Next firing strictly after `after`. Naive UTC in, naive UTC out.

    Every DateTime column in this codebase is naive UTC (`models.utcnow`);
    CronTrigger needs an aware datetime and hands back an aware one in `tz`.
    Both conversions happen here so no caller ever holds an aware datetime.

    Passing a firing instant as `after` yields the NEXT occurrence, not the
    same one — that property is what stops a tick from re-firing the schedule
    it just fired.
    """
    try:
        trigger = CronTrigger.from_crontab(cron, timezone=tz)
    except (ValueError, KeyError) as e:
        # ValueError: field count / range errors.
        # KeyError: zoneinfo.ZoneInfoNotFoundError subclasses it, so an unknown
        # tz lands here rather than escaping as a 500.
        raise BadSchedule(f"{cron!r} @ {tz!r}: {e}") from e
    nxt = trigger.get_next_fire_time(None, after.replace(tzinfo=timezone.utc))
    if nxt is None:
        raise BadSchedule(f"cron {cron!r} has no future firing")
    return nxt.astimezone(timezone.utc).replace(tzinfo=None)


def validate(cron: str, tz: str, job_kind: str) -> None:
    """Everything the API must reject at write time. Raises BadSchedule."""
    if job_kind not in HANDLERS:
        raise BadSchedule(f"no job handler registered for kind {job_kind!r}")
    next_fire(cron, tz, utcnow())


def _target(params: dict | None) -> tuple[str, int | None]:
    """Job target from the schedule's params, so a scheduled run invalidates
    the same UI caches an ad-hoc one does (doc 05 §Streaming: the `job` delta
    carries `target_type`, and api/live.ts routes on it)."""
    params = params or {}
    for key, kind in (("app_id", "app"), ("vm_id", "vm"), ("host_id", "host")):
        if params.get(key) is not None:
            return kind, int(params[key])
    return "system", None


def _disable(db, s: Schedule, reason: str) -> None:
    s.enabled = False
    s.next_run_at = None
    db.commit()
    write_audit(db, actor_type="system", action="schedule.disable",
                target_type="schedule", target_id=s.id, result="error",
                params={"name": s.name, "reason": reason})


def prime(db, now: datetime) -> int:
    """Give every enabled schedule a `next_run_at`. Returns how many were set.

    Called at boot and at the top of every tick, so a row created directly in
    the DB (or one whose next_run_at was cleared) starts firing without a
    restart. Rows that already have a next_run_at are never recomputed here —
    that would move a schedule's firing time on every tick.
    """
    primed = 0
    rows = (db.query(Schedule)
            .filter(Schedule.enabled.is_(True), Schedule.next_run_at.is_(None))
            .all())
    for s in rows:
        try:
            s.next_run_at = next_fire(s.cron, s.timezone, now)
        except BadSchedule as e:
            _disable(db, s, str(e))
            continue
        primed += 1
    db.commit()
    return primed


def due(db, now: datetime) -> list[Schedule]:
    """Enabled, primed, and ripe — oldest first so a backlog fires in order."""
    return (db.query(Schedule)
            .filter(Schedule.enabled.is_(True),
                    Schedule.next_run_at.is_not(None),
                    Schedule.next_run_at <= now)
            .order_by(Schedule.next_run_at, Schedule.id)
            .all())


def fire_one(app, db, s: Schedule, now: datetime) -> dict | None:
    """Enqueue one schedule's job and advance the row. None if it was disabled.

    `next_run_at` advances from `now`, NOT from the stale `next_run_at`: after
    a week of downtime the schedule owes exactly one catch-up run, not one per
    missed occurrence. Skipped occurrences are visible as the gap in the job
    history, which is the honest record.
    """
    params = dict(s.params or {})
    target_type, target_id = _target(params)
    try:
        job = app.state.jobs.enqueue(
            db, kind=s.job_kind, target_type=target_type, target_id=target_id,
            params=params, requested_by=None, schedule_id=s.id)
    except KeyError as e:
        # JobBackend.enqueue raises this for an unregistered kind — a job kind
        # can genuinely disappear across an upgrade, and retrying it every tick
        # forever would be the wrong answer.
        _disable(db, s, f"no handler for job kind {s.job_kind!r}: {e}")
        return None

    s.last_run_at = now
    try:
        s.next_run_at = next_fire(s.cron, s.timezone, now)
    except BadSchedule as e:
        # The job is already enqueued and stays enqueued; only the schedule
        # stops. Disabling here still leaves the audit trail below unwritten,
        # so write it first.
        write_audit(db, actor_type="system", action="schedule.fire",
                    target_type="schedule", target_id=s.id, job_id=job.id,
                    params={"name": s.name, "job_kind": s.job_kind})
        _disable(db, s, str(e))
        return {"schedule_id": s.id, "job_id": job.id, "kind": s.job_kind}
    db.commit()
    write_audit(db, actor_type="system", action="schedule.fire",
                target_type="schedule", target_id=s.id, job_id=job.id,
                params={"name": s.name, "job_kind": s.job_kind})
    return {"schedule_id": s.id, "job_id": job.id, "kind": s.job_kind}


def tick(app, now: datetime | None = None) -> list[dict]:
    """One full pass: prime, select, fire. Blocking — runs in a worker thread.

    `JobBackend.enqueue` is explicitly safe from FastAPI's threadpool (it hops
    to the loop via `call_soon_threadsafe`), which is the same contract this
    relies on.
    """
    now = now or utcnow()
    fired: list[dict] = []
    with app.state.sessionmaker() as db:
        prime(db, now)
        for s in due(db, now):
            out = fire_one(app, db, s, now)
            if out is not None:
                fired.append(out)
    return fired
```

- [ ] **Step 6: Run the tests**

Run: `./.venv/bin/python -m pytest tests/test_scheduler_core.py -q`
Expected: PASS, 13 tests.

- [ ] **Step 7: Run the full backend suite**

Run: `./.venv/bin/python -m pytest tests/ -m "not pve_integration and not e2e" -q`
Expected: 512 passed / 2 skipped (499 + 13), no failures.

- [ ] **Step 8: Commit**

```bash
git add backend/pyproject.toml backend/proxploy/jobs/scheduler.py backend/tests/test_scheduler_core.py
git commit -m "feat(scheduler): cron math, due selection and one-pass firing over the schedules table

APScheduler 3.11.3 for CronTrigger only — no 4.x release exists (alphas
only) and doc 04 makes the schedules table authoritative, so a second
in-memory registry would be two sources of truth."
```

---

## Task 2: Scheduler loop, lifespan wiring, and metrics maintenance as a job

**Files:**
- Create: nothing
- Modify: `backend/proxploy/jobs/scheduler.py` (append `Scheduler` + `SYSTEM_SCHEDULES` + `seed_system_schedules`)
- Modify: `backend/proxploy/jobs/__init__.py` (export `Scheduler`)
- Modify: `backend/proxploy/config.py` (three settings)
- Modify: `backend/proxploy/services/metrics.py` (add `maintain` handler, delete `metrics_loop`)
- Modify: `backend/proxploy/main.py` (start the scheduler, drop `metrics_loop`)
- Test: `backend/tests/test_scheduler_loop.py`
- Test: `backend/tests/test_metrics_store.py` (update the `metrics_loop` reference)

**Interfaces:**
- Consumes: Task 1's `tick`, `prime`, `validate`; `proxploy.services.metrics.rollup`, `prune`.
- Produces, for Tasks 3 and 19:
  - `Scheduler(app)` with `async def run(self)` and `def stop(self)`.
  - `SYSTEM_SCHEDULES: tuple[dict, ...]` — seeded rows, keyed by `name`.
  - `seed_system_schedules(db) -> int` — inserts any missing system row; returns how many.
  - Job kind `metrics.maintain` registered in `HANDLERS`.
  - Settings `scheduler_enabled: bool = True`, `scheduler_tick_s: float = 30.0`, `alerts_enabled: bool = True`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_scheduler_loop.py`:

```python
"""The Scheduler loop, its system-schedule seeding, and metrics.maintain."""
import asyncio
from datetime import datetime, timedelta

from proxploy.jobs.scheduler import (
    SYSTEM_SCHEDULES, Scheduler, seed_system_schedules,
)
from proxploy.models import Job, MetricRollup, MetricSample, Schedule, utcnow
from tests.support import make_db, make_job_app


def test_seeding_is_idempotent_and_covers_every_system_schedule(tmp_path):
    db = make_db(tmp_path)
    assert seed_system_schedules(db) == len(SYSTEM_SCHEDULES)
    assert seed_system_schedules(db) == 0          # second boot adds nothing
    names = {s.name for s in db.query(Schedule).all()}
    assert names == {s["name"] for s in SYSTEM_SCHEDULES}
    for row in db.query(Schedule).all():
        assert row.enabled is True
        assert row.created_by is None              # system-owned, not a user


def test_seeding_does_not_resurrect_a_system_schedule_the_operator_disabled(tmp_path):
    """Re-enabling on every boot would make "turn off the nightly catalog
    refresh" impossible to express."""
    db = make_db(tmp_path)
    seed_system_schedules(db)
    row = db.query(Schedule).filter_by(name=SYSTEM_SCHEDULES[0]["name"]).one()
    row.enabled = False
    db.commit()

    assert seed_system_schedules(db) == 0
    db.refresh(row)
    assert row.enabled is False


def test_every_system_schedule_names_a_registered_handler():
    """Seeding a kind with no handler would disable itself on first tick."""
    from proxploy.jobs import HANDLERS
    import proxploy.services.metrics          # noqa: F401 — registers metrics.maintain
    import proxploy.services.catalog          # noqa: F401 — registers catalog.refresh
    for s in SYSTEM_SCHEDULES:
        assert s["job_kind"] in HANDLERS, s["name"]


def test_loop_fires_a_ripe_schedule_then_stops_cleanly(tmp_path):
    async def go():
        app = make_job_app(tmp_path)
        from proxploy.jobs import JobBackend
        app.state.jobs = JobBackend(app)
        app.state.settings = app.state.settings.model_copy(
            update={"scheduler_tick_s": 0.01})
        with app.state.sessionmaker() as db:
            db.add(Schedule(name="soon", job_kind="catalog.refresh",
                            cron="* * * * *", timezone="UTC", enabled=True,
                            next_run_at=utcnow() - timedelta(minutes=1)))
            db.commit()

        sched = Scheduler(app)
        task = asyncio.create_task(sched.run())
        for _ in range(200):                      # ~2 s ceiling
            await asyncio.sleep(0.01)
            with app.state.sessionmaker() as db:
                if db.query(Job).count():
                    break
        sched.stop()
        task.cancel()

        with app.state.sessionmaker() as db:
            jobs = db.query(Job).all()
        assert len(jobs) >= 1
        assert jobs[0].kind == "catalog.refresh"
        assert jobs[0].schedule_id is not None

    asyncio.run(go())


def test_loop_survives_a_tick_that_raises(tmp_path):
    """A supervisor that dies on one bad tick stops every future schedule."""
    async def go():
        app = make_job_app(tmp_path)
        from proxploy.jobs import JobBackend
        app.state.jobs = JobBackend(app)
        app.state.settings = app.state.settings.model_copy(
            update={"scheduler_tick_s": 0.01})

        calls = {"n": 0}
        import proxploy.jobs.scheduler as mod
        real = mod.tick

        def boom(a, now=None):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("db locked")
            return real(a, now)

        mod.tick, sched = boom, Scheduler(app)
        try:
            task = asyncio.create_task(sched.run())
            for _ in range(200):
                await asyncio.sleep(0.01)
                if calls["n"] >= 3:
                    break
            sched.stop()
            task.cancel()
        finally:
            mod.tick = real
        assert calls["n"] >= 3     # kept ticking after the raise

    asyncio.run(go())


# --- metrics.maintain -------------------------------------------------------

def test_metrics_maintain_rolls_up_and_prunes(tmp_path):
    async def go():
        from proxploy.jobs import HANDLERS, JobContext
        from proxploy.services import metrics as m

        app = make_job_app(tmp_path)
        from proxploy.jobs import JobBackend
        app.state.jobs = JobBackend(app)
        now = utcnow()
        with app.state.sessionmaker() as db:
            # in-window samples that must roll up ...
            for i in range(6):
                db.add(MetricSample(target_type="host", target_id=1,
                                    metric="cpu_pct", value=10.0 + i,
                                    ts=now - timedelta(minutes=20 + i)))
            # ... and one older than RAW_RETENTION_H that must be pruned.
            db.add(MetricSample(target_type="host", target_id=1,
                                metric="cpu_pct", value=99.0,
                                ts=now - timedelta(hours=m.RAW_RETENTION_H + 1)))
            db.commit()
            job = Job(kind="metrics.maintain", status="running")
            db.add(job)
            db.commit()
            job_id = job.id

        ctx = JobContext(app.state.jobs, job_id)
        out = await HANDLERS["metrics.maintain"](ctx, {})

        assert out["pruned"]["raw"] == 1
        assert out["rollups"]["5m"] >= 1
        with app.state.sessionmaker() as db:
            assert db.query(MetricRollup).filter_by(resolution="5m").count() >= 1
            assert db.query(MetricSample).filter(
                MetricSample.value == 99.0).count() == 0

    asyncio.run(go())


def test_metrics_loop_is_gone():
    """It was replaced by the metrics.maintain schedule (doc 04: "All pruning
    runs as scheduled system jobs, visible in the activity feed")."""
    from proxploy.services import metrics
    assert not hasattr(metrics, "metrics_loop")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `./.venv/bin/python -m pytest tests/test_scheduler_loop.py -q`
Expected: `ImportError: cannot import name 'SYSTEM_SCHEDULES' from 'proxploy.jobs.scheduler'`.

- [ ] **Step 3: Add the settings**

In `backend/proxploy/config.py`, after the `backup_sync_stale_s: float = 900.0` line:

```python
    # Scheduler (doc 10 Phase 7). The tick is the resolution floor: a cron
    # expression cannot be finer than one minute, so 30s is already twice as
    # often as it needs to be and costs one indexed SELECT.
    scheduler_enabled: bool = True
    scheduler_tick_s: float = 30.0
    # Alert evaluation rides the poll cycle (services/alerts.py); off means the
    # poller still writes samples, nothing evaluates them.
    alerts_enabled: bool = True
```

- [ ] **Step 4: Replace `metrics_loop` with a job handler**

In `backend/proxploy/services/metrics.py`, delete the entire `async def metrics_loop(app)` function at the bottom of the file (lines 113–132) and the now-unused `import asyncio` at line 10, then append:

```python
async def maintain(ctx, params: dict) -> dict:
    """`metrics.maintain` — hourly rollups + retention prune, as a real job.

    Doc 04: "All pruning runs as scheduled system jobs (visible in the activity
    feed like any other job)". This replaces Phase 2's silent `metrics_loop`
    lifespan task, which is why the lookbacks are wider than that loop's:
    running hourly instead of every five minutes, 13 five-minute buckets covers
    the full hour and then some. Rollups are idempotent (delete+insert over the
    window), so an overlapping lookback is free and a missed run self-heals on
    the next one.

    Charts under six hours read RAW samples (`pick_resolution`), so nothing
    user-visible lags by moving the 5m rollup from a 5-minute to a 60-minute
    cadence.
    """
    app = ctx.backend.app

    def work() -> dict:
        with app.state.sessionmaker() as db:
            now = utcnow()
            rollups = {"5m": rollup(db, "5m", now, lookback=13),
                       "1h": rollup(db, "1h", now, lookback=2)}
            return {"rollups": rollups, "pruned": prune(db, now)}

    ctx.log("rolling up metric samples and applying retention")
    out = await asyncio.to_thread(work)
    ctx.log(f"5m buckets: {out['rollups']['5m']}, 1h buckets: {out['rollups']['1h']}")
    ctx.log(f"pruned raw={out['pruned']['raw']} 5m={out['pruned']['5m']} "
            f"1h={out['pruned']['1h']}")
    ctx.progress(100)
    return out


HANDLERS["metrics.maintain"] = maintain
```

Keep `import asyncio` after all (`maintain` uses `asyncio.to_thread`) and add to the imports at the top of the file:

```python
from proxploy.jobs import HANDLERS
```

> Import-cycle note: `proxploy.jobs` imports only from `proxploy.jobs.backend`, which imports `proxploy.models` and `proxploy.services.audit` — never `proxploy.services.metrics`. `services/catalog.py`, `services/lifecycle.py` and every Phase 6 job module already import `HANDLERS` this way.

- [ ] **Step 5: Append the loop and seeding to `scheduler.py`**

At the bottom of `backend/proxploy/jobs/scheduler.py`:

```python
# --- system schedules -------------------------------------------------------

# Rows Proxploy owns. Seeded by name at boot if absent, never re-created or
# re-enabled once the operator has touched them (see seed_system_schedules).
# `catalog.refresh` is what keeps `apps.update_available` honest — without it
# an auto-update window would never see a new upstream commit.
SYSTEM_SCHEDULES: tuple[dict, ...] = (
    {"name": "Catalog refresh", "job_kind": "catalog.refresh",
     "cron": "0 4 * * *", "timezone": "UTC", "params": {}},
    {"name": "Metrics maintenance", "job_kind": "metrics.maintain",
     "cron": "7 * * * *", "timezone": "UTC", "params": {}},
)


def seed_system_schedules(db) -> int:
    """Insert any missing system schedule. Returns how many were created.

    Keyed on `name`, and deliberately one-way: a system row the operator
    disabled or re-timed stays that way across restarts. Re-enabling here would
    make "stop refreshing the catalog nightly" impossible to express.
    """
    existing = {name for (name,) in db.query(Schedule.name).all()}
    created = 0
    for spec in SYSTEM_SCHEDULES:
        if spec["name"] in existing:
            continue
        db.add(Schedule(enabled=True, created_by=None, **spec))
        created += 1
    if created:
        db.commit()
    return created


# --- the loop ---------------------------------------------------------------

class Scheduler:
    """One tick loop, shaped like pollers.Poller: the supervisor never dies.

    All DB work runs in `asyncio.to_thread` — SQLAlchemy is blocking, and a
    scheduler that stalls the event loop would stall the SSE fanout, the
    pollers and every in-flight job with it.
    """

    def __init__(self, app) -> None:
        self.app = app
        self._stopped = False

    async def run(self) -> None:
        import asyncio

        interval = self.app.state.settings.scheduler_tick_s
        while not self._stopped:
            try:
                for entry in await asyncio.to_thread(tick, self.app):
                    self.app.state.bus.publish(
                        "job", {"id": entry["job_id"], "kind": entry["kind"],
                                "status": "queued",
                                "schedule_id": entry["schedule_id"]})
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — one bad tick must not end them all
                pass
            await asyncio.sleep(interval)

    def stop(self) -> None:
        self._stopped = True
```

Move `import asyncio` to the module's top-level imports rather than inside `run` — it is written inline above only to keep the diff readable; put it with `from datetime import ...` at the top of the file and delete the local import.

- [ ] **Step 6: Export it**

In `backend/proxploy/jobs/__init__.py`:

```python
from proxploy.jobs.backend import (
    HANDLERS, TERMINAL, JobBackend, JobContext, JobFailed, handler,
)
from proxploy.jobs.scheduler import Scheduler

__all__ = ["HANDLERS", "TERMINAL", "JobBackend", "JobContext", "JobFailed",
           "handler", "Scheduler"]
```

- [ ] **Step 7: Wire it into the lifespan**

In `backend/proxploy/main.py`:

1. In the import block around line 82–90, replace `from proxploy.services.metrics import metrics_loop` with `from proxploy.services import metrics as _metrics  # noqa: F401 — registers metrics.maintain`.
2. Replace the poller/metrics startup block (currently lines 100–104) with:

```python
        app.state.poller = Poller(app)
        app.state.scheduler = Scheduler(app)
        poller_task = scheduler_task = None
        if settings.poll_enabled:
            poller_task = asyncio.create_task(app.state.poller.run())
        if settings.scheduler_enabled:
            # Seeding needs every handler registered, which the imports above
            # have just done; priming needs the seeded rows.
            from proxploy.jobs.scheduler import prime, seed_system_schedules
            with app.state.sessionmaker() as db:
                seed_system_schedules(db)
                prime(db, utcnow())
            scheduler_task = asyncio.create_task(app.state.scheduler.run())
```

3. Add `Scheduler` to the `from proxploy.jobs import JobBackend` line so it reads `from proxploy.jobs import JobBackend, Scheduler`.
4. Add `from proxploy.models import AppSetting, utcnow` to the top-level import at line 14.
5. In the shutdown block (currently lines 107–115), replace the `metrics_task` lines with the scheduler:

```python
        if poller_task:
            poller_task.cancel()
        if scheduler_task:
            scheduler_task.cancel()
        app.state.scheduler.stop()
        app.state.poller.stop()
        app.state.jobs.stop()
        app.state.engine.dispose()
```

- [ ] **Step 8: Fix the one existing reference**

Run `grep -rn "metrics_loop" backend/` — the only hits should be `tests/test_metrics_store.py` (if any) and the docstring in `services/metrics.py` you already removed. Delete or rewrite any test that imports `metrics_loop`; `test_metrics_loop_is_gone` in Step 1 replaces its coverage, and `test_metrics_maintain_rolls_up_and_prunes` covers the behaviour.

- [ ] **Step 9: Run the tests**

Run: `./.venv/bin/python -m pytest tests/test_scheduler_loop.py tests/test_metrics_store.py tests/test_health.py -q`
Expected: PASS.

- [ ] **Step 10: Run the full suite**

Run: `./.venv/bin/python -m pytest tests/ -m "not pve_integration and not e2e" -q`
Expected: no failures. Watch specifically for `test_route_auth_invariant.py` and `test_health.py` — both boot the real app through the real lifespan, so a broken scheduler startup shows up there first.

- [ ] **Step 11: Commit**

```bash
git add backend/proxploy/jobs/ backend/proxploy/config.py backend/proxploy/main.py backend/proxploy/services/metrics.py backend/tests/
git commit -m "feat(scheduler): tick loop in the lifespan, seeded system schedules, metrics maintenance as a job

Retires the silent metrics_loop lifespan task — doc 04 requires pruning to
run as a scheduled system job visible in the activity feed."
```

---

## Task 3: `/schedules` CRUD API

**Files:**
- Create: `backend/proxploy/api/schedules.py`
- Modify: `backend/proxploy/api/__init__.py`
- Test: `backend/tests/test_schedules_api.py`

**Interfaces:**
- Consumes: Task 1's `validate`, `next_fire`, `BadSchedule`; `api.deps.require_role`, `require_entitlement`, `get_db`; `api.jobs.enqueue_and_audit`, `job_out`; `services.audit.write_audit`.
- Produces, for Tasks 17 and 19:
  - `GET /api/v1/schedules` → `[{id, name, job_kind, cron, timezone, params, enabled, last_run_at, next_run_at, created_by}]` (viewer)
  - `POST /api/v1/schedules` → the same object, 201 (admin, `sched.windows`, plus `store.auto_update` when `job_kind == "app.update"`)
  - `PATCH /api/v1/schedules/{id}` → the same object (admin, same gates)
  - `DELETE /api/v1/schedules/{id}` → 204 (admin)
  - `POST /api/v1/schedules/{id}/run` → `{"job": {...job_out...}}`, 202 (operator)
- Doc 05 rows implemented verbatim, including the conditional entitlement.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_schedules_api.py`:

```python
"""Schedules CRUD (doc 05 §Schedules)."""
from proxploy.models import AuditEvent, Job, Schedule
from tests.support import make_app

from fastapi.testclient import TestClient


def _admin(client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    return csrf_header(client)


def _create(client, h, **over):
    body = {"name": "Nightly backup", "job_kind": "backup.run",
            "cron": "0 2 * * *", "timezone": "Europe/Berlin",
            "params": {"host_id": 1}}
    body.update(over)
    return client.post("/api/v1/schedules", json=body, headers=h)


def test_create_computes_next_run_at_and_audits(client, csrf_header, bootstrap_admin):
    h = _admin(client, csrf_header, bootstrap_admin)
    r = _create(client, h)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "Nightly backup"
    assert body["job_kind"] == "backup.run"
    assert body["enabled"] is True
    assert body["next_run_at"] is not None       # primed at write time
    assert body["last_run_at"] is None

    with client.app.state.sessionmaker() as db:
        row = db.get(Schedule, body["id"])
        assert row.timezone == "Europe/Berlin"
        assert row.created_by is not None        # user-created, unlike system rows
        assert db.query(AuditEvent).filter_by(
            action="schedule.create", target_id=row.id).count() == 1


def test_create_rejects_a_malformed_cron_with_422(client, csrf_header, bootstrap_admin):
    h = _admin(client, csrf_header, bootstrap_admin)
    r = _create(client, h, cron="every tuesday")
    assert r.status_code == 422
    assert "cron" in r.json()["detail"].lower()


def test_create_rejects_an_unknown_timezone_with_422(client, csrf_header, bootstrap_admin):
    h = _admin(client, csrf_header, bootstrap_admin)
    r = _create(client, h, timezone="Mars/Olympus")
    assert r.status_code == 422


def test_create_rejects_a_job_kind_with_no_handler(client, csrf_header, bootstrap_admin):
    """Otherwise the row seeds, ticks once, and silently disables itself."""
    h = _admin(client, csrf_header, bootstrap_admin)
    r = _create(client, h, job_kind="app.teleport")
    assert r.status_code == 422
    assert "app.teleport" in r.json()["detail"]


def test_patch_recomputes_next_run_at_only_when_the_trigger_changed(
        client, csrf_header, bootstrap_admin):
    h = _admin(client, csrf_header, bootstrap_admin)
    sid = _create(client, h).json()["id"]
    before = client.get("/api/v1/schedules").json()[0]["next_run_at"]

    # A name change must NOT move the firing time.
    r = client.patch(f"/api/v1/schedules/{sid}", json={"name": "Renamed"}, headers=h)
    assert r.status_code == 200
    assert r.json()["next_run_at"] == before
    assert r.json()["name"] == "Renamed"

    # A cron change must.
    r = client.patch(f"/api/v1/schedules/{sid}", json={"cron": "30 5 * * *"},
                     headers=h)
    assert r.status_code == 200
    assert r.json()["next_run_at"] != before


def test_disabling_clears_next_run_at_and_re_enabling_restores_it(
        client, csrf_header, bootstrap_admin):
    """A disabled row with a stale next_run_at in the past would fire the
    instant it is re-enabled, which is not what "enable" means."""
    h = _admin(client, csrf_header, bootstrap_admin)
    sid = _create(client, h).json()["id"]

    off = client.patch(f"/api/v1/schedules/{sid}", json={"enabled": False},
                       headers=h).json()
    assert off["enabled"] is False and off["next_run_at"] is None

    on = client.patch(f"/api/v1/schedules/{sid}", json={"enabled": True},
                      headers=h).json()
    assert on["enabled"] is True and on["next_run_at"] is not None


def test_patch_rejects_a_bad_cron_without_corrupting_the_stored_row(
        client, csrf_header, bootstrap_admin):
    h = _admin(client, csrf_header, bootstrap_admin)
    sid = _create(client, h).json()["id"]
    assert client.patch(f"/api/v1/schedules/{sid}", json={"cron": "nope"},
                        headers=h).status_code == 422
    with client.app.state.sessionmaker() as db:
        assert db.get(Schedule, sid).cron == "0 2 * * *"   # unchanged


def test_run_now_enqueues_the_schedules_job_and_stamps_last_run(
        client, csrf_header, bootstrap_admin):
    h = _admin(client, csrf_header, bootstrap_admin)
    sid = _create(client, h, job_kind="catalog.refresh", params={}).json()["id"]

    r = client.post(f"/api/v1/schedules/{sid}/run", headers=h)
    assert r.status_code == 202, r.text
    job = r.json()["job"]
    assert job["kind"] == "catalog.refresh"
    assert job["schedule_id"] == sid

    with client.app.state.sessionmaker() as db:
        assert db.get(Job, job["id"]).requested_by is not None   # a human asked
        assert db.get(Schedule, sid).last_run_at is not None


def test_run_now_does_not_move_next_run_at(client, csrf_header, bootstrap_admin):
    """"Run now" is an extra run, not a reschedule — the window still opens
    when the operator said it would."""
    h = _admin(client, csrf_header, bootstrap_admin)
    sid = _create(client, h, job_kind="catalog.refresh", params={}).json()["id"]
    before = client.get("/api/v1/schedules").json()[0]["next_run_at"]
    client.post(f"/api/v1/schedules/{sid}/run", headers=h)
    assert client.get("/api/v1/schedules").json()[0]["next_run_at"] == before


def test_delete_removes_the_row_and_audits(client, csrf_header, bootstrap_admin):
    h = _admin(client, csrf_header, bootstrap_admin)
    sid = _create(client, h).json()["id"]
    assert client.delete(f"/api/v1/schedules/{sid}", headers=h).status_code == 204
    with client.app.state.sessionmaker() as db:
        assert db.get(Schedule, sid) is None
        assert db.query(AuditEvent).filter_by(
            action="schedule.delete", target_id=sid).count() == 1


def test_unknown_id_is_404_on_every_verb(client, csrf_header, bootstrap_admin):
    h = _admin(client, csrf_header, bootstrap_admin)
    assert client.patch("/api/v1/schedules/9999", json={"name": "x"},
                        headers=h).status_code == 404
    assert client.delete("/api/v1/schedules/9999", headers=h).status_code == 404
    assert client.post("/api/v1/schedules/9999/run", headers=h).status_code == 404


def test_auto_update_entitlement_gates_app_update_schedules_only(
        tmp_path, csrf_header, bootstrap_admin):
    """Doc 05: `sched.windows`; `store.auto_update` when job_kind=app.update.
    A backup schedule must stay creatable when only auto-update is off."""
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        h = csrf_header(c)
        c.app.state.entitlements._features = {"sched.windows": True,
                                              "store.auto_update": False}
        blocked = c.post("/api/v1/schedules", headers=h, json={
            "name": "Auto update", "job_kind": "app.update", "cron": "0 3 * * 0",
            "timezone": "UTC", "params": {"app_id": 1}})
        assert blocked.status_code == 403
        assert blocked.json()["feature"] == "store.auto_update"

        allowed = c.post("/api/v1/schedules", headers=h, json={
            "name": "Nightly backup", "job_kind": "backup.run",
            "cron": "0 2 * * *", "timezone": "UTC", "params": {"host_id": 1}})
        assert allowed.status_code == 201


def test_sched_windows_entitlement_gates_every_write(tmp_path, csrf_header,
                                                     bootstrap_admin):
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        h = csrf_header(c)
        c.app.state.entitlements._features = {"sched.windows": False}
        r = c.post("/api/v1/schedules", headers=h, json={
            "name": "x", "job_kind": "catalog.refresh", "cron": "0 2 * * *",
            "timezone": "UTC", "params": {}})
        assert r.status_code == 403
        assert r.json()["feature"] == "sched.windows"


def test_entitlement_gate_runs_after_auth_not_before(tmp_path, csrf_header):
    """An anonymous caller gets 401, never a 403 that leaks which flags are on."""
    app = make_app(tmp_path)
    with TestClient(app) as c:
        h = csrf_header(c)
        c.app.state.entitlements._features = {}
        assert c.post("/api/v1/schedules", headers=h, json={}).status_code == 401
        assert c.get("/api/v1/schedules").status_code == 401
```

- [ ] **Step 2: Run it to verify it fails**

Run: `./.venv/bin/python -m pytest tests/test_schedules_api.py -q`
Expected: every test 404s — the router does not exist.

- [ ] **Step 3: Write the router**

Create `backend/proxploy/api/schedules.py`:

```python
"""Schedules CRUD (doc 05 §Schedules).

The `schedules` table is authoritative (doc 04) and `jobs/scheduler.py` reads
it every tick, so there is nothing to register or de-register here: a write
that lands is live within one tick. The only obligation is that a row this
router accepts must be one the tick can actually fire — hence `validate()` on
every write, rather than discovering a bad cron when the schedule silently
disables itself hours later.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from proxploy.api.deps import get_db, require_entitlement, require_role
from proxploy.api.jobs import job_out
from proxploy.jobs.scheduler import BadSchedule, next_fire, validate
from proxploy.models import Schedule, User, utcnow
from proxploy.services.audit import write_audit

router = APIRouter(prefix="/schedules", tags=["schedules"])

# One singleton per role so FastAPI's dependency cache collapses the
# route-level and parameter-level uses, and so auth/role always runs before
# require_entitlement (tests/test_route_auth_invariant.py).
_require_viewer = require_role("viewer")
_require_operator = require_role("operator")
_require_admin = require_role("admin")

# Doc 05: "`sched.windows`; `store.auto_update` when `job_kind=app.update`".
# Enforced in the body rather than as a route dependency because it depends on
# the payload — a dependency cannot see `job_kind`.
AUTO_UPDATE_KIND = "app.update"


class ScheduleIn(BaseModel):
    name: str
    job_kind: str
    cron: str
    timezone: str = "UTC"
    params: dict | None = None
    enabled: bool = True


class SchedulePatch(BaseModel):
    name: str | None = None
    job_kind: str | None = None
    cron: str | None = None
    timezone: str | None = None
    params: dict | None = None
    enabled: bool | None = None


def _iso(dt):
    return dt.isoformat() + "Z" if dt else None


def _out(s: Schedule) -> dict:
    return {"id": s.id, "name": s.name, "job_kind": s.job_kind, "cron": s.cron,
            "timezone": s.timezone, "params": s.params or {},
            "enabled": s.enabled, "created_by": s.created_by,
            "last_run_at": _iso(s.last_run_at), "next_run_at": _iso(s.next_run_at)}


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _get(db, schedule_id: int) -> Schedule:
    row = db.get(Schedule, schedule_id)
    if row is None:
        raise HTTPException(404, "schedule not found")
    return row


def _check_auto_update(request: Request, job_kind: str) -> None:
    if (job_kind == AUTO_UPDATE_KIND
            and not request.app.state.entitlements.enabled("store.auto_update")):
        raise HTTPException(403, {"error": "entitlement_required",
                                  "feature": "store.auto_update"})


def _validated(cron: str, tz: str, job_kind: str) -> None:
    try:
        validate(cron, tz, job_kind)
    except BadSchedule as e:
        raise HTTPException(422, str(e)) from e


@router.get("", dependencies=[Depends(_require_viewer)])
def list_schedules(db=Depends(get_db), user: User = Depends(_require_viewer)):
    return [_out(s) for s in db.query(Schedule).order_by(Schedule.id).all()]


@router.post("", status_code=201,
             dependencies=[Depends(_require_admin),
                           Depends(require_entitlement("sched.windows"))])
def create_schedule(request: Request, body: ScheduleIn, db=Depends(get_db),
                    user: User = Depends(_require_admin)):
    _check_auto_update(request, body.job_kind)
    _validated(body.cron, body.timezone, body.job_kind)
    row = Schedule(name=body.name, job_kind=body.job_kind, cron=body.cron,
                   timezone=body.timezone, params=body.params or {},
                   enabled=body.enabled, created_by=user.id)
    # Primed at write time so the row is live on the very next tick rather than
    # waiting for `prime()` to notice it.
    if row.enabled:
        row.next_run_at = next_fire(row.cron, row.timezone, utcnow())
    db.add(row)
    db.commit()
    write_audit(db, actor_type="user", actor_id=user.id, action="schedule.create",
                target_type="schedule", target_id=row.id,
                params={"name": row.name, "job_kind": row.job_kind,
                        "cron": row.cron, "timezone": row.timezone},
                ip=_ip(request))
    return _out(row)


@router.patch("/{schedule_id}",
              dependencies=[Depends(_require_admin),
                            Depends(require_entitlement("sched.windows"))])
def patch_schedule(request: Request, schedule_id: int, body: SchedulePatch,
                   db=Depends(get_db), user: User = Depends(_require_admin)):
    row = _get(db, schedule_id)
    cron = body.cron if body.cron is not None else row.cron
    tz = body.timezone if body.timezone is not None else row.timezone
    kind = body.job_kind if body.job_kind is not None else row.job_kind
    enabled = body.enabled if body.enabled is not None else row.enabled

    _check_auto_update(request, kind)
    # Validate BEFORE mutating: a rejected PATCH must leave the stored row
    # exactly as it was, not half-applied.
    _validated(cron, tz, kind)

    trigger_changed = (cron, tz) != (row.cron, row.timezone)
    was_enabled = row.enabled

    row.name = body.name if body.name is not None else row.name
    row.job_kind, row.cron, row.timezone, row.enabled = kind, cron, tz, enabled
    if body.params is not None:
        row.params = body.params

    if not enabled:
        # A stale past next_run_at would fire the instant it is re-enabled.
        row.next_run_at = None
    elif trigger_changed or not was_enabled or row.next_run_at is None:
        row.next_run_at = next_fire(cron, tz, utcnow())
    db.commit()
    write_audit(db, actor_type="user", actor_id=user.id, action="schedule.update",
                target_type="schedule", target_id=row.id,
                params={"name": row.name, "cron": row.cron,
                        "timezone": row.timezone, "enabled": row.enabled},
                ip=_ip(request))
    return _out(row)


@router.delete("/{schedule_id}", status_code=204,
               dependencies=[Depends(_require_admin)])
def delete_schedule(request: Request, schedule_id: int, db=Depends(get_db),
                    user: User = Depends(_require_admin)):
    row = _get(db, schedule_id)
    name, kind = row.name, row.job_kind
    # jobs.schedule_id is a plain nullable FK with no ON DELETE — historical
    # job rows must survive their schedule, so unlink rather than cascade.
    from proxploy.models import Job
    (db.query(Job).filter(Job.schedule_id == schedule_id)
     .update({"schedule_id": None}, synchronize_session=False))
    db.delete(row)
    db.commit()
    write_audit(db, actor_type="user", actor_id=user.id, action="schedule.delete",
                target_type="schedule", target_id=schedule_id,
                params={"name": name, "job_kind": kind}, ip=_ip(request))
    return Response(status_code=204)


@router.post("/{schedule_id}/run", status_code=202,
             dependencies=[Depends(_require_operator)])
def run_schedule_now(request: Request, schedule_id: int, db=Depends(get_db),
                     user: User = Depends(_require_operator)):
    """An extra run, not a reschedule: `next_run_at` deliberately does not move.

    Unlike a tick-fired run this one carries `requested_by` — a human asked for
    it, and the audit trail should say so.
    """
    row = _get(db, schedule_id)
    _check_auto_update(request, row.job_kind)
    params = dict(row.params or {})
    from proxploy.jobs.scheduler import _target

    target_type, target_id = _target(params)
    try:
        job = request.app.state.jobs.enqueue(
            db, kind=row.job_kind, target_type=target_type, target_id=target_id,
            params=params, requested_by=user.id, schedule_id=row.id)
    except KeyError as e:
        raise HTTPException(422, f"no job handler for kind {row.job_kind!r}") from e
    row.last_run_at = utcnow()
    db.commit()
    write_audit(db, actor_type="user", actor_id=user.id, action="schedule.run",
                target_type="schedule", target_id=row.id, job_id=job.id,
                params={"name": row.name, "job_kind": row.job_kind},
                ip=_ip(request))
    return {"job": job_out(job)}
```

- [ ] **Step 4: Register the router**

In `backend/proxploy/api/__init__.py`, add `schedules` to the import tuple and add `api_router.include_router(schedules.router)` after the `jobs.router` line:

```python
from proxploy.api import (apps, audit, auth, backups, catalog, cluster, consoles,
                          entitlements, events, hosts, jobs, meta, metrics, network,
                          notifications, schedules, settings, storage, vms)
...
api_router.include_router(jobs.router)
api_router.include_router(schedules.router)
```

- [ ] **Step 5: Run the tests**

Run: `./.venv/bin/python -m pytest tests/test_schedules_api.py tests/test_route_auth_invariant.py -q`
Expected: PASS, 14 new tests.

- [ ] **Step 6: Run the full suite**

Run: `./.venv/bin/python -m pytest tests/ -m "not pve_integration and not e2e" -q`
Expected: no failures.

- [ ] **Step 7: Commit**

```bash
git add backend/proxploy/api/schedules.py backend/proxploy/api/__init__.py backend/tests/test_schedules_api.py
git commit -m "feat(schedules): CRUD + run-now, validated against the tick's own cron parser

A row this router accepts is one the scheduler can actually fire — bad cron,
unknown tz and unregistered job kinds are 422s at write time rather than a
schedule that silently disables itself hours later."
```

---

## Task 4: `update_available` detection

**Files:**
- Modify: `backend/proxploy/services/appstore.py` (add `mark_updates_available`; clear the flag in `run_install`)
- Modify: `backend/proxploy/services/catalog.py` (call it at the end of `refresh_catalog`)
- Test: `backend/tests/test_app_updates_detect.py`

**Interfaces:**
- Consumes: `proxploy.models.App`, `AppScript`, `CatalogEntry`.
- Produces, for Tasks 5, 6, 7 and 18:
  - `mark_updates_available(db) -> dict` → `{"marked": int, "cleared": int}`. Sets `App.update_available` to the **short (7-char) upstream commit SHA** an update would move the app to, or `None` when it is current.
  - `pinned_ref(db, app_id) -> str | None` — the `upstream_ref` of the app's newest `app_scripts` row.

**Design note — what "update available" can honestly mean here.** community-scripts entries carry no version number; `catalog_entries` pins an immutable commit (`upstream_sha`) and `app_scripts` records the commit each app was installed from (`upstream_ref`). The only truthful signal available is *upstream has moved since this app was pinned*. So `update_available` holds the short SHA the app would move to, and doc 06's "Update to vX" renders as "Update to a1b2c3d". Anything version-shaped would be invented.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_app_updates_detect.py`:

```python
"""`apps.update_available` detection (doc 05 GET /apps/{id}, doc 06 badge).

community-scripts publishes no version numbers, so the only honest signal is
"the pinned commit is behind the catalog's current commit".
"""
from proxploy.models import App, AppScript, CatalogEntry, Host
from proxploy.services.appstore import mark_updates_available, pinned_ref
from tests.support import make_db, seed_host_row


def _entry(db, slug="redis", sha="a" * 40):
    db.add(CatalogEntry(slug=slug, name=slug, script_path=f"ct/{slug}.sh",
                        upstream_sha=sha, installable=True,
                        raw={"install_script": "#!/bin/bash\n"}))
    db.commit()


def _app(db, host, slug="redis", ctid=101, ref="a" * 40, version=1):
    a = App(host_id=host.id, ctid=ctid, name=slug, slug=f"{slug}-{host.id}-{ctid}",
            catalog_slug=slug, web_protocol="http", web_path="/", adopted=True)
    db.add(a)
    db.flush()
    if ref is not None:
        db.add(AppScript(app_id=a.id, version=version, content="x",
                         content_sha256="0" * 64, source="upstream",
                         upstream_ref=ref))
    db.commit()
    return a


def test_pinned_ref_reads_the_newest_script_version(tmp_path):
    db = make_db(tmp_path)
    host = seed_host_row(db)
    _entry(db)
    a = _app(db, host, ref="a" * 40)
    db.add(AppScript(app_id=a.id, version=2, content="y", content_sha256="1" * 64,
                     source="edited", upstream_ref="b" * 40))
    db.commit()
    assert pinned_ref(db, a.id) == "b" * 40


def test_marks_an_app_whose_upstream_moved(tmp_path):
    db = make_db(tmp_path)
    host = seed_host_row(db)
    _entry(db, sha="b" * 40)                     # catalog moved on ...
    a = _app(db, host, ref="a" * 40)             # ... app still pinned to the old one

    assert mark_updates_available(db) == {"marked": 1, "cleared": 0}
    db.refresh(a)
    assert a.update_available == "b" * 7         # short sha, doc 06 "Update to vX"


def test_leaves_a_current_app_alone(tmp_path):
    db = make_db(tmp_path)
    host = seed_host_row(db)
    _entry(db, sha="a" * 40)
    a = _app(db, host, ref="a" * 40)

    assert mark_updates_available(db) == {"marked": 0, "cleared": 0}
    db.refresh(a)
    assert a.update_available is None


def test_clears_the_flag_once_the_app_catches_up(tmp_path):
    """The flag is derived state, not a latch — an app that updated (or whose
    catalog entry rolled back) must stop advertising an update."""
    db = make_db(tmp_path)
    host = seed_host_row(db)
    _entry(db, sha="a" * 40)
    a = _app(db, host, ref="a" * 40)
    a.update_available = "b" * 7
    db.commit()

    assert mark_updates_available(db) == {"marked": 0, "cleared": 1}
    db.refresh(a)
    assert a.update_available is None


def test_ignores_an_adopted_app_with_no_catalog_slug(tmp_path):
    """A hand-rolled CT adopted in Phase 4 has no upstream to compare against."""
    db = make_db(tmp_path)
    host = seed_host_row(db)
    a = App(host_id=host.id, ctid=110, name="custom", slug="custom-1-110",
            catalog_slug=None, web_protocol="http", web_path="/", adopted=True)
    db.add(a)
    db.commit()

    assert mark_updates_available(db) == {"marked": 0, "cleared": 0}
    db.refresh(a)
    assert a.update_available is None


def test_ignores_an_app_with_no_pinned_script(tmp_path):
    """Adopted apps have no app_scripts row — there is no "from" commit, so
    there is no honest diff to offer."""
    db = make_db(tmp_path)
    host = seed_host_row(db)
    _entry(db, sha="b" * 40)
    a = _app(db, host, ref=None)

    assert mark_updates_available(db) == {"marked": 0, "cleared": 0}
    db.refresh(a)
    assert a.update_available is None


def test_ignores_a_catalog_entry_with_no_pinned_sha(tmp_path):
    db = make_db(tmp_path)
    host = seed_host_row(db)
    db.add(CatalogEntry(slug="redis", name="redis", script_path="ct/redis.sh",
                        upstream_sha=None, installable=True))
    db.commit()
    a = _app(db, host, ref="a" * 40)

    assert mark_updates_available(db) == {"marked": 0, "cleared": 0}
    db.refresh(a)
    assert a.update_available is None


def test_catalog_refresh_marks_updates_when_it_finishes(tmp_path, monkeypatch):
    """Refresh is the only moment the answer can change, so it is the only
    place this needs to run."""
    import asyncio

    from proxploy.jobs import JobBackend, JobContext
    from proxploy.models import Job
    from proxploy.services import catalog
    from tests.support import make_job_app

    async def go():
        app = make_job_app(tmp_path)
        app.state.jobs = JobBackend(app)
        with app.state.sessionmaker() as db:
            host = seed_host_row(db)
            _entry(db, sha="a" * 40)
            a = _app(db, host, ref="a" * 40)
            app_id = a.id
            job = Job(kind="catalog.refresh", status="running")
            db.add(job)
            db.commit()
            job_id = job.id

        def fake_ingest(db, slugs):
            row = db.query(CatalogEntry).filter_by(slug="redis").one()
            row.upstream_sha = "c" * 40           # upstream moved
            db.commit()
            return {"synced": 1, "failed": [], "upstream_sha": "c" * 40}

        monkeypatch.setattr(catalog, "run_ingest", fake_ingest)
        ctx = JobContext(app.state.jobs, job_id)
        out = await catalog.refresh_catalog(ctx, {"slugs": ["redis"]})
        assert out["updates_marked"] == 1

        with app.state.sessionmaker() as db:
            assert db.get(App, app_id).update_available == "c" * 7

    asyncio.run(go())
```

- [ ] **Step 2: Run it to verify it fails**

Run: `./.venv/bin/python -m pytest tests/test_app_updates_detect.py -q`
Expected: `ImportError: cannot import name 'mark_updates_available'`.

- [ ] **Step 3: Implement the detection**

In `backend/proxploy/services/appstore.py`, add above `run_install`:

```python
SHORT_SHA = 7


def pinned_ref(db, app_id: int) -> str | None:
    """The upstream commit the app's newest saved script came from."""
    latest = (db.query(AppScript).filter_by(app_id=app_id)
              .order_by(AppScript.version.desc()).first())
    return latest.upstream_ref if latest else None


def mark_updates_available(db) -> dict:
    """Recompute `apps.update_available` for every app. Blocking.

    community-scripts publishes no version numbers (doc 01 §3), so the only
    honest signal is "the commit this app was pinned to is behind the commit
    the catalog now holds". The column stores the SHORT sha an update would
    move the app to, which is what doc 06's "Update to vX" renders.

    This is DERIVED state, recomputed wholesale rather than latched: an app
    that updated, or whose catalog entry was rolled back, must stop advertising
    an update. `cleared` counts exactly that.

    Skipped, each for a reason rather than as an oversight:
      - no `catalog_slug` — a hand-rolled CT adopted in Phase 4 has no upstream;
      - no `app_scripts` row — an adopted app has no "from" commit, so there is
        no diff to show and nothing to consent to;
      - catalog entry with no `upstream_sha` — never successfully refreshed.
    """
    shas = {c.slug: c.upstream_sha
            for c in db.query(CatalogEntry.slug, CatalogEntry.upstream_sha).all()}
    marked = cleared = 0
    for a in db.query(App).all():
        want = None
        upstream = shas.get(a.catalog_slug) if a.catalog_slug else None
        if upstream:
            ref = pinned_ref(db, a.id)
            if ref and ref != upstream:
                want = upstream[:SHORT_SHA]
        if want == a.update_available:
            continue
        if want:
            marked += 1
        else:
            cleared += 1
        a.update_available = want
    db.commit()
    return {"marked": marked, "cleared": cleared}
```

`CatalogEntry` and `App` are already imported at the top of `appstore.py`; `AppScript` too.

- [ ] **Step 4: Clear the flag on a fresh install**

In `run_install`, in the `with app.state.sessionmaker() as db:` block that creates the `App` row, add `update_available=None` to the `App(...)` constructor call — a just-installed app is by definition current with the commit it was installed from:

```python
        row = App(host_id=host_id, ctid=ctid, name=name, slug=slug,
                  catalog_slug=catalog_slug, category=entry.category,
                  web_protocol="http", web_path="/", adopted=True,
                  update_available=None)
```

- [ ] **Step 5: Call it from `catalog.refresh`**

In `backend/proxploy/services/catalog.py`, inside `refresh_catalog`, replace the block from `with app.state.sessionmaker() as db:` through the `ctx.progress(100)` line with:

```python
    with app.state.sessionmaker() as db:
        result = await asyncio.to_thread(run_ingest, db, slugs)
    ctx.log(f"pinned to upstream commit {result['upstream_sha']}")
    # ctx.log only runs on the event loop (every other handler does the same),
    # so per-slug failures are narrated here rather than from inside the thread.
    for f in result["failed"]:
        ctx.log(f"{f['slug']}: {f['reason']}", stream="stderr")
    ctx.log(f"synced {result['synced']}, failed {len(result['failed'])}")

    # A refresh is the ONLY moment `update_available` can change, so it is the
    # only place this has to run — no separate sweep, no separate schedule.
    def _mark():
        with app.state.sessionmaker() as db:
            return mark_updates_available(db)

    counts = await asyncio.to_thread(_mark)
    result["updates_marked"] = counts["marked"]
    result["updates_cleared"] = counts["cleared"]
    ctx.log(f"{counts['marked']} app(s) have an update available")
    if counts["marked"] or counts["cleared"]:
        app.state.bus.publish("resource", {"type": "app", "change": "list"})
    ctx.progress(100)
    return result
```

Add the import at the top of `catalog.py`, **inside** the function body rather than at module level:

```python
    from proxploy.services.appstore import mark_updates_available
```

> Why a local import: `services/appstore.py` imports `raw_url` from `services/catalog.py`, so a module-level import back the other way is a cycle. `appstore` is already fully imported by the time any `catalog.refresh` job runs (main.py's lifespan imports both), so the local import costs nothing.

- [ ] **Step 6: Run the tests**

Run: `./.venv/bin/python -m pytest tests/test_app_updates_detect.py tests/test_catalog_ingest.py tests/test_appstore_install.py -q`
Expected: PASS, 8 new tests, nothing existing broken.

- [ ] **Step 7: Run the full suite and commit**

Run: `./.venv/bin/python -m pytest tests/ -m "not pve_integration and not e2e" -q`

```bash
git add backend/proxploy/services/appstore.py backend/proxploy/services/catalog.py backend/tests/test_app_updates_detect.py
git commit -m "feat(store): derive apps.update_available from pinned-vs-catalog commit

community-scripts has no version numbers; the pinned commit falling behind
the catalog's is the only honest 'update available' signal. Recomputed
wholesale on every catalog refresh so it clears as well as sets."
```

---

## Task 5: `app.update` job handler

**Files:**
- Modify: `backend/proxploy/services/appstore.py` (add `run_update`, register `HANDLERS["app.update"]`)
- Test: `backend/tests/test_app_update_job.py`

**Interfaces:**
- Consumes: Task 4's `pinned_ref`; `SSHExecutor`, `client_for_host`, `raw_url`, `JobFailed`, `JobContext`.
- Produces, for Tasks 3, 6, 7 and 19:
  - Job kind `app.update`, params `{"app_id": int}`.
  - Result `{"app_id": int, "from_ref": str, "to_ref": str, "script_version": int}`.

**The two guards, and why they exist.** A community-scripts `ct/<slug>.sh` decides for itself whether it is installing or updating — `build.func`'s `start` routes to the script's `update_script()` when it finds the container, and to `build_container` when it does not. Proxploy cannot see inside that decision, and the failure mode when it goes the wrong way is a **second container silently created** and an `apps` row now pointing at the wrong CT. So:

1. **Preflight** — the app's CTID must be present on the host before the script runs. If it is not, the script would install fresh, and the job fails instead with a message that says exactly that.
2. **Post-check** — the set of LXC ids on the host is captured before and after. A new id appearing means the script took the install branch anyway; the job fails loudly and names the stray CTID so an operator can clean it up. It is a detector, not a preventer — see the residual limitation below, which Task 19 records in `docs/notes/phase-7-operate.md`.

**Residual limitation (deliberately not solved here, stated rather than hidden).** Whether a given entry's update path runs non-interactively is a property of that upstream script, not of Proxploy. `services/classifier.py` classifies *install* feasibility only. An update path that prompts will abort under `catch_errors`' `set -Ee`, and the job fails with the full transcript archived — the honest outcome, and the same one the classifier's install-side guarantee produces. Classifying update paths separately is real work for a later phase, not a line of code to sneak in here.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_app_update_job.py`:

```python
"""`app.update` — same pin/stream/archive path as install (doc 10 Phase 7)."""
import asyncio

import pytest

from proxploy.jobs import HANDLERS, JobBackend, JobContext, JobFailed
from proxploy.models import App, AppScript, CatalogEntry, Host, HostCredential, Job
from tests.fakes.pve import FakePVE
from tests.support import make_job_app, seed_host_row


def _seed(app, *, ctid=101, pinned="a" * 40, upstream="b" * 40):
    with app.state.sessionmaker() as db:
        host = seed_host_row(db)
        blob, ver = app.state.secretstore.encrypt(
            b'{"token_id": "root@pam!t", "token_secret": "s"}')
        db.add(HostCredential(host_id=host.id, kind="api_token",
                              encrypted_blob=blob, key_version=ver))
        db.add(CatalogEntry(slug="redis", name="Redis", script_path="ct/redis.sh",
                            upstream_sha=upstream, installable=True,
                            raw={"install_script": "#!/bin/bash\n"}))
        a = App(host_id=host.id, ctid=ctid, name="Redis", slug=f"redis-{host.id}-{ctid}",
                catalog_slug="redis", web_protocol="http", web_path="/",
                adopted=True, update_available=upstream[:7])
        db.add(a)
        db.flush()
        db.add(AppScript(app_id=a.id, version=1, content="#!/bin/bash\n",
                         content_sha256="0" * 64, source="upstream",
                         upstream_ref=pinned))
        db.commit()
        return host.id, a.id


def _job(app, app_id):
    with app.state.sessionmaker() as db:
        j = Job(kind="app.update", status="running", target_type="app",
                target_id=app_id, params={"app_id": app_id})
        db.add(j)
        db.commit()
        return j.id


def _ssh(recorder, exit_status=0, lines=("updating...",)):
    """asyncssh connect factory stand-in matching tests/fakes/ssh.py's contract."""
    from tests.fakes.ssh import make_ssh_factory
    return make_ssh_factory(recorder, exit_status=exit_status, lines=lines)


def test_update_runs_the_new_pinned_commit_and_advances_the_script_pin(tmp_path):
    async def go():
        fake = FakePVE()
        fake.add_ct(101, node="pve1", name="redis", status="running")
        cmds: list[str] = []
        app = make_job_app(tmp_path, fake=fake, ssh_factory=_ssh(cmds))
        app.state.jobs = JobBackend(app)
        host_id, app_id = _seed(app)

        ctx = JobContext(app.state.jobs, _job(app, app_id))
        out = await HANDLERS["app.update"](ctx, {"app_id": app_id})

        assert out["from_ref"] == "a" * 40
        assert out["to_ref"] == "b" * 40
        # Pinned to the NEW commit, never to `main` — same rule as install.
        assert "b" * 40 in cmds[0]
        assert "/main/" not in cmds[0].split("build.func")[0]

        with app.state.sessionmaker() as db:
            a = db.get(App, app_id)
            assert a.update_available is None          # cleared on success
            latest = (db.query(AppScript).filter_by(app_id=app_id)
                      .order_by(AppScript.version.desc()).first())
            assert latest.version == 2
            assert latest.upstream_ref == "b" * 40
            assert latest.source == "upstream"
        assert out["script_version"] == 2

    asyncio.run(go())


def test_update_refuses_when_the_container_is_missing(tmp_path):
    """Without this the script takes its install branch and builds a SECOND
    container while the apps row keeps pointing at the old CTID."""
    async def go():
        fake = FakePVE()                              # no CT 101 anywhere
        cmds: list[str] = []
        app = make_job_app(tmp_path, fake=fake, ssh_factory=_ssh(cmds))
        app.state.jobs = JobBackend(app)
        _, app_id = _seed(app)

        ctx = JobContext(app.state.jobs, _job(app, app_id))
        with pytest.raises(JobFailed) as e:
            await HANDLERS["app.update"](ctx, {"app_id": app_id})
        assert "101" in str(e.value)
        assert cmds == []                             # nothing ever ran over SSH

    asyncio.run(go())


def test_update_fails_loudly_if_a_new_container_appeared(tmp_path):
    """The post-check. The script decided to install; say so and name the CTID
    rather than report success over a stray container."""
    async def go():
        fake = FakePVE()
        fake.add_ct(101, node="pve1", name="redis", status="running")
        cmds: list[str] = []

        def on_run(_cmd):
            fake.add_ct(999, node="pve1", name="redis", status="running")

        app = make_job_app(tmp_path, fake=fake,
                           ssh_factory=_ssh(cmds, lines=("done",)))
        app.state.jobs = JobBackend(app)
        _, app_id = _seed(app)
        # The fake SSH factory calls this after recording the command.
        app.state.ssh_after_run = on_run

        ctx = JobContext(app.state.jobs, _job(app, app_id))
        with pytest.raises(JobFailed) as e:
            await HANDLERS["app.update"](ctx, {"app_id": app_id})
        assert "999" in str(e.value)

    asyncio.run(go())


def test_a_nonzero_exit_fails_the_job_and_leaves_the_pin_alone(tmp_path):
    async def go():
        fake = FakePVE()
        fake.add_ct(101, node="pve1", name="redis", status="running")
        cmds: list[str] = []
        app = make_job_app(tmp_path, fake=fake, ssh_factory=_ssh(cmds, exit_status=2))
        app.state.jobs = JobBackend(app)
        _, app_id = _seed(app)

        ctx = JobContext(app.state.jobs, _job(app, app_id))
        with pytest.raises(JobFailed) as e:
            await HANDLERS["app.update"](ctx, {"app_id": app_id})
        assert "exited 2" in str(e.value)

        with app.state.sessionmaker() as db:
            a = db.get(App, app_id)
            assert a.update_available == "b" * 7      # still offered, correctly
            assert db.query(AppScript).filter_by(app_id=app_id).count() == 1

    asyncio.run(go())


def test_update_refuses_an_app_already_on_the_catalog_commit(tmp_path):
    async def go():
        fake = FakePVE()
        fake.add_ct(101, node="pve1", name="redis", status="running")
        cmds: list[str] = []
        app = make_job_app(tmp_path, fake=fake, ssh_factory=_ssh(cmds))
        app.state.jobs = JobBackend(app)
        _, app_id = _seed(app, pinned="a" * 40, upstream="a" * 40)

        ctx = JobContext(app.state.jobs, _job(app, app_id))
        with pytest.raises(JobFailed) as e:
            await HANDLERS["app.update"](ctx, {"app_id": app_id})
        assert "already" in str(e.value).lower()
        assert cmds == []

    asyncio.run(go())


def test_update_refuses_an_app_with_no_catalog_entry(tmp_path):
    async def go():
        fake = FakePVE()
        fake.add_ct(101, node="pve1", name="custom", status="running")
        app = make_job_app(tmp_path, fake=fake, ssh_factory=_ssh([]))
        app.state.jobs = JobBackend(app)
        with app.state.sessionmaker() as db:
            host = seed_host_row(db)
            a = App(host_id=host.id, ctid=101, name="custom", slug="custom-1-101",
                    catalog_slug=None, web_protocol="http", web_path="/",
                    adopted=True)
            db.add(a)
            db.commit()
            app_id = a.id

        ctx = JobContext(app.state.jobs, _job(app, app_id))
        with pytest.raises(JobFailed) as e:
            await HANDLERS["app.update"](ctx, {"app_id": app_id})
        assert "catalog" in str(e.value).lower()

    asyncio.run(go())


def test_a_missing_credential_reports_as_a_failed_job_not_a_handler_bug(tmp_path):
    """ProxmoxError -> JobFailed, matching every Phase 6 handler."""
    async def go():
        fake = FakePVE()
        fake.add_ct(101, node="pve1", name="redis", status="running")
        app = make_job_app(tmp_path, fake=fake, ssh_factory=_ssh([]))
        app.state.jobs = JobBackend(app)
        _, app_id = _seed(app)
        with app.state.sessionmaker() as db:
            db.query(HostCredential).delete()
            db.commit()

        ctx = JobContext(app.state.jobs, _job(app, app_id))
        with pytest.raises(JobFailed):
            await HANDLERS["app.update"](ctx, {"app_id": app_id})

    asyncio.run(go())
```

> **Before writing the implementation**, open `backend/tests/fakes/ssh.py` and `backend/tests/fakes/pve.py` and check the real helper names — `make_ssh_factory`, `FakePVE.add_ct` and the `ssh_after_run` hook above are the *shapes* these tests need, not necessarily the names that exist. `tests/test_appstore_install.py` already drives `run_install` through both fakes; copy its exact idiom and adjust the `_ssh` / `_seed` helpers above to match. If `FakePVE` has no `add_ct`, add one (a fake gaining a method is fine; a test contorting around a missing one is not). If there is no post-run hook, add the smallest one that lets a test mutate the fake between the SSH call and the post-check.

- [ ] **Step 2: Run it to verify it fails**

Run: `./.venv/bin/python -m pytest tests/test_app_update_job.py -q`
Expected: `KeyError: 'app.update'`.

- [ ] **Step 3: Write the handler**

At the bottom of `backend/proxploy/services/appstore.py`, above the existing `HANDLERS["app.install"] = run_install` line:

```python
def _resolve_update(app, app_id: int):
    """Blocking: (app row fields, host row fields, catalog entry fields).

    Plain dicts, not ORM objects: the session closes when this returns and the
    caller runs for minutes afterwards. Same reason services/backupjobs.py's
    `_backup_target` returns a dict.
    """
    with app.state.sessionmaker() as db:
        a = db.get(App, app_id)
        if a is None:
            raise JobFailed(f"app {app_id} not found")
        if not a.catalog_slug:
            raise JobFailed(f"{a.name} was adopted, not installed from the catalog "
                            f"— there is no upstream script to update it with")
        entry = db.query(CatalogEntry).filter_by(slug=a.catalog_slug).one_or_none()
        if entry is None:
            raise JobFailed(f"catalog entry {a.catalog_slug} not found; "
                            f"refresh the catalog first")
        if not entry.upstream_sha:
            raise JobFailed(f"{a.catalog_slug} has no pinned upstream commit; "
                            f"refresh the catalog before updating")
        from_ref = pinned_ref(db, app_id)
        if from_ref is None:
            raise JobFailed(f"{a.name} has no pinned script; there is no commit "
                            f"to update from")
        if from_ref == entry.upstream_sha:
            raise JobFailed(f"{a.name} is already on upstream commit "
                            f"{from_ref[:SHORT_SHA]}")
        host = db.get(Host, a.host_id)
        if host is None:
            raise JobFailed(f"host {a.host_id} not found")
        return (
            {"id": a.id, "name": a.name, "ctid": a.ctid, "host_id": a.host_id},
            {"id": host.id, "name": host.name, "address": host.address,
             "fingerprint": host.ssh_host_key_fingerprint},
            {"slug": entry.slug, "sha": entry.upstream_sha,
             "script_path": entry.script_path,
             "install_script": (entry.raw or {}).get("install_script", ""),
             "from_ref": from_ref},
        )


def _lxc_ids(app, host_id: int) -> set[int]:
    """Blocking: every LXC id currently on the host, straight from PVE.

    One `/cluster/resources` call — the same read the poller makes. Deliberately
    NOT the poller's cached snapshot: this is a safety check, and a cache up to
    30 s stale is exactly what would miss a container created seconds ago.
    """
    with app.state.sessionmaker() as db:
        host = db.get(Host, host_id)
        if host is None:
            raise JobFailed(f"host {host_id} not found")
        try:
            client = client_for_host(app, db, host)
            rows = client.cluster_resources()
        except ProxmoxError as e:
            raise JobFailed(str(e)) from e
    return {int(r["vmid"]) for r in rows if r.get("type") == "lxc"}


async def run_update(ctx: JobContext, params: dict) -> dict:
    """`app.update` — re-run the app's catalog script, pinned to the CURRENT
    upstream commit, over the same SSH path install uses (doc 10 Phase 7:
    "same pin/diff/consent/stream/archive path as install").

    Consent and the upstream diff are the API layer's job (Task 6), exactly as
    install splits them; this handler assumes both were obtained.

    Two guards bracket the SSH run. A community-scripts `ct/*.sh` decides for
    itself whether it is installing or updating — `build.func`'s `start` routes
    to `update_script()` when it finds the container and to `build_container()`
    when it does not — and Proxploy cannot see inside that decision. The
    failure mode when it goes the wrong way is a second container built while
    the `apps` row still points at the first. So the CT must exist BEFORE
    (otherwise the script would certainly install fresh), and no new CT may
    exist AFTER (otherwise it installed anyway, and the job must say so rather
    than report success over a stray container).

    RESIDUAL LIMITATION, stated rather than hidden: whether a given entry's
    update path is non-interactive is a property of that upstream script.
    services/classifier.py classifies INSTALL feasibility only. An update path
    that prompts aborts under `catch_errors`' `set -Ee` and this job fails with
    the full transcript archived — the honest outcome. Classifying update paths
    is separate, larger work; see docs/notes/phase-7-operate.md.
    """
    app = ctx.backend.app
    app_id = int(params["app_id"])

    a, host, entry = await asyncio.to_thread(_resolve_update, app, app_id)

    ctx.log(f"updating {a['name']} (CT {a['ctid']}) on {host['name']}: "
            f"{entry['from_ref'][:SHORT_SHA]} -> {entry['sha'][:SHORT_SHA]}")

    before = await asyncio.to_thread(_lxc_ids, app, a["host_id"])
    if a["ctid"] not in before:
        raise JobFailed(
            f"CT {a['ctid']} is not present on {host['name']} — refusing to run "
            f"the catalog script, which would install a NEW container rather "
            f"than update this one")
    ctx.progress(10)

    executor = SSHExecutor(connect_factory=app.state.ssh_connect_factory)

    def on_new_fingerprint(fp: str) -> None:
        with app.state.sessionmaker() as db:
            h = db.get(Host, a["host_id"])
            if h is not None:
                h.ssh_host_key_fingerprint = fp
                db.commit()

    # Pinned to the exact commit that was ingested and classified, never to
    # `main` — identical rule and identical raw_url() helper as run_install,
    # and it carries the same one-level-down residual: the pinned script's own
    # `source <(curl ... /main/misc/build.func)` line is frozen text but still
    # fetches live. See docs/notes/phase-4-store.md.
    command = f"bash -c \"$(curl -fsSL {raw_url(entry['sha'], entry['script_path'])})\""
    env = {"MODE": "default", "PHS_SILENT": "1"}
    try:
        status = await executor.run_for_host(
            app.state.sessionmaker, app.state.secretstore, a["host_id"],
            host["address"], command,
            pinned_fingerprint=host["fingerprint"],
            on_new_fingerprint=on_new_fingerprint, env=env,
            on_line=lambda stream, line: ctx.log(line, stream=stream),
        )
    except LookupError as e:
        raise JobFailed(str(e)) from e
    if status != 0:
        raise JobFailed(f"update script exited {status}")
    ctx.progress(80)

    after = await asyncio.to_thread(_lxc_ids, app, a["host_id"])
    strays = sorted(after - before)
    if strays:
        raise JobFailed(
            f"the catalog script created new container(s) {strays} instead of "
            f"updating CT {a['ctid']} — {a['name']} was NOT updated, and "
            f"{'CT ' + str(strays[0]) if len(strays) == 1 else 'those CTs'} "
            f"should be reviewed and removed by hand")
    if a["ctid"] not in after:
        raise JobFailed(f"CT {a['ctid']} disappeared during the update")

    # The pin advances only now, on a run that provably updated this container.
    def _record() -> int:
        with app.state.sessionmaker() as db:
            row = db.get(App, app_id)
            latest = (db.query(AppScript).filter_by(app_id=app_id)
                      .order_by(AppScript.version.desc()).first())
            version = (latest.version + 1) if latest else 1
            content = entry["install_script"]
            db.add(AppScript(app_id=app_id, version=version, content=content,
                             content_sha256=hashlib.sha256(
                                 content.encode()).hexdigest(),
                             source="upstream", upstream_ref=entry["sha"]))
            if row is not None:
                row.update_available = None
            db.commit()
            return version

    version = await asyncio.to_thread(_record)
    ctx.progress(100)
    app.state.bus.publish("resource", {"type": "app", "id": app_id,
                                       "change": "updated"})
    return {"app_id": app_id, "from_ref": entry["from_ref"], "to_ref": entry["sha"],
            "script_version": version}


HANDLERS["app.update"] = run_update
```

Add to `appstore.py`'s imports at the top:

```python
from proxploy.services.hostclient import client_for_host
from proxploy.services.proxmox import ProxmoxError
```

- [ ] **Step 4: Register the handler at boot**

In `backend/proxploy/main.py`, the existing `from proxploy.services import appstore as _appstore  # noqa: F401 — registers app.install` line now registers both; update the comment to `# noqa: F401 — registers app.install / app.update`.

- [ ] **Step 5: Run the tests**

Run: `./.venv/bin/python -m pytest tests/test_app_update_job.py tests/test_appstore_install.py -q`
Expected: PASS, 7 new tests.

- [ ] **Step 6: Run the full suite and commit**

Run: `./.venv/bin/python -m pytest tests/ -m "not pve_integration and not e2e" -q`

```bash
git add backend/proxploy/services/appstore.py backend/proxploy/main.py backend/tests/
git commit -m "feat(store): app.update job — pinned re-run with before/after CT guards

A community-scripts ct/*.sh chooses install-vs-update itself; the CT must
exist first and no new CT may appear after, or the job fails and names the
stray container rather than reporting success over it."
```

---

## Task 6: `GET /apps/{id}/update` and `POST /apps/{id}/update`

**Files:**
- Modify: `backend/proxploy/api/apps.py`
- Test: `backend/tests/test_app_update_api.py`

**Interfaces:**
- Consumes: Task 4's `mark_updates_available`/`pinned_ref`, Task 5's `app.update` handler, `api.jobs.enqueue_and_audit`, `api.apps._diff_vs_upstream`.
- Produces, for Tasks 7 and 18:
  - `GET /api/v1/apps/{id}/update` → `{"update_available": str|None, "from_ref": str|None, "to_ref": str|None, "diff_vs_upstream": str|None}` (operator, `store.updates`)
  - `POST /api/v1/apps/{id}/update` body `{"consent": bool}` → `{"job": {...}}`, 202 (operator, `store.update`)

**Placement.** Both go **above** the `POST /{app_id}/{action}` lifecycle wildcard, next to the existing `/{app_id}/script` routes and under the same WARNING comment — Starlette matches in registration order and `/{app_id}/{action}` would otherwise swallow `POST /{app_id}/update`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_app_update_api.py`:

```python
"""GET/POST /apps/{id}/update (doc 05 §Apps)."""
from fastapi.testclient import TestClient

from proxploy.models import App, AppScript, AuditEvent, CatalogEntry, Job
from tests.support import make_app, seed_host_row


def _seed(c, *, pinned="a" * 40, upstream="b" * 40, slug="redis", ctid=101):
    with c.app.state.sessionmaker() as db:
        host = seed_host_row(db)
        db.add(CatalogEntry(slug=slug, name="Redis", script_path=f"ct/{slug}.sh",
                            upstream_sha=upstream, installable=True,
                            raw={"install_script": "#!/bin/bash\nNEW\n"}))
        a = App(host_id=host.id, ctid=ctid, name="Redis",
                slug=f"{slug}-{host.id}-{ctid}", catalog_slug=slug,
                web_protocol="http", web_path="/", adopted=True,
                update_available=upstream[:7] if pinned != upstream else None)
        db.add(a)
        db.flush()
        db.add(AppScript(app_id=a.id, version=1, content="#!/bin/bash\nOLD\n",
                         content_sha256="0" * 64, source="upstream",
                         upstream_ref=pinned))
        db.commit()
        return a.id


def test_get_update_reports_the_two_commits_and_the_diff(client, csrf_header,
                                                         bootstrap_admin):
    bootstrap_admin(client)
    app_id = _seed(client)
    r = client.get(f"/api/v1/apps/{app_id}/update")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["update_available"] == "b" * 7
    assert body["from_ref"] == "a" * 40
    assert body["to_ref"] == "b" * 40
    assert "OLD" in body["diff_vs_upstream"] and "NEW" in body["diff_vs_upstream"]


def test_get_update_on_a_current_app_reports_no_update(client, csrf_header,
                                                       bootstrap_admin):
    bootstrap_admin(client)
    app_id = _seed(client, pinned="a" * 40, upstream="a" * 40)
    body = client.get(f"/api/v1/apps/{app_id}/update").json()
    assert body["update_available"] is None
    assert body["to_ref"] == "a" * 40
    assert body["diff_vs_upstream"] is None


def test_get_update_404s_an_unknown_app(client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    assert client.get("/api/v1/apps/9999/update").status_code == 404


def test_post_update_requires_explicit_consent(client, csrf_header, bootstrap_admin):
    """Same root-consent gate as install (api/catalog.py) — this runs a
    community script as root on the node."""
    bootstrap_admin(client)
    app_id = _seed(client)
    h = csrf_header(client)
    r = client.post(f"/api/v1/apps/{app_id}/update", json={"consent": False},
                    headers=h)
    assert r.status_code == 400
    assert "consent" in r.text.lower()
    with client.app.state.sessionmaker() as db:
        assert db.query(Job).count() == 0


def test_post_update_enqueues_and_audits(client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    app_id = _seed(client)
    h = csrf_header(client)
    r = client.post(f"/api/v1/apps/{app_id}/update", json={"consent": True},
                    headers=h)
    assert r.status_code == 202, r.text
    job = r.json()["job"]
    assert job["kind"] == "app.update"
    assert job["target_type"] == "app" and job["target_id"] == app_id
    with client.app.state.sessionmaker() as db:
        assert db.query(AuditEvent).filter_by(
            action="app.update", target_id=app_id).count() == 1


def test_post_update_refuses_when_there_is_nothing_to_update(client, csrf_header,
                                                             bootstrap_admin):
    """Rejected at the route, not four minutes later inside the job."""
    bootstrap_admin(client)
    app_id = _seed(client, pinned="a" * 40, upstream="a" * 40)
    h = csrf_header(client)
    r = client.post(f"/api/v1/apps/{app_id}/update", json={"consent": True},
                    headers=h)
    assert r.status_code == 409
    assert "up to date" in r.text.lower()


def test_post_update_404s_an_unknown_app(client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    h = csrf_header(client)
    assert client.post("/api/v1/apps/9999/update", json={"consent": True},
                       headers=h).status_code == 404


def test_update_routes_are_not_swallowed_by_the_lifecycle_wildcard(client,
                                                                   csrf_header,
                                                                   bootstrap_admin):
    """`POST /{app_id}/{action}` is registered later and would match
    `/{id}/update` as action="update" if ordering ever regressed."""
    bootstrap_admin(client)
    app_id = _seed(client)
    h = csrf_header(client)
    r = client.post(f"/api/v1/apps/{app_id}/update", json={"consent": True},
                    headers=h)
    assert r.json()["job"]["kind"] == "app.update"     # not "app.update" via lifecycle
    assert r.status_code == 202


def test_store_update_entitlement_gates_the_post(tmp_path, csrf_header,
                                                 bootstrap_admin):
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        app_id = _seed(c)
        h = csrf_header(c)
        c.app.state.entitlements._features = {"store.updates": True,
                                              "store.update": False}
        r = c.post(f"/api/v1/apps/{app_id}/update", json={"consent": True},
                   headers=h)
        assert r.status_code == 403
        assert r.json()["feature"] == "store.update"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `./.venv/bin/python -m pytest tests/test_app_update_api.py -q`
Expected: 404s / 405s — the routes do not exist.

- [ ] **Step 3: Write the routes**

In `backend/proxploy/api/apps.py`, immediately after the `list_app_script_versions` function (i.e. still above the network routes and well above the lifecycle wildcard), add:

```python
class UpdateIn(BaseModel):
    consent: bool = False


def _update_state(db, app_id: int) -> tuple[App, CatalogEntry | None, str | None]:
    a = db.get(App, app_id)
    if a is None:
        raise HTTPException(404, "app not found")
    entry = (db.query(CatalogEntry).filter_by(slug=a.catalog_slug).one_or_none()
             if a.catalog_slug else None)
    latest = (db.query(AppScript).filter_by(app_id=app_id)
              .order_by(AppScript.version.desc()).first())
    return a, entry, (latest.upstream_ref if latest else None)


@router.get("/{app_id}/update",
            dependencies=[Depends(_require_operator),
                          Depends(require_entitlement("store.updates"))])
def get_app_update(app_id: int, db=Depends(get_db)):
    """What an update would do: which commit to which, and the script diff.

    Doc 10 Phase 7 requires the same diff/consent surface install has, so the
    diff shown here is the SAME `_diff_vs_upstream` the Config tab renders —
    one implementation, one answer, no chance of the two disagreeing about
    what is about to run.
    """
    a, entry, from_ref = _update_state(db, app_id)
    latest = (db.query(AppScript).filter_by(app_id=app_id)
              .order_by(AppScript.version.desc()).first())
    return {
        "update_available": a.update_available,
        "from_ref": from_ref,
        "to_ref": entry.upstream_sha if entry else None,
        "diff_vs_upstream": (_diff_vs_upstream(db, a, latest.content)
                             if latest else None),
    }


@router.post("/{app_id}/update", status_code=202,
             dependencies=[Depends(_require_operator),
                           Depends(require_entitlement("store.update"))])
def update_app(app_id: int, body: UpdateIn, request: Request, db=Depends(get_db),
               user: User = Depends(_require_operator)):
    """Root-consent gated, exactly like install (api/catalog.py::install_catalog_entry).

    This re-runs a community script as root on the node — brief §8 says the
    honest thing is to make the operator say so out loud, and an update is no
    less privileged than the install was.
    """
    if not body.consent:
        raise HTTPException(400, "root-consent required: this runs a community "
                                 "script as root on the node")
    a, entry, from_ref = _update_state(db, app_id)
    if entry is None or not entry.upstream_sha or from_ref is None:
        raise HTTPException(409, "no upstream script is pinned for this app; "
                                 "refresh the catalog first")
    if from_ref == entry.upstream_sha:
        raise HTTPException(409, f"{a.name} is already up to date")
    return enqueue_and_audit(request, db, user, kind="app.update",
                             target_type="app", target_id=app_id,
                             params={"app_id": app_id})
```

`enqueue_and_audit` is already imported in `apps.py` via `from proxploy.api.jobs import job_out` — change that line to `from proxploy.api.jobs import enqueue_and_audit, job_out`.

- [ ] **Step 4: Run the tests**

Run: `./.venv/bin/python -m pytest tests/test_app_update_api.py tests/test_lifecycle_api.py tests/test_route_auth_invariant.py -q`
Expected: PASS, 9 new tests. `test_lifecycle_api.py` is the canary for the wildcard-ordering rule.

- [ ] **Step 5: Run the full suite and commit**

```bash
git add backend/proxploy/api/apps.py backend/tests/test_app_update_api.py
git commit -m "feat(apps): GET/POST /apps/{id}/update with the install path's consent + diff gate"
```

---

## Task 7: `POST /apps/update-all`

**Files:**
- Modify: `backend/proxploy/api/apps.py`
- Test: `backend/tests/test_app_update_all.py`

**Interfaces:**
- Consumes: Task 6's `_update_state`, `enqueue_and_audit`.
- Produces, for Task 18:
  - `POST /api/v1/apps/update-all` body `{"consent": bool}` → `{"jobs": [job_out…], "skipped": [{"app_id", "name", "reason"}]}`, 202 (operator, `store.update_all`).

**Placement.** Literal `/update-all` must be registered **before** `GET /{app_id}` and before the lifecycle wildcard, or `{app_id}` swallows it. Put it directly beneath the existing `POST /adopt` route, which sits there for exactly the same reason.

**Concurrency.** No new queue: `JobBackend.MAX_CONCURRENT` is 4, so N enqueued `app.update` jobs already run four at a time with the rest genuinely `queued`. Doc 05's "per-app results" is the job list — each job carries its own status, transcript and result.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_app_update_all.py`:

```python
"""POST /apps/update-all (doc 05 §Apps, doc 06 cluster "Update all")."""
from fastapi.testclient import TestClient

from proxploy.models import App, AppScript, AuditEvent, CatalogEntry, Job
from tests.support import make_app, seed_host_row


def _seed_app(db, host, slug, ctid, pinned, upstream):
    if db.query(CatalogEntry).filter_by(slug=slug).one_or_none() is None:
        db.add(CatalogEntry(slug=slug, name=slug, script_path=f"ct/{slug}.sh",
                            upstream_sha=upstream, installable=True,
                            raw={"install_script": "#!/bin/bash\n"}))
    a = App(host_id=host.id, ctid=ctid, name=slug, slug=f"{slug}-{host.id}-{ctid}",
            catalog_slug=slug, web_protocol="http", web_path="/", adopted=True,
            update_available=upstream[:7] if pinned != upstream else None)
    db.add(a)
    db.flush()
    db.add(AppScript(app_id=a.id, version=1, content="x", content_sha256="0" * 64,
                     source="upstream", upstream_ref=pinned))
    db.commit()
    return a.id


def _seed(c):
    with c.app.state.sessionmaker() as db:
        host = seed_host_row(db)
        stale = _seed_app(db, host, "redis", 101, "a" * 40, "b" * 40)
        current = _seed_app(db, host, "gitea", 102, "c" * 40, "c" * 40)
        # adopted, no catalog slug and no script row
        orphan = App(host_id=host.id, ctid=103, name="custom",
                     slug="custom-1-103", catalog_slug=None, web_protocol="http",
                     web_path="/", adopted=True)
        db.add(orphan)
        db.commit()
        return stale, current, orphan.id


def test_update_all_enqueues_only_the_stale_apps(client, csrf_header,
                                                 bootstrap_admin):
    bootstrap_admin(client)
    stale, current, orphan = _seed(client)
    h = csrf_header(client)
    r = client.post("/api/v1/apps/update-all", json={"consent": True}, headers=h)
    assert r.status_code == 202, r.text
    body = r.json()
    assert [j["target_id"] for j in body["jobs"]] == [stale]
    assert all(j["kind"] == "app.update" for j in body["jobs"])
    with client.app.state.sessionmaker() as db:
        assert db.query(Job).count() == 1


def test_update_all_reports_why_each_app_was_skipped(client, csrf_header,
                                                     bootstrap_admin):
    """A silent "0 updated" is indistinguishable from a broken endpoint."""
    bootstrap_admin(client)
    stale, current, orphan = _seed(client)
    h = csrf_header(client)
    body = client.post("/api/v1/apps/update-all", json={"consent": True},
                       headers=h).json()
    skipped = {s["app_id"]: s["reason"] for s in body["skipped"]}
    assert set(skipped) == {current, orphan}
    assert "up to date" in skipped[current]
    assert "catalog" in skipped[orphan]


def test_update_all_requires_consent(client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    _seed(client)
    h = csrf_header(client)
    r = client.post("/api/v1/apps/update-all", json={"consent": False}, headers=h)
    assert r.status_code == 400
    with client.app.state.sessionmaker() as db:
        assert db.query(Job).count() == 0


def test_update_all_writes_one_audit_row_per_job(client, csrf_header,
                                                 bootstrap_admin):
    bootstrap_admin(client)
    stale, _, _ = _seed(client)
    h = csrf_header(client)
    client.post("/api/v1/apps/update-all", json={"consent": True}, headers=h)
    with client.app.state.sessionmaker() as db:
        rows = db.query(AuditEvent).filter_by(action="app.update").all()
        assert len(rows) == 1
        assert rows[0].target_id == stale
        assert rows[0].job_id is not None


def test_update_all_with_nothing_stale_is_an_empty_202_not_an_error(
        client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    h = csrf_header(client)
    r = client.post("/api/v1/apps/update-all", json={"consent": True}, headers=h)
    assert r.status_code == 202
    assert r.json() == {"jobs": [], "skipped": []}


def test_update_all_is_not_matched_as_an_app_id(client, csrf_header,
                                                bootstrap_admin):
    """`/apps/{app_id}` would parse "update-all" as an id if ordering
    regressed — FastAPI would 422 on the int coercion."""
    bootstrap_admin(client)
    h = csrf_header(client)
    assert client.post("/api/v1/apps/update-all", json={"consent": True},
                       headers=h).status_code == 202


def test_store_update_all_entitlement_gates_it(tmp_path, csrf_header,
                                               bootstrap_admin):
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        _seed(c)
        h = csrf_header(c)
        c.app.state.entitlements._features = {"store.update": True,
                                              "store.update_all": False}
        r = c.post("/api/v1/apps/update-all", json={"consent": True}, headers=h)
        assert r.status_code == 403
        assert r.json()["feature"] == "store.update_all"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `./.venv/bin/python -m pytest tests/test_app_update_all.py -q`
Expected: 422 — `update-all` is being parsed as `{app_id}`.

- [ ] **Step 3: Write the route**

In `backend/proxploy/api/apps.py`, directly after the `adopt_apps` function (and therefore before `GET /{app_id}`), add:

```python
# Literal segment, registered ahead of `GET /{app_id}` and the lifecycle
# wildcard: `{app_id}` would otherwise try to parse "update-all" as an int.
@router.post("/update-all", status_code=202,
             dependencies=[Depends(_require_operator),
                           Depends(require_entitlement("store.update_all"))])
def update_all_apps(body: UpdateIn, request: Request, db=Depends(get_db),
                    user: User = Depends(_require_operator)):
    """One `app.update` job per stale app (doc 05: "per-app results").

    No new queue machinery: JobBackend.MAX_CONCURRENT already runs four at a
    time and genuinely queues the rest, and each job carries its own status,
    transcript and result — which is what "per-app results" means.

    `skipped` is not decoration. A bare "0 jobs started" is indistinguishable
    from a broken endpoint, so every app that did not get a job says why.
    """
    if not body.consent:
        raise HTTPException(400, "root-consent required: this runs community "
                                 "scripts as root on your nodes")
    jobs, skipped = [], []
    for a in db.query(App).order_by(App.id).all():
        if not a.catalog_slug:
            skipped.append({"app_id": a.id, "name": a.name,
                            "reason": "adopted, not installed from the catalog"})
            continue
        entry = db.query(CatalogEntry).filter_by(slug=a.catalog_slug).one_or_none()
        latest = (db.query(AppScript).filter_by(app_id=a.id)
                  .order_by(AppScript.version.desc()).first())
        if entry is None or not entry.upstream_sha or latest is None:
            skipped.append({"app_id": a.id, "name": a.name,
                            "reason": "no pinned upstream script; refresh the catalog"})
            continue
        if latest.upstream_ref == entry.upstream_sha:
            skipped.append({"app_id": a.id, "name": a.name, "reason": "up to date"})
            continue
        jobs.append(enqueue_and_audit(request, db, user, kind="app.update",
                                      target_type="app", target_id=a.id,
                                      params={"app_id": a.id})["job"])
    return {"jobs": jobs, "skipped": skipped}
```

`UpdateIn` is defined in Task 6 further down the file. Move its `class UpdateIn(BaseModel)` definition up so it sits **above** `update_all_apps` — put it next to the existing `class AdoptIn` / `class ScriptIn` model definitions near the top of the module.

- [ ] **Step 4: Run the tests**

Run: `./.venv/bin/python -m pytest tests/test_app_update_all.py tests/test_apps_adopt.py tests/test_apps_vms_api.py -q`
Expected: PASS, 7 new tests, nothing existing broken.

- [ ] **Step 5: Run the full suite and commit**

```bash
git add backend/proxploy/api/apps.py backend/tests/test_app_update_all.py
git commit -m "feat(apps): POST /apps/update-all — one job per stale app, with per-app skip reasons"
```

---

## Task 8: Persist `mem_pct` and `disk_pct` samples

**Files:**
- Modify: `backend/proxploy/pollers/__init__.py` (`ingest_cycle`)
- Modify: `backend/proxploy/services/metrics.py` (`METRICS` tuple)
- Test: `backend/tests/test_poller_ingest.py` (extend)

**Interfaces:**
- Produces, for Task 9: `metric_samples` rows with `metric` in `{"mem_pct", "disk_pct"}`, alongside the existing `cpu_pct`, `mem_bytes`, `net_in_bps`, `net_out_bps`.

**Why this task exists.** Doc 04 names the `alert_rules.metric` enum as `cpu_pct | mem_pct | disk_pct | host_offline | backup_failed`. Verified against the poller: `ingest_cycle` writes **only** `cpu_pct` and `mem_bytes` per target (plus `net_in_bps`/`net_out_bps` for hosts) — there is no `mem_pct` and no `disk_pct` sample anywhere in the database. A memory or disk rule built on top of today's poller would be created successfully, sit `enabled`, and never fire. `mem_pct` is already *computed* every cycle by `_mem_pct()` for the SSE `targets` payload; it is simply thrown away instead of persisted. This task persists it and adds the host disk aggregate. It is a prerequisite for Task 9, not a nice-to-have.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_poller_ingest.py`:

```python
def test_ingest_persists_mem_pct_for_host_app_and_vm(tmp_path):
    """Doc 04's alert_rules.metric enum names mem_pct; without a sample by
    that name a memory rule is created, enabled, and never fires."""
    from proxploy.models import App, MetricSample, utcnow
    from proxploy.pollers import ingest_cycle
    from tests.support import make_db, seed_host_row

    db = make_db(tmp_path)
    host = seed_host_row(db, node="pve1")
    db.add(App(host_id=host.id, ctid=101, name="redis", slug="redis-1-101",
               web_protocol="http", web_path="/", adopted=True))
    db.commit()

    resources = [
        {"type": "node", "node": "pve1", "status": "online", "cpu": 0.5,
         "maxcpu": 8, "mem": 4_000_000_000, "maxmem": 8_000_000_000, "uptime": 100},
        {"type": "lxc", "vmid": 101, "node": "pve1", "name": "redis",
         "status": "running", "cpu": 0.1, "maxcpu": 1,
         "mem": 512_000_000, "maxmem": 1_024_000_000, "maxdisk": 0, "uptime": 50},
        {"type": "qemu", "vmid": 201, "node": "pve1", "name": "win",
         "status": "running", "cpu": 0.2, "maxcpu": 4,
         "mem": 2_000_000_000, "maxmem": 8_000_000_000, "maxdisk": 0, "uptime": 50},
    ]
    ingest_cycle(db, host, resources, {"pve1": []}, utcnow())

    got = {(s.target_type, s.metric): s.value
           for s in db.query(MetricSample).filter_by(metric="mem_pct").all()}
    assert got[("host", "mem_pct")] == 50.0      # 4G of 8G
    assert got[("app", "mem_pct")] == 50.0       # 512M of 1024M
    assert got[("vm", "mem_pct")] == 25.0        # 2G of 8G


def test_ingest_persists_a_host_disk_pct_from_its_datastores(tmp_path):
    from proxploy.models import MetricSample, utcnow
    from proxploy.pollers import ingest_cycle
    from tests.support import make_db, seed_host_row

    db = make_db(tmp_path)
    host = seed_host_row(db, node="pve1")
    resources = [
        {"type": "node", "node": "pve1", "status": "online", "cpu": 0.1,
         "maxcpu": 4, "mem": 1, "maxmem": 2, "uptime": 1},
        {"type": "storage", "storage": "local", "node": "pve1",
         "disk": 30, "maxdisk": 100, "shared": 0},
        {"type": "storage", "storage": "local", "node": "pve2",
         "disk": 10, "maxdisk": 100, "shared": 0},
        # shared datastore, reported once per node — must count ONCE
        {"type": "storage", "storage": "nfs", "node": "pve1",
         "disk": 60, "maxdisk": 200, "shared": 1},
        {"type": "storage", "storage": "nfs", "node": "pve2",
         "disk": 60, "maxdisk": 200, "shared": 1},
    ]
    ingest_cycle(db, host, resources, {"pve1": []}, utcnow())

    s = db.query(MetricSample).filter_by(metric="disk_pct").one()
    assert s.target_type == "host" and s.target_id == host.id
    # (30 + 10 + 60) / (100 + 100 + 200) = 25%
    assert s.value == 25.0


def test_disk_pct_is_zero_rather_than_a_crash_when_a_host_reports_no_storage(tmp_path):
    from proxploy.models import MetricSample, utcnow
    from proxploy.pollers import ingest_cycle
    from tests.support import make_db, seed_host_row

    db = make_db(tmp_path)
    host = seed_host_row(db, node="pve1")
    ingest_cycle(db, host, [
        {"type": "node", "node": "pve1", "status": "online", "cpu": 0.1,
         "maxcpu": 4, "mem": 1, "maxmem": 2, "uptime": 1}], {"pve1": []}, utcnow())
    assert db.query(MetricSample).filter_by(metric="disk_pct").one().value == 0.0


def test_mem_pct_and_disk_pct_are_queryable_metrics():
    """api/metrics.py rejects anything outside METRICS with a 422, so a chart
    of a metric the alert rules use would 422 without this."""
    from proxploy.services.metrics import METRICS
    assert "mem_pct" in METRICS
    assert "disk_pct" in METRICS
```

- [ ] **Step 2: Run it to verify it fails**

Run: `./.venv/bin/python -m pytest tests/test_poller_ingest.py -q`
Expected: `KeyError: ('host', 'mem_pct')` and `NoResultFound` on the disk_pct query.

- [ ] **Step 3: Widen the queryable metric list**

In `backend/proxploy/services/metrics.py`:

```python
# Phase 7 adds mem_pct and disk_pct: doc 04's alert_rules.metric enum names
# both, and api/metrics.py 422s any metric not listed here — so a chart of the
# very metric an alert fired on would have been unqueryable.
METRICS = ("cpu_pct", "mem_pct", "disk_pct", "mem_bytes", "disk_bytes",
           "net_in_bps", "net_out_bps", "io_read_bps", "io_write_bps")
```

- [ ] **Step 4: Persist the samples**

In `backend/proxploy/pollers/__init__.py`:

1. Add a helper next to `_mem_pct`:

```python
def _disk_pct(host_node: str, storage_rows: list[dict]) -> float:
    """Aggregate used/total across this host's datastores.

    Deduped correctly, unlike the cluster ring's deliberate shortcut in
    api/cluster.py::cluster_summary: a SHARED datastore is reported once per
    node and must count once, a LOCAL datastore with the same name on two
    nodes is two distinct pools. Doing it wrong here is not a cosmetic ring
    error — it is an alert that fires at the wrong number.
    """
    pools: dict[tuple, dict] = {}
    for r in storage_rows:
        key = (r.get("storage"),) if r.get("shared") else (r.get("node"),
                                                           r.get("storage"))
        pools[key] = r
    used = sum(int(r.get("disk") or 0) for r in pools.values())
    total = sum(int(r.get("maxdisk") or 0) for r in pools.values())
    return round(used / total * 100, 1) if total else 0.0
```

2. In the host block of `ingest_cycle`, extend the `for metric, value in (...)` tuple:

```python
    if own:
        for metric, value in (("cpu_pct", own["cpu_pct"]),
                              ("mem_bytes", float(own["mem_bytes"])),
                              ("mem_pct", _mem_pct(own["mem_bytes"],
                                                   own["mem_total_bytes"])),
                              ("disk_pct", _disk_pct(host.node_name, storage_rows)),
                              ("net_in_bps", net_in), ("net_out_bps", net_out)):
            samples.append(MetricSample(target_type="host", target_id=host.id,
                                        metric=metric, value=value, ts=now))
```

3. In the apps loop, after the two existing `samples.append(...)` calls:

```python
        samples.append(MetricSample(target_type="app", target_id=a.id,
                                    metric="mem_pct",
                                    value=_mem_pct(g["mem_bytes"],
                                                   g["mem_total_bytes"]), ts=now))
```

4. In the VM sampling loop, after its two existing `samples.append(...)` calls:

```python
        samples.append(MetricSample(target_type="vm", target_id=v.id,
                                    metric="mem_pct",
                                    value=_mem_pct(g["mem_bytes"],
                                                   g["mem_total_bytes"]), ts=now))
```

> No `disk_pct` for apps or VMs, deliberately. `/cluster/resources` reports `maxdisk` (allocated) for guests and a `disk` figure that is meaningful for LXC but routinely 0 for QEMU — a guest disk_pct would be silently wrong for every VM. Task 12's rule validation rejects `disk_pct` on `app`/`vm` targets with an explanatory 422 rather than accepting a rule that can never fire. `ponytail:` comment this in the code.

- [ ] **Step 5: Run the tests**

Run: `./.venv/bin/python -m pytest tests/test_poller_ingest.py tests/test_metrics_api.py tests/test_metrics_store.py -q`
Expected: PASS, 4 new tests.

- [ ] **Step 6: Run the full suite and commit**

```bash
git add backend/proxploy/pollers/__init__.py backend/proxploy/services/metrics.py backend/tests/test_poller_ingest.py
git commit -m "feat(metrics): persist mem_pct and host disk_pct samples

Doc 04's alert_rules.metric enum names both; the poller only ever wrote
cpu_pct and mem_bytes, so a memory or disk rule would have sat enabled and
never fired."
```

---

## Task 9: Alert evaluator core

**Files:**
- Create: `backend/proxploy/services/alerts.py`
- Test: `backend/tests/test_alerts_eval.py`

**Interfaces:**
- Consumes: `proxploy.models.{Alert, AlertRule, App, Backup, Host, Job, MetricSample, Vm, utcnow}`.
- Produces, for Tasks 10, 11, 12 and 13:
  - `METRIC_TARGETS: dict[str, tuple[str, ...]]` — which `target_type`s each metric supports.
  - `SUPPORTED_METRICS: tuple[str, ...]`
  - `Transition` — a plain dict `{"alert_id", "rule_id", "rule_name", "state", "severity", "target_type", "target_id", "target_label", "value", "message", "channel_ids"}`.
  - `evaluate(db, now) -> list[dict]` — blocking; opens/closes alerts and returns only the **transitions**, never the steady state.
  - `render_message(rule_name, label, metric, operator, threshold, duration_s, value, state) -> str`
  - `targets_for(db, rule) -> list[tuple[str, int, str]]` — `(target_type, target_id, label)`.

**Semantics, decided here so no task re-litigates them:**

- **`duration_s` means "has continuously breached for at least this long"**, not "the average over the window breached". Implementation walks samples newest-first, takes the breaching prefix, and fires when `now - oldest_of_prefix >= duration_s`. `duration_s=0` fires on the newest sample alone. A target with no samples never fires — absence of data is not a breach.
- **A rule fires at most one open alert per concrete target.** A second evaluation while it is still breaching produces no transition and no second notification.
- **Resolution is automatic**: the open alert flips to `resolved` the first cycle the condition stops holding. An acknowledged alert still resolves — ack silences, it does not pin.
- **`host_offline` and `backup_failed` ignore `operator` and `threshold`** (there is nothing to compare); `duration_s` still applies to `host_offline` via `hosts.last_seen_at`. Task 12 hides those inputs in the UI and does not validate them.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_alerts_eval.py`:

```python
"""Alert evaluation (doc 04 alert_rules/alerts, doc 10 Phase 7)."""
from datetime import timedelta

from proxploy.models import (Alert, AlertRule, App, Backup, Host, Job,
                             MetricSample, Vm, utcnow)
from proxploy.services.alerts import (METRIC_TARGETS, evaluate, render_message,
                                      targets_for)
from tests.support import make_db, seed_host_row


def _rule(db, **kw):
    kw.setdefault("name", "CPU high")
    kw.setdefault("metric", "cpu_pct")
    kw.setdefault("target_type", "host")
    kw.setdefault("operator", "gt")
    kw.setdefault("threshold", 85.0)
    kw.setdefault("duration_s", 0)
    kw.setdefault("severity", "warning")
    kw.setdefault("channel_ids", [])
    kw.setdefault("enabled", True)
    r = AlertRule(**kw)
    db.add(r)
    db.commit()
    return r


def _samples(db, target_type, target_id, metric, values, now, step_s=30):
    """values[0] is the NEWEST."""
    for i, v in enumerate(values):
        db.add(MetricSample(target_type=target_type, target_id=target_id,
                            metric=metric, value=float(v),
                            ts=now - timedelta(seconds=i * step_s)))
    db.commit()


# --- firing -----------------------------------------------------------------

def test_a_breach_with_no_duration_fires_immediately(tmp_path):
    db = make_db(tmp_path)
    host = seed_host_row(db)
    rule = _rule(db, target_id=host.id)
    now = utcnow()
    _samples(db, "host", host.id, "cpu_pct", [92.0], now)

    out = evaluate(db, now)
    assert len(out) == 1
    t = out[0]
    assert t["state"] == "firing"
    assert t["rule_id"] == rule.id
    assert t["target_type"] == "host" and t["target_id"] == host.id
    assert t["value"] == 92.0
    assert t["severity"] == "warning"
    assert db.query(Alert).filter_by(state="firing").count() == 1


def test_a_breach_shorter_than_duration_does_not_fire(tmp_path):
    """Two 30 s samples is one minute of breach, not five."""
    db = make_db(tmp_path)
    host = seed_host_row(db)
    _rule(db, target_id=host.id, duration_s=300)
    now = utcnow()
    _samples(db, "host", host.id, "cpu_pct", [92.0, 91.0], now)

    assert evaluate(db, now) == []
    assert db.query(Alert).count() == 0


def test_a_breach_held_for_the_full_duration_fires(tmp_path):
    db = make_db(tmp_path)
    host = seed_host_row(db)
    _rule(db, target_id=host.id, duration_s=300)
    now = utcnow()
    _samples(db, "host", host.id, "cpu_pct", [92.0] * 12, now)   # 11 * 30s = 330s

    out = evaluate(db, now)
    assert len(out) == 1 and out[0]["state"] == "firing"


def test_a_dip_inside_the_window_resets_the_clock(tmp_path):
    """"85% for 5 minutes" means continuously — one healthy sample two minutes
    ago means it has only been breaching for two minutes."""
    db = make_db(tmp_path)
    host = seed_host_row(db)
    _rule(db, target_id=host.id, duration_s=300)
    now = utcnow()
    _samples(db, "host", host.id, "cpu_pct",
             [92.0, 92.0, 92.0, 10.0, 92.0, 92.0, 92.0, 92.0, 92.0, 92.0, 92.0,
              92.0], now)

    assert evaluate(db, now) == []


def test_no_samples_is_never_a_breach(tmp_path):
    """Absence of data is not evidence of a problem."""
    db = make_db(tmp_path)
    host = seed_host_row(db)
    _rule(db, target_id=host.id)
    assert evaluate(db, utcnow()) == []


def test_the_lt_operator_fires_below_the_threshold(tmp_path):
    db = make_db(tmp_path)
    host = seed_host_row(db)
    _rule(db, metric="mem_pct", operator="lt", threshold=10.0, target_id=host.id)
    now = utcnow()
    _samples(db, "host", host.id, "mem_pct", [3.0], now)
    assert evaluate(db, now)[0]["state"] == "firing"


# --- idempotence and resolution --------------------------------------------

def test_a_still_breaching_rule_produces_no_second_transition(tmp_path):
    """Otherwise every 30 s poll re-notifies for the same problem."""
    db = make_db(tmp_path)
    host = seed_host_row(db)
    _rule(db, target_id=host.id)
    now = utcnow()
    _samples(db, "host", host.id, "cpu_pct", [92.0], now)

    assert len(evaluate(db, now)) == 1
    assert evaluate(db, now + timedelta(seconds=30)) == []
    assert db.query(Alert).count() == 1


def test_recovery_resolves_the_open_alert(tmp_path):
    db = make_db(tmp_path)
    host = seed_host_row(db)
    _rule(db, target_id=host.id)
    now = utcnow()
    _samples(db, "host", host.id, "cpu_pct", [92.0], now)
    evaluate(db, now)

    later = now + timedelta(seconds=60)
    _samples(db, "host", host.id, "cpu_pct", [20.0], later)
    out = evaluate(db, later)
    assert len(out) == 1 and out[0]["state"] == "resolved"

    a = db.query(Alert).one()
    assert a.state == "resolved" and a.resolved_at is not None
    # and it stays resolved — no re-resolve transition on the next cycle
    assert evaluate(db, later + timedelta(seconds=30)) == []


def test_an_acknowledged_alert_still_resolves(tmp_path):
    """Ack silences the noise; it does not pin the alert open."""
    db = make_db(tmp_path)
    host = seed_host_row(db)
    _rule(db, target_id=host.id)
    now = utcnow()
    _samples(db, "host", host.id, "cpu_pct", [92.0], now)
    evaluate(db, now)
    a = db.query(Alert).one()
    a.acked_by, a.acked_at = 1, now
    db.commit()

    later = now + timedelta(seconds=60)
    _samples(db, "host", host.id, "cpu_pct", [20.0], later)
    assert evaluate(db, later)[0]["state"] == "resolved"


def test_a_disabled_rule_is_not_evaluated_at_all(tmp_path):
    db = make_db(tmp_path)
    host = seed_host_row(db)
    _rule(db, target_id=host.id, enabled=False)
    now = utcnow()
    _samples(db, "host", host.id, "cpu_pct", [99.0], now)
    assert evaluate(db, now) == []


# --- target resolution ------------------------------------------------------

def test_target_any_expands_across_every_supported_target(tmp_path):
    db = make_db(tmp_path)
    host = seed_host_row(db)
    db.add(App(host_id=host.id, ctid=101, name="redis", slug="redis-1-101",
               web_protocol="http", web_path="/", adopted=True))
    db.add(Vm(host_id=host.id, vmid=201, name="win", status="running"))
    db.commit()
    rule = _rule(db, target_type="any", target_id=None)

    labels = {t[2] for t in targets_for(db, rule)}
    assert labels == {"host-01", "redis", "win"}


def test_target_any_fires_once_per_breaching_target(tmp_path):
    db = make_db(tmp_path)
    host = seed_host_row(db)
    db.add(App(host_id=host.id, ctid=101, name="redis", slug="redis-1-101",
               web_protocol="http", web_path="/", adopted=True))
    db.commit()
    app_id = db.query(App).one().id
    _rule(db, target_type="any", target_id=None)
    now = utcnow()
    _samples(db, "host", host.id, "cpu_pct", [92.0], now)
    _samples(db, "app", app_id, "cpu_pct", [10.0], now)     # healthy

    out = evaluate(db, now)
    assert len(out) == 1
    assert (out[0]["target_type"], out[0]["target_id"]) == ("host", host.id)


def test_disk_pct_only_ever_targets_hosts(tmp_path):
    """Guest disk figures from /cluster/resources are meaningless for QEMU, so
    the poller writes disk_pct for hosts only and this must match."""
    assert METRIC_TARGETS["disk_pct"] == ("host",)
    db = make_db(tmp_path)
    host = seed_host_row(db)
    db.add(App(host_id=host.id, ctid=101, name="redis", slug="redis-1-101",
               web_protocol="http", web_path="/", adopted=True))
    db.commit()
    rule = _rule(db, metric="disk_pct", target_type="any", target_id=None)
    assert {t[0] for t in targets_for(db, rule)} == {"host"}


def test_a_rule_pointing_at_a_deleted_target_is_skipped_not_crashed(tmp_path):
    db = make_db(tmp_path)
    _rule(db, target_type="host", target_id=4242)
    assert evaluate(db, utcnow()) == []


# --- status-backed metrics --------------------------------------------------

def test_host_offline_fires_on_an_unreachable_host(tmp_path):
    db = make_db(tmp_path)
    host = seed_host_row(db, status="unreachable")
    host.last_seen_at = utcnow() - timedelta(minutes=10)
    db.commit()
    _rule(db, name="Host down", metric="host_offline", target_id=host.id,
          duration_s=300, severity="critical")

    out = evaluate(db, utcnow())
    assert len(out) == 1
    assert out[0]["severity"] == "critical"
    assert "offline" in out[0]["message"].lower()


def test_host_offline_respects_duration_before_firing(tmp_path):
    """A 30 s blip during a PVE restart is not an outage."""
    db = make_db(tmp_path)
    host = seed_host_row(db, status="unreachable")
    host.last_seen_at = utcnow() - timedelta(seconds=30)
    db.commit()
    _rule(db, metric="host_offline", target_id=host.id, duration_s=300)
    assert evaluate(db, utcnow()) == []


def test_host_offline_resolves_when_the_host_comes_back(tmp_path):
    db = make_db(tmp_path)
    host = seed_host_row(db, status="unreachable")
    host.last_seen_at = utcnow() - timedelta(minutes=10)
    db.commit()
    _rule(db, metric="host_offline", target_id=host.id)
    now = utcnow()
    evaluate(db, now)

    host.status, host.last_seen_at = "connected", now
    db.commit()
    assert evaluate(db, now + timedelta(seconds=30))[0]["state"] == "resolved"


def test_backup_failed_fires_on_the_hosts_latest_failed_backup_job(tmp_path):
    db = make_db(tmp_path)
    host = seed_host_row(db)
    db.add(Job(kind="backup.run", status="failed", target_type="host",
               target_id=host.id, finished_at=utcnow()))
    db.commit()
    _rule(db, name="Backup failed", metric="backup_failed", target_id=host.id)

    out = evaluate(db, utcnow())
    assert len(out) == 1 and out[0]["state"] == "firing"


def test_backup_failed_does_not_fire_when_the_latest_run_succeeded(tmp_path):
    """Only the LATEST run matters — an old failure already fixed is not a
    live alert."""
    db = make_db(tmp_path)
    host = seed_host_row(db)
    old = utcnow() - timedelta(hours=2)
    db.add(Job(kind="backup.run", status="failed", target_type="host",
               target_id=host.id, finished_at=old))
    db.add(Job(kind="backup.run", status="succeeded", target_type="host",
               target_id=host.id, finished_at=utcnow()))
    db.commit()
    _rule(db, metric="backup_failed", target_id=host.id)
    assert evaluate(db, utcnow()) == []


# --- message rendering ------------------------------------------------------

def test_message_reads_like_the_doc_05_example(tmp_path):
    msg = render_message("CPU high", "host-02", "cpu_pct", "gt", 85.0, 300,
                         92.4, "firing")
    assert msg == "host-02 CPU > 85% for 5m (now 92.4%)"


def test_a_resolved_message_says_so(tmp_path):
    msg = render_message("CPU high", "host-02", "cpu_pct", "gt", 85.0, 300,
                         12.0, "resolved")
    assert msg.startswith("Resolved: ")
    assert "host-02" in msg


def test_one_bad_rule_does_not_stop_the_others(tmp_path):
    """A metric the evaluator does not know (a downgrade, a hand-edited row)
    must be skipped, not raised."""
    db = make_db(tmp_path)
    host = seed_host_row(db)
    _rule(db, name="nonsense", metric="phase_of_moon", target_id=host.id)
    _rule(db, name="real", metric="cpu_pct", target_id=host.id)
    now = utcnow()
    _samples(db, "host", host.id, "cpu_pct", [99.0], now)

    out = evaluate(db, now)
    assert [t["rule_name"] for t in out] == ["real"]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `./.venv/bin/python -m pytest tests/test_alerts_eval.py -q`
Expected: `ModuleNotFoundError: No module named 'proxploy.services.alerts'`.

- [ ] **Step 3: Write the evaluator**

Create `backend/proxploy/services/alerts.py`:

```python
"""Alert evaluation (doc 04 `alert_rules` / `alerts`, doc 10 Phase 7).

Reads only the DB. No HTTP, no Apprise, no event bus — it opens and closes
`alerts` rows and returns the TRANSITIONS. Task 10's notifier and Task 11's
poll-loop hook do everything outward-facing, so a change to how alerts are
delivered never touches how they are decided.

Semantics, once, so nothing has to guess:

  * `duration_s` means CONTINUOUSLY breaching for at least that long — the
    doc 04 prototype phrase is "85% CPU for 5 minutes", and a five-minute
    average that dipped to 10% in the middle is not that. Implemented by
    walking samples newest-first and taking the breaching prefix.
  * A rule holds at most ONE open alert per concrete target. A still-breaching
    rule yields no transition, which is what stops a 30 s poll cadence from
    re-notifying twice a minute.
  * Recovery resolves automatically on the first non-breaching cycle. An
    acknowledged alert still resolves — ack silences, it does not pin.
  * No samples is not a breach. Absence of data is not evidence of a problem,
    and a freshly-added host must not alarm on its first cycle.
  * `host_offline` and `backup_failed` have nothing to compare, so they ignore
    `operator` and `threshold`. `duration_s` still applies to `host_offline`
    (via `hosts.last_seen_at`) so a PVE restart blip is not an outage.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from proxploy.models import Alert, AlertRule, App, Host, Job, MetricSample, Vm, utcnow

logger = logging.getLogger(__name__)

# Which target kinds each metric can honestly be evaluated against. `disk_pct`
# is hosts-only: /cluster/resources reports `maxdisk` (allocated, not used) for
# guests and a `disk` figure that is routinely 0 for QEMU, so a guest disk_pct
# would be confidently wrong. api/alerts.py rejects the unsupported pairs at
# rule-creation time rather than accepting a rule that can never fire.
METRIC_TARGETS: dict[str, tuple[str, ...]] = {
    "cpu_pct": ("host", "app", "vm"),
    "mem_pct": ("host", "app", "vm"),
    "disk_pct": ("host",),
    "host_offline": ("host",),
    "backup_failed": ("host",),
}
SUPPORTED_METRICS: tuple[str, ...] = tuple(METRIC_TARGETS)

# Metrics answered from a status column rather than from metric_samples.
STATUS_METRICS = ("host_offline", "backup_failed")

# Extra history fetched beyond `duration_s` so the sample that ESTABLISHES the
# start of a breach is inside the window. Two poll intervals of slack.
_WINDOW_SLACK_S = 120

_METRIC_LABEL = {"cpu_pct": "CPU", "mem_pct": "memory", "disk_pct": "disk",
                 "host_offline": "host", "backup_failed": "backup"}
_OP_LABEL = {"gt": ">", "lt": "<"}


def _human_duration(seconds: int) -> str:
    if seconds <= 0:
        return ""
    if seconds % 3600 == 0:
        return f"{seconds // 3600}h"
    if seconds % 60 == 0:
        return f"{seconds // 60}m"
    return f"{seconds}s"


def render_message(rule_name: str, label: str, metric: str, operator: str,
                   threshold: float, duration_s: int, value: float | None,
                   state: str) -> str:
    """Doc 05's SSE example: "host-02 CPU > 85% for 5m"."""
    if metric == "host_offline":
        body = f"{label} is offline"
        if duration_s:
            body += f" for {_human_duration(duration_s)}"
    elif metric == "backup_failed":
        body = f"{label}: last backup run failed"
    else:
        unit = "%" if metric.endswith("_pct") else ""
        body = (f"{label} {_METRIC_LABEL.get(metric, metric)} "
                f"{_OP_LABEL.get(operator, operator)} "
                f"{threshold:g}{unit}")
        if duration_s:
            body += f" for {_human_duration(duration_s)}"
        if value is not None:
            body += f" (now {value:g}{unit})"
    return f"Resolved: {body}" if state == "resolved" else body


def targets_for(db, rule: AlertRule) -> list[tuple[str, int, str]]:
    """Concrete `(target_type, target_id, label)` triples this rule covers.

    `target_type == "any"` expands across every target kind the metric supports
    (doc 04: "`host` | `app` | `vm` | `any`", target_id NULL when any).
    """
    kinds = METRIC_TARGETS.get(rule.metric, ())
    if rule.target_type != "any":
        if rule.target_type not in kinds:
            return []
        label = _label(db, rule.target_type, rule.target_id)
        # A rule pointing at a deleted host/app/vm is skipped, not crashed —
        # nothing cascades alert_rules on target deletion.
        return [] if label is None else [(rule.target_type, rule.target_id, label)]

    out: list[tuple[str, int, str]] = []
    if "host" in kinds:
        out += [("host", h.id, h.name) for h in db.query(Host).all()]
    if "app" in kinds:
        out += [("app", a.id, a.name) for a in db.query(App).all()]
    if "vm" in kinds:
        out += [("vm", v.id, v.name) for v in db.query(Vm).all()]
    return out


def _label(db, target_type: str, target_id: int | None) -> str | None:
    if target_id is None:
        return None
    model = {"host": Host, "app": App, "vm": Vm}.get(target_type)
    row = db.get(model, target_id) if model else None
    return row.name if row is not None else None


def _breaches(value: float, operator: str, threshold: float) -> bool:
    return value > threshold if operator == "gt" else value < threshold


def _metric_state(db, rule: AlertRule, target_type: str, target_id: int,
                  now: datetime) -> tuple[bool, float | None]:
    """(breaching for long enough, newest observed value) from metric_samples.

    Walks newest-first and takes the breaching prefix; the rule fires when the
    oldest sample of that prefix is at least `duration_s` old. That is what
    "held for 5 minutes" means, and it is why a single dip resets the clock.
    """
    since = now - timedelta(seconds=rule.duration_s + _WINDOW_SLACK_S)
    rows = (db.query(MetricSample)
            .filter(MetricSample.target_type == target_type,
                    MetricSample.target_id == target_id,
                    MetricSample.metric == rule.metric,
                    MetricSample.ts >= since, MetricSample.ts <= now)
            .order_by(MetricSample.ts.desc())
            .all())
    if not rows:
        return False, None                      # no data is not a breach
    newest = rows[0].value
    prefix_start = None
    for row in rows:
        if not _breaches(row.value, rule.operator, rule.threshold):
            break
        prefix_start = row.ts
    if prefix_start is None:
        return False, newest
    held = (now - prefix_start).total_seconds()
    return held >= rule.duration_s, newest


def _status_state(db, rule: AlertRule, target_id: int,
                  now: datetime) -> tuple[bool, float | None]:
    if rule.metric == "host_offline":
        host = db.get(Host, target_id)
        if host is None or host.status == "connected":
            return False, 0.0
        # A PVE restart blips `unreachable` for one cycle; duration_s is how an
        # operator says "only tell me if it stays down".
        if rule.duration_s and host.last_seen_at is not None:
            down_for = (now - host.last_seen_at).total_seconds()
            if down_for < rule.duration_s:
                return False, 1.0
        return True, 1.0

    # backup_failed — only the LATEST finished backup.run for this host counts.
    # An old failure that has since been fixed is not a live alert.
    latest = (db.query(Job)
              .filter(Job.kind == "backup.run", Job.target_type == "host",
                      Job.target_id == target_id, Job.finished_at.is_not(None))
              .order_by(Job.finished_at.desc(), Job.id.desc())
              .first())
    if latest is None:
        return False, 0.0
    return latest.status == "failed", 1.0 if latest.status == "failed" else 0.0


def _open_alert(db, rule_id: int, target_type: str, target_id: int) -> Alert | None:
    return (db.query(Alert)
            .filter(Alert.rule_id == rule_id, Alert.state == "firing",
                    Alert.target_type == target_type,
                    Alert.target_id == target_id)
            .order_by(Alert.id.desc())
            .first())


def _transition(rule: AlertRule, alert: Alert, label: str, state: str) -> dict:
    return {"alert_id": alert.id, "rule_id": rule.id, "rule_name": rule.name,
            "state": state, "severity": rule.severity,
            "target_type": alert.target_type, "target_id": alert.target_id,
            "target_label": label, "value": alert.value,
            "message": alert.message, "channel_ids": list(rule.channel_ids or [])}


def evaluate(db, now: datetime | None = None) -> list[dict]:
    """One pass over every enabled rule. Blocking. Returns only transitions.

    ponytail: O(rules x targets) queries per pass, each one index-covered by
    `ix_samples(target_type, target_id, metric, ts)`. At the single-digit rule
    counts a self-hoster has this is a handful of queries every 30 s. If a
    fleet ever makes it hurt, the fix is one grouped query per (metric,
    duration) bucket rather than per target — not a different design.
    """
    now = now or utcnow()
    transitions: list[dict] = []
    for rule in db.query(AlertRule).filter(AlertRule.enabled.is_(True)).all():
        if rule.metric not in METRIC_TARGETS:
            # A metric this build does not know — a downgrade, or a row edited
            # by hand. Skip it; one unusable rule must not stop the others.
            logger.debug("alert rule %s: unknown metric %r", rule.id, rule.metric)
            continue
        for target_type, target_id, label in targets_for(db, rule):
            try:
                if rule.metric in STATUS_METRICS:
                    breaching, value = _status_state(db, rule, target_id, now)
                else:
                    breaching, value = _metric_state(db, rule, target_type,
                                                     target_id, now)
            except Exception:  # noqa: BLE001 — one bad target never stops the pass
                logger.debug("alert rule %s target %s:%s raised", rule.id,
                             target_type, target_id, exc_info=True)
                continue

            open_alert = _open_alert(db, rule.id, target_type, target_id)
            if breaching and open_alert is None:
                row = Alert(rule_id=rule.id, target_type=target_type,
                            target_id=target_id, state="firing", value=value,
                            message=render_message(rule.name, label, rule.metric,
                                                   rule.operator, rule.threshold,
                                                   rule.duration_s, value, "firing"),
                            fired_at=now)
                db.add(row)
                db.commit()
                transitions.append(_transition(rule, row, label, "firing"))
            elif not breaching and open_alert is not None:
                open_alert.state = "resolved"
                open_alert.resolved_at = now
                open_alert.value = value
                open_alert.message = render_message(
                    rule.name, label, rule.metric, rule.operator, rule.threshold,
                    rule.duration_s, value, "resolved")
                db.commit()
                transitions.append(_transition(rule, open_alert, label, "resolved"))
    return transitions
```

- [ ] **Step 4: Run the tests**

Run: `./.venv/bin/python -m pytest tests/test_alerts_eval.py -q`
Expected: PASS, 20 tests.

- [ ] **Step 5: Run the full suite and commit**

```bash
git add backend/proxploy/services/alerts.py backend/tests/test_alerts_eval.py
git commit -m "feat(alerts): threshold evaluator with continuous-breach duration semantics

duration_s means continuously breaching, not averaging: one healthy sample
resets the clock. One open alert per rule+target, so a 30s poll cadence
cannot re-notify twice a minute."
```

---

## Task 10: Alert notification routing

**Files:**
- Modify: `backend/proxploy/services/notifier.py` (`channels_for` and `notify` gain `only_ids`)
- Modify: `backend/proxploy/services/alerts.py` (add `notify_transitions`, `sse_frame`)
- Test: `backend/tests/test_alerts_notify.py`
- Test: `backend/tests/test_notifier.py` (extend)

**Interfaces:**
- Consumes: Task 9's transition dicts; `services.notifier.{notify, channels_for}`.
- Produces, for Tasks 11 and 15:
  - `notifier.channels_for(db, event, only_ids: list[int] | None = None)`
  - `notifier.notify(app, event, title, body, only_ids: list[int] | None = None) -> int`
  - `alerts.sse_frame(t: dict) -> dict` → `{"id", "state", "severity", "message"}` (doc 05's `alert` event shape, verbatim)
  - `alerts.notify_transitions(app, transitions: list[dict]) -> int` — blocking; returns channels reached.

**Routing rule, decided once:** a rule's `channel_ids` is an **override**, not an addition. Non-empty → only those channels, and each still has to be `enabled`. Empty → the normal `notification_channels.events` subscription applies (doc 04: an empty `events` list means every event). Event names are `alert.fired` and `alert.resolved`, matching `notification_channels.events`' documented example `["job.failed","alert.fired","app.updated"]`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_alerts_notify.py`:

```python
"""Alert -> Notifier routing and the SSE frame shape (doc 05 §Streaming)."""
from proxploy.models import NotificationChannel
from proxploy.services.alerts import notify_transitions, sse_frame
from tests.support import make_job_app


def _channel(app, name, events, enabled=True):
    with app.state.sessionmaker() as db:
        blob, ver = app.state.secretstore.encrypt(b"json://example.com/hook")
        row = NotificationChannel(name=name, kind="webhook", url_enc=blob,
                                  key_version=ver, events=events, enabled=enabled)
        db.add(row)
        db.commit()
        return row.id


def _t(**kw):
    base = {"alert_id": 1, "rule_id": 2, "rule_name": "CPU high",
            "state": "firing", "severity": "warning", "target_type": "host",
            "target_id": 3, "target_label": "host-02", "value": 92.0,
            "message": "host-02 CPU > 85% for 5m (now 92%)", "channel_ids": []}
    base.update(kw)
    return base


def test_sse_frame_matches_the_doc_05_shape(tmp_path):
    """doc 05: {"id":12,"state":"firing","severity":"warning","message":"…"}"""
    assert sse_frame(_t(alert_id=12)) == {
        "id": 12, "state": "firing", "severity": "warning",
        "message": "host-02 CPU > 85% for 5m (now 92%)"}


def test_a_firing_alert_reaches_channels_subscribed_to_alert_fired(tmp_path, monkeypatch):
    app = make_job_app(tmp_path)
    _channel(app, "subscribed", ["alert.fired"])
    _channel(app, "wrong event", ["job.failed"])
    _channel(app, "all events", [])

    sent = []
    monkeypatch.setattr("proxploy.services.notifier.send_one",
                        lambda url, title, body: sent.append((title, body)) or True)

    assert notify_transitions(app, [_t()]) == 2      # subscribed + all-events
    assert all("host-02" in body for _, body in sent)


def test_a_resolved_alert_routes_on_alert_resolved(tmp_path, monkeypatch):
    app = make_job_app(tmp_path)
    _channel(app, "fired only", ["alert.fired"])
    _channel(app, "resolved only", ["alert.resolved"])

    sent = []
    monkeypatch.setattr("proxploy.services.notifier.send_one",
                        lambda url, title, body: sent.append(title) or True)

    assert notify_transitions(app, [_t(state="resolved")]) == 1
    assert len(sent) == 1


def test_rule_channel_ids_override_the_event_subscription(tmp_path, monkeypatch):
    """A rule that names its channels means EXACTLY those, not those plus
    everything subscribed to alert.fired."""
    app = make_job_app(tmp_path)
    chosen = _channel(app, "chosen", [])
    _channel(app, "also subscribed to everything", [])

    sent = []
    monkeypatch.setattr("proxploy.services.notifier.send_one",
                        lambda url, title, body: sent.append(title) or True)

    assert notify_transitions(app, [_t(channel_ids=[chosen])]) == 1
    assert len(sent) == 1


def test_a_named_channel_that_is_disabled_still_does_not_fire(tmp_path, monkeypatch):
    app = make_job_app(tmp_path)
    off = _channel(app, "off", [], enabled=False)
    monkeypatch.setattr("proxploy.services.notifier.send_one",
                        lambda url, title, body: True)
    assert notify_transitions(app, [_t(channel_ids=[off])]) == 0


def test_a_channel_that_raises_never_stops_the_others(tmp_path, monkeypatch):
    app = make_job_app(tmp_path)
    _channel(app, "broken", [])
    _channel(app, "fine", [])

    calls = {"n": 0}

    def flaky(url, title, body):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("connection refused to https://user:pass@host")
        return True

    monkeypatch.setattr("proxploy.services.notifier.send_one", flaky)
    assert notify_transitions(app, [_t()]) == 1


def test_the_notification_body_never_carries_a_channel_url(tmp_path, monkeypatch,
                                                           caplog):
    """A raised Apprise error can interpolate the raw URL; notifier.notify logs
    the redacted form only."""
    import logging

    app = make_job_app(tmp_path)
    _channel(app, "broken", [])

    def boom(url, title, body):
        raise RuntimeError(f"failed talking to {url}")

    monkeypatch.setattr("proxploy.services.notifier.send_one", boom)
    with caplog.at_level(logging.DEBUG, logger="proxploy.services.notifier"):
        notify_transitions(app, [_t()])
    assert "example.com/hook" not in caplog.text


def test_an_empty_transition_list_sends_nothing(tmp_path, monkeypatch):
    app = make_job_app(tmp_path)
    _channel(app, "c", [])
    monkeypatch.setattr("proxploy.services.notifier.send_one",
                        lambda *a: (_ for _ in ()).throw(AssertionError("sent!")))
    assert notify_transitions(app, []) == 0
```

Append to `backend/tests/test_notifier.py`:

```python
def test_channels_for_restricted_to_explicit_ids(tmp_path):
    """only_ids is an override: named channels are used regardless of their
    `events` subscription, but never when disabled."""
    from proxploy.models import NotificationChannel
    from proxploy.services.notifier import channels_for
    from tests.support import make_db

    db = make_db(tmp_path)
    wanted = NotificationChannel(name="a", kind="webhook", url_enc=b"x",
                                 key_version=1, events=["job.failed"], enabled=True)
    other = NotificationChannel(name="b", kind="webhook", url_enc=b"x",
                                key_version=1, events=[], enabled=True)
    off = NotificationChannel(name="c", kind="webhook", url_enc=b"x",
                              key_version=1, events=[], enabled=False)
    db.add_all([wanted, other, off])
    db.commit()

    got = channels_for(db, "alert.fired", only_ids=[wanted.id, off.id])
    assert [c.name for c in got] == ["a"]
    # unchanged without only_ids: subscription rules apply
    assert {c.name for c in channels_for(db, "alert.fired")} == {"b"}
```

- [ ] **Step 2: Run it to verify it fails**

Run: `./.venv/bin/python -m pytest tests/test_alerts_notify.py -q`
Expected: `ImportError: cannot import name 'notify_transitions'`.

- [ ] **Step 3: Widen the notifier**

In `backend/proxploy/services/notifier.py`, replace `channels_for` and the top of `notify`:

```python
def channels_for(db, event: str, only_ids: list[int] | None = None
                 ) -> list[NotificationChannel]:
    """Doc 04: an empty `events` list means every event.

    `only_ids` is an OVERRIDE, not a filter on top of the subscription: an
    alert rule that names its channels (doc 04 `alert_rules.channel_ids`)
    means exactly those, whatever they happen to be subscribed to. A disabled
    channel is still never used — "off" beats "named".
    """
    rows = db.query(NotificationChannel).filter_by(enabled=True)
    if only_ids is not None:
        if not only_ids:
            return []
        return rows.filter(NotificationChannel.id.in_(only_ids)).all()
    return [c for c in rows.all() if not c.events or event in c.events]


def notify(app, event: str, title: str, body: str,
           only_ids: list[int] | None = None) -> int:
```

and inside `notify`, change the one call site:

```python
        for channel in channels_for(db, event, only_ids):
```

Everything else in `notify` — the decrypt-inside-the-session, blocking-sends-outside, per-channel isolation and redacted logging — is unchanged.

- [ ] **Step 4: Add the alert fan-out**

Append to `backend/proxploy/services/alerts.py`:

```python
def sse_frame(t: dict) -> dict:
    """The `alert` SSE delta, doc 05 §Streaming 4, verbatim:
    {"id":12,"state":"firing","severity":"warning","message":"host-02 CPU …"}
    """
    return {"id": t["alert_id"], "state": t["state"],
            "severity": t["severity"], "message": t["message"]}


def notify_transitions(app, transitions: list[dict]) -> int:
    """Fan transitions out through the Notifier. Blocking; returns sends made.

    Event names are `alert.fired` / `alert.resolved`, which is what doc 04's
    `notification_channels.events` example subscribes to. A rule's
    `channel_ids` overrides that subscription (see notifier.channels_for).

    Notification is a courtesy and must never be able to fail evaluation, so
    every send is isolated inside notifier.notify already; this only has to not
    raise on its own account.
    """
    from proxploy.services.notifier import notify

    reached = 0
    for t in transitions:
        event = f"alert.{'fired' if t['state'] == 'firing' else 'resolved'}"
        verb = "FIRING" if t["state"] == "firing" else "RESOLVED"
        title = f"Proxploy alert {verb}: {t['rule_name']}"
        try:
            reached += notify(app, event, title, t["message"],
                              only_ids=t.get("channel_ids") or None)
        except Exception:  # noqa: BLE001 — a broken channel never breaks alerting
            logger.debug("alert %s notification failed", t.get("alert_id"),
                         exc_info=True)
    return reached
```

- [ ] **Step 5: Run the tests**

Run: `./.venv/bin/python -m pytest tests/test_alerts_notify.py tests/test_notifier.py tests/test_notifications_api.py tests/test_no_secret_echo.py -q`
Expected: PASS, 9 new tests.

- [ ] **Step 6: Run the full suite and commit**

```bash
git add backend/proxploy/services/notifier.py backend/proxploy/services/alerts.py backend/tests/
git commit -m "feat(alerts): route firing/resolved transitions through the Notifier

alert_rules.channel_ids overrides the channel event subscription rather than
adding to it; a disabled channel still never fires."
```

---

## Task 11: Ride the poll loop

**Files:**
- Modify: `backend/proxploy/pollers/__init__.py` (`Poller.run`)
- Test: `backend/tests/test_alerts_loop.py`

**Interfaces:**
- Consumes: Task 9's `evaluate`, Task 10's `notify_transitions` + `sse_frame`; `settings.alerts_enabled`.
- Produces, for Tasks 15 and 19: an `alert` SSE event on every transition, and a Notifier send per transition.

**Where the hook goes, and why.** Doc 10 says "evaluator riding the poll loop". `Poller.run()` is the supervisor: it already ticks exactly once per `poll_interval_s` regardless of how many hosts exist, which is precisely the cadence alerting wants. Hooking the per-host `_host_loop` instead would re-evaluate every rule once per host per interval — N times the work for the same answer.

**Thread discipline.** `evaluate` and `notify_transitions` are blocking and go in `asyncio.to_thread`. `bus.publish` is called **on the loop** between them, matching the convention `Poller._poll_once` already follows (it returns events for `_host_loop` to publish rather than publishing from the worker thread).

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_alerts_loop.py`:

```python
"""The evaluator riding the poll loop (doc 10 Phase 7)."""
import asyncio

from proxploy.models import Alert, AlertRule, MetricSample, utcnow
from proxploy.pollers import Poller
from tests.support import make_job_app, seed_host_row


def _seed(app, threshold=85.0):
    with app.state.sessionmaker() as db:
        host = seed_host_row(db)
        db.add(AlertRule(name="CPU high", metric="cpu_pct", target_type="host",
                         target_id=host.id, operator="gt", threshold=threshold,
                         duration_s=0, severity="warning", channel_ids=[],
                         enabled=True))
        db.add(MetricSample(target_type="host", target_id=host.id,
                            metric="cpu_pct", value=99.0, ts=utcnow()))
        db.commit()
        return host.id


def test_the_supervisor_pass_evaluates_and_publishes_an_alert_event(tmp_path):
    async def go():
        app = make_job_app(tmp_path)
        app.state.settings = app.state.settings.model_copy(
            update={"poll_interval_s": 0.01, "alerts_enabled": True})
        app.state.poller = Poller(app)
        _seed(app)

        q = app.state.bus.subscribe()
        task = asyncio.create_task(app.state.poller.run())
        frame = None
        for _ in range(300):
            try:
                name, data = q.get_nowait()
            except asyncio.QueueEmpty:
                await asyncio.sleep(0.01)
                continue
            if name == "alert":
                frame = data
                break
        task.cancel()
        app.state.poller.stop()

        assert frame is not None, "no alert event was published"
        assert frame["state"] == "firing"
        assert frame["severity"] == "warning"
        assert set(frame) == {"id", "state", "severity", "message"}
        with app.state.sessionmaker() as db:
            assert db.query(Alert).filter_by(state="firing").count() == 1

    asyncio.run(go())


def test_alerts_disabled_evaluates_nothing(tmp_path):
    async def go():
        app = make_job_app(tmp_path)
        app.state.settings = app.state.settings.model_copy(
            update={"poll_interval_s": 0.01, "alerts_enabled": False})
        app.state.poller = Poller(app)
        _seed(app)

        task = asyncio.create_task(app.state.poller.run())
        await asyncio.sleep(0.2)
        task.cancel()
        app.state.poller.stop()

        with app.state.sessionmaker() as db:
            assert db.query(Alert).count() == 0

    asyncio.run(go())


def test_an_evaluator_failure_never_kills_the_supervisor(tmp_path, monkeypatch):
    """The supervisor also (re)spawns host loops — if alerting can kill it,
    one bad rule stops all polling."""
    async def go():
        app = make_job_app(tmp_path)
        app.state.settings = app.state.settings.model_copy(
            update={"poll_interval_s": 0.01, "alerts_enabled": True})
        app.state.poller = Poller(app)
        _seed(app)

        calls = {"n": 0}

        def boom(db, now=None):
            calls["n"] += 1
            raise RuntimeError("database is locked")

        monkeypatch.setattr("proxploy.services.alerts.evaluate", boom)
        task = asyncio.create_task(app.state.poller.run())
        await asyncio.sleep(0.2)
        task.cancel()
        app.state.poller.stop()
        assert calls["n"] >= 3          # kept ticking after each raise

    asyncio.run(go())


def test_a_notifier_failure_does_not_lose_the_sse_event(tmp_path, monkeypatch):
    """The UI badge must still update when a webhook is down."""
    async def go():
        app = make_job_app(tmp_path)
        app.state.settings = app.state.settings.model_copy(
            update={"poll_interval_s": 0.01, "alerts_enabled": True})
        app.state.poller = Poller(app)
        _seed(app)

        monkeypatch.setattr(
            "proxploy.services.alerts.notify_transitions",
            lambda a, t: (_ for _ in ()).throw(RuntimeError("smtp down")))

        q = app.state.bus.subscribe()
        task = asyncio.create_task(app.state.poller.run())
        seen = False
        for _ in range(300):
            try:
                name, _data = q.get_nowait()
            except asyncio.QueueEmpty:
                await asyncio.sleep(0.01)
                continue
            if name == "alert":
                seen = True
                break
        task.cancel()
        app.state.poller.stop()
        assert seen

    asyncio.run(go())
```

- [ ] **Step 2: Run it to verify it fails**

Run: `./.venv/bin/python -m pytest tests/test_alerts_loop.py -q`
Expected: the first test times out its 300 polls and asserts "no alert event was published".

- [ ] **Step 3: Hook it into the supervisor**

In `backend/proxploy/pollers/__init__.py`, replace `Poller.run` with:

```python
    async def run(self) -> None:
        interval = self.app.state.settings.poll_interval_s
        while True:
            try:
                ids = await asyncio.to_thread(self._host_ids)
                for hid in ids:
                    if hid not in self._tasks or self._tasks[hid].done():
                        self._tasks[hid] = asyncio.create_task(self._host_loop(hid))
                for hid in list(self._tasks):
                    if hid not in ids:
                        self._tasks.pop(hid).cancel()
                        self.snapshots.pop(hid, None)
            except Exception:  # noqa: BLE001 — supervisor never dies
                pass
            # Doc 10 Phase 7: "alert_rules CRUD + evaluator riding the poll
            # loop". Here rather than in _host_loop: this supervisor already
            # ticks exactly once per interval no matter how many hosts exist,
            # and every rule's answer is global — evaluating per host would be
            # N times the queries for the same result. Wrapped separately from
            # the block above so an alerting failure can never stop the
            # supervisor from (re)spawning host loops.
            if self.app.state.settings.alerts_enabled:
                await self._evaluate_alerts()
            await asyncio.sleep(interval)

    async def _evaluate_alerts(self) -> None:
        """Evaluate, publish on the loop, notify off it.

        `evaluate` and `notify_transitions` are blocking (SQLAlchemy, then
        Apprise's ~8 s-per-channel network I/O) so both go to a thread;
        `bus.publish` runs on the loop, matching _poll_once's contract that a
        worker thread returns events rather than publishing them itself.

        The SSE publish happens BEFORE notification and in its own try: a dead
        webhook must not cost the UI its badge update.
        """
        from proxploy.services import alerts as alerts_svc

        try:
            def work():
                with self.app.state.sessionmaker() as db:
                    return alerts_svc.evaluate(db, utcnow())

            transitions = await asyncio.to_thread(work)
        except Exception:  # noqa: BLE001 — one bad pass, not the end of polling
            return
        if not transitions:
            return
        for t in transitions:
            self.app.state.bus.publish("alert", alerts_svc.sse_frame(t))
        try:
            await asyncio.to_thread(alerts_svc.notify_transitions, self.app,
                                    transitions)
        except Exception:  # noqa: BLE001 — a notification is a courtesy
            pass
```

> `alerts_svc.evaluate` / `alerts_svc.notify_transitions` are resolved through the module object, not imported by name, so `monkeypatch.setattr("proxploy.services.alerts.evaluate", …)` in the tests actually takes effect.

- [ ] **Step 4: Run the tests**

Run: `./.venv/bin/python -m pytest tests/test_alerts_loop.py tests/test_poller_loop.py tests/test_events_sse.py -q`
Expected: PASS, 4 new tests.

- [ ] **Step 5: Run the full suite and commit**

```bash
git add backend/proxploy/pollers/__init__.py backend/tests/test_alerts_loop.py
git commit -m "feat(alerts): evaluate on the poll supervisor tick, publish SSE then notify

One evaluation per interval regardless of host count; a notifier failure
cannot cost the UI its alert event, and neither can stop host polling."
```

---

## Task 12: `/alert-rules` CRUD

**Files:**
- Create: `backend/proxploy/api/alerts.py`
- Modify: `backend/proxploy/api/__init__.py`
- Test: `backend/tests/test_alert_rules_api.py`

**Interfaces:**
- Consumes: Task 9's `METRIC_TARGETS`, `SUPPORTED_METRICS`, `STATUS_METRICS`.
- Produces, for Tasks 13 and 16:
  - `GET /api/v1/alert-rules` → `[{id, name, metric, target_type, target_id, operator, threshold, duration_s, severity, channel_ids, enabled}]` (viewer, `alerts.rules`)
  - `POST /api/v1/alert-rules` → 201, same shape (admin, `alerts.rules`)
  - `PATCH /api/v1/alert-rules/{id}` → 200 (admin, `alerts.rules`)
  - `DELETE /api/v1/alert-rules/{id}` → 204 (admin, `alerts.rules`)
  - `GET /api/v1/alert-rules/metrics` → `{"metrics": [{"metric", "targets", "needs_threshold"}]}` — what the form in Task 16 renders from, so the UI never has to hard-code the enum.

**Validation, which is the point of this task.** The worst alerting bug is a rule that looks configured and can never fire. Every one of these is a 422 at write time: an unknown metric; a `(metric, target_type)` pair outside `METRIC_TARGETS` (notably `disk_pct` on an app or VM); an operator other than `gt`/`lt`; a negative `duration_s`; a severity outside `info|warning|critical`; a `target_id` that does not exist; `target_id` present with `target_type="any"` or absent without it; a `channel_ids` entry naming no channel.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_alert_rules_api.py`:

```python
"""Alert rule CRUD (doc 05 §Alerts). Validation is the substance here: a rule
that can never fire is worse than no rule."""
from fastapi.testclient import TestClient

from proxploy.models import Alert, AlertRule, AuditEvent, NotificationChannel
from tests.support import make_app, seed_host_row


def _host(c):
    with c.app.state.sessionmaker() as db:
        return seed_host_row(db).id


def _body(**over):
    b = {"name": "CPU high", "metric": "cpu_pct", "target_type": "any",
         "target_id": None, "operator": "gt", "threshold": 85.0,
         "duration_s": 300, "severity": "warning", "channel_ids": [],
         "enabled": True}
    b.update(over)
    return b


def test_create_round_trips_every_field(client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    h = csrf_header(client)
    r = client.post("/api/v1/alert-rules", json=_body(), headers=h)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["metric"] == "cpu_pct"
    assert body["threshold"] == 85.0
    assert body["duration_s"] == 300
    assert body["severity"] == "warning"
    assert body["target_type"] == "any" and body["target_id"] is None
    with client.app.state.sessionmaker() as db:
        assert db.query(AuditEvent).filter_by(
            action="alert.rule.create", target_id=body["id"]).count() == 1


def test_create_accepts_a_concrete_target(client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    hid = _host(client)
    h = csrf_header(client)
    r = client.post("/api/v1/alert-rules",
                    json=_body(target_type="host", target_id=hid), headers=h)
    assert r.status_code == 201
    assert r.json()["target_id"] == hid


def test_rejects_an_unknown_metric(client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    h = csrf_header(client)
    r = client.post("/api/v1/alert-rules", json=_body(metric="phase_of_moon"),
                    headers=h)
    assert r.status_code == 422
    assert "phase_of_moon" in r.json()["detail"]


def test_rejects_disk_pct_on_a_guest_target(client, csrf_header, bootstrap_admin):
    """The poller writes disk_pct for hosts only — a guest disk rule would sit
    enabled forever and never fire. Say so instead of accepting it."""
    bootstrap_admin(client)
    h = csrf_header(client)
    r = client.post("/api/v1/alert-rules",
                    json=_body(metric="disk_pct", target_type="app", target_id=1),
                    headers=h)
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert "disk_pct" in detail and "host" in detail


def test_rejects_a_target_id_that_does_not_exist(client, csrf_header,
                                                 bootstrap_admin):
    bootstrap_admin(client)
    h = csrf_header(client)
    r = client.post("/api/v1/alert-rules",
                    json=_body(target_type="host", target_id=4242), headers=h)
    assert r.status_code == 422
    assert "4242" in r.json()["detail"]


def test_rejects_any_with_a_target_id_and_a_concrete_type_without_one(
        client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    hid = _host(client)
    h = csrf_header(client)
    assert client.post("/api/v1/alert-rules",
                       json=_body(target_type="any", target_id=hid),
                       headers=h).status_code == 422
    assert client.post("/api/v1/alert-rules",
                       json=_body(target_type="host", target_id=None),
                       headers=h).status_code == 422


def test_rejects_a_bad_operator_severity_or_duration(client, csrf_header,
                                                     bootstrap_admin):
    bootstrap_admin(client)
    h = csrf_header(client)
    for bad in (_body(operator="ge"), _body(severity="apocalyptic"),
                _body(duration_s=-1)):
        assert client.post("/api/v1/alert-rules", json=bad,
                           headers=h).status_code == 422


def test_rejects_a_channel_id_that_names_no_channel(client, csrf_header,
                                                    bootstrap_admin):
    """Otherwise the rule fires and silently notifies nobody."""
    bootstrap_admin(client)
    h = csrf_header(client)
    r = client.post("/api/v1/alert-rules", json=_body(channel_ids=[99]),
                    headers=h)
    assert r.status_code == 422
    assert "99" in r.json()["detail"]


def test_accepts_a_channel_id_that_exists(client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    h = csrf_header(client)
    with client.app.state.sessionmaker() as db:
        blob, ver = client.app.state.secretstore.encrypt(b"json://x/y")
        ch = NotificationChannel(name="c", kind="webhook", url_enc=blob,
                                 key_version=ver, events=[], enabled=True)
        db.add(ch)
        db.commit()
        cid = ch.id
    r = client.post("/api/v1/alert-rules", json=_body(channel_ids=[cid]),
                    headers=h)
    assert r.status_code == 201
    assert r.json()["channel_ids"] == [cid]


def test_status_metrics_do_not_require_a_threshold(client, csrf_header,
                                                   bootstrap_admin):
    """host_offline has nothing to compare — demanding a threshold would be
    theatre."""
    bootstrap_admin(client)
    hid = _host(client)
    h = csrf_header(client)
    r = client.post("/api/v1/alert-rules", headers=h, json={
        "name": "Host down", "metric": "host_offline", "target_type": "host",
        "target_id": hid, "duration_s": 300, "severity": "critical"})
    assert r.status_code == 201, r.text


def test_patch_revalidates_the_whole_rule(client, csrf_header, bootstrap_admin):
    """A PATCH that only sets target_type must still be checked against the
    STORED metric, or disk_pct-on-a-host becomes disk_pct-on-a-vm."""
    bootstrap_admin(client)
    hid = _host(client)
    h = csrf_header(client)
    rid = client.post("/api/v1/alert-rules", headers=h,
                      json=_body(metric="disk_pct", target_type="host",
                                 target_id=hid)).json()["id"]
    r = client.patch(f"/api/v1/alert-rules/{rid}",
                     json={"target_type": "vm", "target_id": 1}, headers=h)
    assert r.status_code == 422
    with client.app.state.sessionmaker() as db:
        assert db.get(AlertRule, rid).target_type == "host"   # unchanged


def test_patch_can_disable_a_rule(client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    h = csrf_header(client)
    rid = client.post("/api/v1/alert-rules", json=_body(), headers=h).json()["id"]
    assert client.patch(f"/api/v1/alert-rules/{rid}", json={"enabled": False},
                        headers=h).json()["enabled"] is False


def test_delete_cascades_its_fired_alerts(client, csrf_header, bootstrap_admin):
    """alerts.rule_id is ON DELETE CASCADE (migration 0001) — assert the
    behaviour rather than trusting the DDL from memory."""
    bootstrap_admin(client)
    h = csrf_header(client)
    rid = client.post("/api/v1/alert-rules", json=_body(), headers=h).json()["id"]
    with client.app.state.sessionmaker() as db:
        db.add(Alert(rule_id=rid, target_type="host", target_id=1,
                     state="firing", value=99.0, message="x"))
        db.commit()

    assert client.delete(f"/api/v1/alert-rules/{rid}", headers=h).status_code == 204
    with client.app.state.sessionmaker() as db:
        assert db.get(AlertRule, rid) is None
        assert db.query(Alert).filter_by(rule_id=rid).count() == 0


def test_unknown_id_is_404(client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    h = csrf_header(client)
    assert client.patch("/api/v1/alert-rules/9999", json={"enabled": False},
                        headers=h).status_code == 404
    assert client.delete("/api/v1/alert-rules/9999", headers=h).status_code == 404


def test_metrics_catalogue_describes_every_supported_metric(client, csrf_header,
                                                            bootstrap_admin):
    """The form in Task 16 renders from this, so the enum lives in exactly one
    place."""
    bootstrap_admin(client)
    body = client.get("/api/v1/alert-rules/metrics").json()
    by = {m["metric"]: m for m in body["metrics"]}
    assert set(by) == {"cpu_pct", "mem_pct", "disk_pct", "host_offline",
                       "backup_failed"}
    assert by["disk_pct"]["targets"] == ["host"]
    assert by["cpu_pct"]["needs_threshold"] is True
    assert by["host_offline"]["needs_threshold"] is False


def test_alerts_rules_entitlement_gates_reads_and_writes(tmp_path, csrf_header,
                                                         bootstrap_admin):
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        h = csrf_header(c)
        c.app.state.entitlements._features = {"alerts.rules": False}
        assert c.get("/api/v1/alert-rules").status_code == 403
        r = c.post("/api/v1/alert-rules", json=_body(), headers=h)
        assert r.status_code == 403
        assert r.json()["feature"] == "alerts.rules"


def test_entitlement_gate_runs_after_auth_not_before(tmp_path, csrf_header):
    app = make_app(tmp_path)
    with TestClient(app) as c:
        h = csrf_header(c)
        c.app.state.entitlements._features = {}
        assert c.get("/api/v1/alert-rules").status_code == 401
        assert c.post("/api/v1/alert-rules", json={}, headers=h).status_code == 401
```

- [ ] **Step 2: Run it to verify it fails**

Run: `./.venv/bin/python -m pytest tests/test_alert_rules_api.py -q`
Expected: 404s — the router does not exist.

- [ ] **Step 3: Write the router**

Create `backend/proxploy/api/alerts.py`:

```python
"""Alert rules and fired alerts (doc 05 §Alerts).

The substance here is validation. The worst failure mode in alerting is a rule
that looks configured, sits `enabled`, and can never fire — nobody discovers it
until the outage it was meant to catch. So every combination the evaluator
cannot answer is a 422 at write time: unknown metric, a (metric, target_type)
pair outside services/alerts.py::METRIC_TARGETS, a target id that names
nothing, a channel id that names nothing.

`GET /alert-rules/metrics` exists so the frontend renders the enum from the
backend rather than hard-coding a second copy that can drift.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from proxploy.api.deps import get_db, require_entitlement, require_role
from proxploy.models import (Alert, AlertRule, App, Host, NotificationChannel,
                             User, Vm, utcnow)
from proxploy.services.alerts import METRIC_TARGETS, STATUS_METRICS
from proxploy.services.audit import write_audit

router = APIRouter(tags=["alerts"])

_require_viewer = require_role("viewer")
_require_operator = require_role("operator")
_require_admin = require_role("admin")

OPERATORS = ("gt", "lt")
SEVERITIES = ("info", "warning", "critical")
TARGET_MODEL = {"host": Host, "app": App, "vm": Vm}


class RuleIn(BaseModel):
    name: str
    metric: str
    target_type: str = "any"
    target_id: int | None = None
    operator: str = "gt"
    threshold: float = 0.0
    duration_s: int = 0
    severity: str = "warning"
    channel_ids: list[int] | None = None
    enabled: bool = True


class RulePatch(BaseModel):
    name: str | None = None
    metric: str | None = None
    target_type: str | None = None
    target_id: int | None = None
    operator: str | None = None
    threshold: float | None = None
    duration_s: int | None = None
    severity: str | None = None
    channel_ids: list[int] | None = None
    enabled: bool | None = None


def _rule_out(r: AlertRule) -> dict:
    return {"id": r.id, "name": r.name, "metric": r.metric,
            "target_type": r.target_type, "target_id": r.target_id,
            "operator": r.operator, "threshold": r.threshold,
            "duration_s": r.duration_s, "severity": r.severity,
            "channel_ids": list(r.channel_ids or []), "enabled": r.enabled}


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _validate(db, *, metric: str, target_type: str, target_id: int | None,
              operator: str, duration_s: int, severity: str,
              channel_ids: list[int]) -> None:
    if metric not in METRIC_TARGETS:
        raise HTTPException(422, f"unknown metric {metric!r}; supported: "
                                 f"{', '.join(sorted(METRIC_TARGETS))}")
    allowed = METRIC_TARGETS[metric]
    if target_type != "any" and target_type not in allowed:
        raise HTTPException(422, f"{metric!r} can only target "
                                 f"{', '.join(allowed)} — not {target_type!r}")
    if target_type == "any" and target_id is not None:
        raise HTTPException(422, "target_id must be null when target_type is 'any'")
    if target_type != "any":
        if target_id is None:
            raise HTTPException(422, f"target_id is required for "
                                     f"target_type {target_type!r}")
        model = TARGET_MODEL.get(target_type)
        if model is None:
            raise HTTPException(422, f"unknown target_type {target_type!r}")
        if db.get(model, target_id) is None:
            raise HTTPException(422, f"no {target_type} with id {target_id}")
    if metric not in STATUS_METRICS and operator not in OPERATORS:
        raise HTTPException(422, f"operator must be one of {', '.join(OPERATORS)}")
    if duration_s < 0:
        raise HTTPException(422, "duration_s must not be negative")
    if severity not in SEVERITIES:
        raise HTTPException(422, f"severity must be one of {', '.join(SEVERITIES)}")
    for cid in channel_ids:
        if db.get(NotificationChannel, cid) is None:
            # A rule that fires into a deleted channel notifies nobody and
            # gives no sign of it.
            raise HTTPException(422, f"no notification channel with id {cid}")


# --- rules ------------------------------------------------------------------

@router.get("/alert-rules/metrics",
            dependencies=[Depends(_require_viewer),
                          Depends(require_entitlement("alerts.rules"))])
def list_metrics(user: User = Depends(_require_viewer)):
    """One source of truth for the metric enum — the rule form renders this."""
    return {"metrics": [
        {"metric": m, "targets": list(targets),
         "needs_threshold": m not in STATUS_METRICS}
        for m, targets in METRIC_TARGETS.items()]}


@router.get("/alert-rules",
            dependencies=[Depends(_require_viewer),
                          Depends(require_entitlement("alerts.rules"))])
def list_rules(db=Depends(get_db), user: User = Depends(_require_viewer)):
    return [_rule_out(r) for r in db.query(AlertRule).order_by(AlertRule.id).all()]


@router.post("/alert-rules", status_code=201,
             dependencies=[Depends(_require_admin),
                           Depends(require_entitlement("alerts.rules"))])
def create_rule(request: Request, body: RuleIn, db=Depends(get_db),
                user: User = Depends(_require_admin)):
    channel_ids = body.channel_ids or []
    _validate(db, metric=body.metric, target_type=body.target_type,
              target_id=body.target_id, operator=body.operator,
              duration_s=body.duration_s, severity=body.severity,
              channel_ids=channel_ids)
    row = AlertRule(name=body.name, metric=body.metric,
                    target_type=body.target_type, target_id=body.target_id,
                    operator=body.operator, threshold=body.threshold,
                    duration_s=body.duration_s, severity=body.severity,
                    channel_ids=channel_ids, enabled=body.enabled)
    db.add(row)
    db.commit()
    write_audit(db, actor_type="user", actor_id=user.id,
                action="alert.rule.create", target_type="alert_rule",
                target_id=row.id, params=_rule_out(row), ip=_ip(request))
    return _rule_out(row)


@router.patch("/alert-rules/{rule_id}",
              dependencies=[Depends(_require_admin),
                            Depends(require_entitlement("alerts.rules"))])
def patch_rule(request: Request, rule_id: int, body: RulePatch,
               db=Depends(get_db), user: User = Depends(_require_admin)):
    row = db.get(AlertRule, rule_id)
    if row is None:
        raise HTTPException(404, "alert rule not found")
    merged = {**_rule_out(row),
              **{k: v for k, v in body.model_dump(exclude_unset=True).items()}}
    # Revalidate the WHOLE merged rule, not just the changed fields: a PATCH
    # that moves target_type has to be checked against the STORED metric.
    _validate(db, metric=merged["metric"], target_type=merged["target_type"],
              target_id=merged["target_id"], operator=merged["operator"],
              duration_s=merged["duration_s"], severity=merged["severity"],
              channel_ids=merged["channel_ids"] or [])
    for field in ("name", "metric", "target_type", "target_id", "operator",
                  "threshold", "duration_s", "severity", "enabled"):
        setattr(row, field, merged[field])
    row.channel_ids = merged["channel_ids"] or []
    db.commit()
    write_audit(db, actor_type="user", actor_id=user.id,
                action="alert.rule.update", target_type="alert_rule",
                target_id=row.id, params=_rule_out(row), ip=_ip(request))
    return _rule_out(row)


@router.delete("/alert-rules/{rule_id}", status_code=204,
               dependencies=[Depends(_require_admin),
                             Depends(require_entitlement("alerts.rules"))])
def delete_rule(request: Request, rule_id: int, db=Depends(get_db),
                user: User = Depends(_require_admin)):
    row = db.get(AlertRule, rule_id)
    if row is None:
        raise HTTPException(404, "alert rule not found")
    name = row.name
    # alerts.rule_id is ON DELETE CASCADE (migration 0001), but SQLite only
    # honours that with PRAGMA foreign_keys ON — delete the children explicitly
    # so the behaviour is identical on both target databases.
    db.query(Alert).filter(Alert.rule_id == rule_id).delete(
        synchronize_session=False)
    db.delete(row)
    db.commit()
    write_audit(db, actor_type="user", actor_id=user.id,
                action="alert.rule.delete", target_type="alert_rule",
                target_id=rule_id, params={"name": name}, ip=_ip(request))
    return Response(status_code=204)
```

- [ ] **Step 4: Register the router**

In `backend/proxploy/api/__init__.py`, add `alerts` to the import tuple and `api_router.include_router(alerts.router)` after `notifications.router`.

> The router has **no prefix** — doc 05 puts rules at `/alert-rules` and alerts at `/alerts`, which are two top-level paths in one domain. Both live in this module.

- [ ] **Step 5: Run the tests**

Run: `./.venv/bin/python -m pytest tests/test_alert_rules_api.py tests/test_route_auth_invariant.py -q`
Expected: PASS, 17 new tests.

- [ ] **Step 6: Run the full suite and commit**

```bash
git add backend/proxploy/api/alerts.py backend/proxploy/api/__init__.py backend/tests/test_alert_rules_api.py
git commit -m "feat(alerts): rule CRUD that refuses rules which could never fire

disk_pct on a guest, a target id naming nothing, a channel id naming nothing
— all 422 at write time rather than sitting enabled and silent."
```

---

## Task 13: `GET /alerts` and `POST /alerts/{id}/ack`

**Files:**
- Modify: `backend/proxploy/api/alerts.py`
- Test: `backend/tests/test_alerts_api.py`

**Interfaces:**
- Produces, for Tasks 14, 15 and 16:
  - `GET /api/v1/alerts?state=firing&limit=50` → `[{id, rule_id, rule_name, severity, target_type, target_id, target_label, state, value, message, fired_at, resolved_at, acked_by, acked_by_email, acked_at}]` (viewer, no entitlement — doc 05 leaves the column blank; the health footer needs it on every tier)
  - `POST /api/v1/alerts/{id}/ack` → the same object (operator)
  - `alert_out(db, a: Alert, rules: dict, emails: dict) -> dict` — reused by Task 14's activity feed.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_alerts_api.py`:

```python
"""GET /alerts and POST /alerts/{id}/ack (doc 05 §Alerts)."""
from datetime import timedelta

from proxploy.models import Alert, AlertRule, AuditEvent, utcnow
from tests.support import seed_host_row


def _seed(c):
    with c.app.state.sessionmaker() as db:
        host = seed_host_row(db)
        rule = AlertRule(name="CPU high", metric="cpu_pct", target_type="host",
                         target_id=host.id, operator="gt", threshold=85.0,
                         duration_s=300, severity="warning", channel_ids=[],
                         enabled=True)
        db.add(rule)
        db.commit()
        now = utcnow()
        firing = Alert(rule_id=rule.id, target_type="host", target_id=host.id,
                       state="firing", value=92.0, message="host-01 CPU > 85%",
                       fired_at=now)
        old = Alert(rule_id=rule.id, target_type="host", target_id=host.id,
                    state="resolved", value=10.0, message="Resolved: host-01 CPU",
                    fired_at=now - timedelta(hours=2),
                    resolved_at=now - timedelta(hours=1))
        db.add_all([firing, old])
        db.commit()
        return rule.id, firing.id, old.id, host.id


def test_list_returns_both_states_newest_first(client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    _rid, firing, old, _ = _seed(client)
    rows = client.get("/api/v1/alerts").json()
    assert [r["id"] for r in rows] == [firing, old]


def test_state_filter_narrows_to_firing(client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    _rid, firing, _old, _ = _seed(client)
    rows = client.get("/api/v1/alerts?state=firing").json()
    assert [r["id"] for r in rows] == [firing]


def test_each_row_carries_its_rule_name_and_target_label(client, csrf_header,
                                                         bootstrap_admin):
    """The health footer and the alerts table both render these; without them
    every row would need a second and third fetch."""
    bootstrap_admin(client)
    _seed(client)
    row = client.get("/api/v1/alerts?state=firing").json()[0]
    assert row["rule_name"] == "CPU high"
    assert row["severity"] == "warning"
    assert row["target_label"] == "host-01"
    assert row["fired_at"].endswith("Z")


def test_a_target_deleted_since_firing_still_renders(client, csrf_header,
                                                     bootstrap_admin):
    """History outlives the host it was about."""
    bootstrap_admin(client)
    _rid, firing, _old, host_id = _seed(client)
    with client.app.state.sessionmaker() as db:
        from proxploy.models import Host
        db.delete(db.get(Host, host_id))
        db.commit()
    row = next(r for r in client.get("/api/v1/alerts").json() if r["id"] == firing)
    assert row["target_label"] is None      # honest gap, not a crash


def test_limit_is_bounded(client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    _seed(client)
    assert len(client.get("/api/v1/alerts?limit=1").json()) == 1
    # absurd values are clamped rather than 500ing or dumping the table
    assert client.get("/api/v1/alerts?limit=100000").status_code == 200


def test_ack_stamps_the_user_and_audits(client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    _rid, firing, _old, _ = _seed(client)
    h = csrf_header(client)
    r = client.post(f"/api/v1/alerts/{firing}/ack", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["acked_by"] is not None
    assert body["acked_by_email"] == "admin@example.com"
    assert body["acked_at"] is not None
    assert body["state"] == "firing"          # ack silences, it does not resolve
    with client.app.state.sessionmaker() as db:
        assert db.query(AuditEvent).filter_by(
            action="alert.ack", target_id=firing).count() == 1


def test_acking_twice_is_idempotent_and_keeps_the_first_acker(client, csrf_header,
                                                              bootstrap_admin):
    bootstrap_admin(client)
    _rid, firing, _old, _ = _seed(client)
    h = csrf_header(client)
    first = client.post(f"/api/v1/alerts/{firing}/ack", headers=h).json()
    second = client.post(f"/api/v1/alerts/{firing}/ack", headers=h).json()
    assert second["acked_at"] == first["acked_at"]


def test_ack_404s_an_unknown_alert(client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    h = csrf_header(client)
    assert client.post("/api/v1/alerts/9999/ack", headers=h).status_code == 404


def test_alerts_are_readable_without_any_entitlement(tmp_path, csrf_header,
                                                     bootstrap_admin):
    """Doc 05 leaves the entitlement column blank for GET /alerts — the sidebar
    health footer must work on every tier, including the free one."""
    from fastapi.testclient import TestClient
    from tests.support import make_app

    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        c.app.state.entitlements._features = {}
        assert c.get("/api/v1/alerts?state=firing").status_code == 200
```

- [ ] **Step 2: Run it to verify it fails**

Run: `./.venv/bin/python -m pytest tests/test_alerts_api.py -q`
Expected: 404s.

- [ ] **Step 3: Write the routes**

Append to `backend/proxploy/api/alerts.py`:

```python
# --- fired alerts -----------------------------------------------------------

ALERTS_MAX = 200


def alert_out(a: Alert, rules: dict, labels: dict, emails: dict) -> dict:
    """One row, fully renderable — rule name, severity and target label are
    joined here so the table and the health footer need exactly one fetch.

    `rules`/`labels`/`emails` are caller-built lookup dicts, so listing N
    alerts is a constant number of queries rather than 3N.
    """
    rule = rules.get(a.rule_id)
    return {
        "id": a.id, "rule_id": a.rule_id,
        "rule_name": rule.name if rule else None,
        "severity": rule.severity if rule else "warning",
        "target_type": a.target_type, "target_id": a.target_id,
        "target_label": labels.get((a.target_type, a.target_id)),
        "state": a.state, "value": a.value, "message": a.message,
        "fired_at": a.fired_at.isoformat() + "Z" if a.fired_at else None,
        "resolved_at": a.resolved_at.isoformat() + "Z" if a.resolved_at else None,
        "acked_by": a.acked_by, "acked_by_email": emails.get(a.acked_by),
        "acked_at": a.acked_at.isoformat() + "Z" if a.acked_at else None,
    }


def _lookups(db, rows: list[Alert]) -> tuple[dict, dict, dict]:
    rules = {r.id: r for r in db.query(AlertRule)
             .filter(AlertRule.id.in_({a.rule_id for a in rows})).all()} if rows else {}
    labels: dict[tuple, str] = {}
    for kind, model in TARGET_MODEL.items():
        ids = {a.target_id for a in rows
               if a.target_type == kind and a.target_id is not None}
        if not ids:
            continue
        for row in db.query(model).filter(model.id.in_(ids)).all():
            labels[(kind, row.id)] = row.name
    acked = {a.acked_by for a in rows if a.acked_by}
    emails = {u.id: u.email for u in db.query(User)
              .filter(User.id.in_(acked)).all()} if acked else {}
    return rules, labels, emails


@router.get("/alerts", dependencies=[Depends(_require_viewer)])
def list_alerts(state: str | None = None, limit: int = 50, db=Depends(get_db),
                user: User = Depends(_require_viewer)):
    """Doc 05 leaves the entitlement column blank here on purpose: the sidebar
    health footer ("3 nodes · 0 alerts") reads this on every tier."""
    limit = max(1, min(limit, ALERTS_MAX))
    q = db.query(Alert)
    if state:
        q = q.filter(Alert.state == state)
    rows = q.order_by(Alert.fired_at.desc(), Alert.id.desc()).limit(limit).all()
    rules, labels, emails = _lookups(db, rows)
    return [alert_out(a, rules, labels, emails) for a in rows]


@router.post("/alerts/{alert_id}/ack", dependencies=[Depends(_require_operator)])
def ack_alert(request: Request, alert_id: int, db=Depends(get_db),
              user: User = Depends(_require_operator)):
    """Acknowledging silences; it never resolves. The evaluator still flips an
    acked alert to `resolved` on recovery (services/alerts.py) — an operator
    saying "I know" must not make the system stop tracking whether it is fixed.
    """
    row = db.get(Alert, alert_id)
    if row is None:
        raise HTTPException(404, "alert not found")
    if row.acked_at is None:
        row.acked_by, row.acked_at = user.id, utcnow()
        db.commit()
        write_audit(db, actor_type="user", actor_id=user.id, action="alert.ack",
                    target_type="alert", target_id=row.id,
                    params={"message": row.message}, ip=_ip(request))
    rules, labels, emails = _lookups(db, [row])
    return alert_out(row, rules, labels, emails)
```

- [ ] **Step 4: Run the tests**

Run: `./.venv/bin/python -m pytest tests/test_alerts_api.py tests/test_alert_rules_api.py -q`
Expected: PASS, 9 new tests.

- [ ] **Step 5: Run the full suite and commit**

```bash
git add backend/proxploy/api/alerts.py backend/tests/test_alerts_api.py
git commit -m "feat(alerts): GET /alerts + ack, with rule name and target label joined in"
```

---

## Task 14: Alerts in the activity feed

**Files:**
- Modify: `backend/proxploy/api/cluster.py` (`activity`)
- Test: `backend/tests/test_activity_api.py` (extend)

**Interfaces:**
- Consumes: Task 13's `alert_out`.
- Produces: `GET /cluster/activity` rows now include `{"kind": "alert", …}` entries alongside `job` and `audit`.

**Why this is a task and not a line.** `api/cluster.py::activity` carries a written promise: *"Alerts join this feed in Phase 7 when the evaluator exists — the `kind` discriminator is here so that is additive."* Doc 05 describes the endpoint as "jobs + alerts + audit highlights, merged". The existing paging note also matters: each source is queried with `LIMIT limit` (not `limit // 3`) so the merged-then-sliced result is the true top-`limit`. Adding a third source keeps that property only if it too gets the full `limit`.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_activity_api.py`:

```python
def test_activity_merges_alerts_with_jobs_and_audits(client, csrf_header,
                                                     bootstrap_admin):
    from datetime import timedelta

    from proxploy.models import Alert, AlertRule, Job, utcnow
    from tests.support import seed_host_row

    bootstrap_admin(client)
    now = utcnow()
    with client.app.state.sessionmaker() as db:
        host = seed_host_row(db)
        rule = AlertRule(name="CPU high", metric="cpu_pct", target_type="host",
                         target_id=host.id, operator="gt", threshold=85.0,
                         duration_s=0, severity="critical", channel_ids=[],
                         enabled=True)
        db.add(rule)
        db.add(Job(kind="backup.run", status="succeeded", target_type="host",
                   target_id=host.id, created_at=now - timedelta(minutes=5)))
        db.commit()
        db.add(Alert(rule_id=rule.id, target_type="host", target_id=host.id,
                     state="firing", value=99.0, message="host-01 CPU > 85%",
                     fired_at=now, created_at=now))
        db.commit()

    rows = client.get("/api/v1/cluster/activity").json()
    kinds = [r["kind"] for r in rows]
    assert "alert" in kinds and "job" in kinds

    alert_row = next(r for r in rows if r["kind"] == "alert")
    assert alert_row["title"] == "CPU high"
    assert alert_row["status"] == "firing"
    assert alert_row["severity"] == "critical"
    assert alert_row["target_type"] == "host"
    assert alert_row["job_id"] is None
    # newest first — the alert fired after the job was created
    assert kinds.index("alert") < kinds.index("job")


def test_a_resolved_alert_shows_as_resolved_in_the_feed(client, csrf_header,
                                                        bootstrap_admin):
    from proxploy.models import Alert, AlertRule, utcnow
    from tests.support import seed_host_row

    bootstrap_admin(client)
    with client.app.state.sessionmaker() as db:
        host = seed_host_row(db)
        rule = AlertRule(name="CPU high", metric="cpu_pct", target_type="host",
                         target_id=host.id, operator="gt", threshold=85.0,
                         duration_s=0, severity="warning", channel_ids=[],
                         enabled=True)
        db.add(rule)
        db.commit()
        db.add(Alert(rule_id=rule.id, target_type="host", target_id=host.id,
                     state="resolved", value=5.0, message="Resolved: host-01 CPU",
                     fired_at=utcnow(), resolved_at=utcnow()))
        db.commit()

    row = next(r for r in client.get("/api/v1/cluster/activity").json()
               if r["kind"] == "alert")
    assert row["status"] == "resolved"


def test_alerts_do_not_starve_the_other_sources_of_the_feed(client, csrf_header,
                                                            bootstrap_admin):
    """Each source is queried with the full `limit` so the merged top-N is the
    true top-N — adding a third source must not change that."""
    from proxploy.models import Alert, AlertRule, Job, utcnow
    from tests.support import seed_host_row

    bootstrap_admin(client)
    with client.app.state.sessionmaker() as db:
        host = seed_host_row(db)
        rule = AlertRule(name="noisy", metric="cpu_pct", target_type="host",
                         target_id=host.id, operator="gt", threshold=1.0,
                         duration_s=0, severity="info", channel_ids=[],
                         enabled=True)
        db.add(rule)
        db.add(Job(kind="backup.run", status="succeeded", target_type="host",
                   target_id=host.id))
        db.commit()
        for _ in range(30):
            db.add(Alert(rule_id=rule.id, target_type="host", target_id=host.id,
                         state="resolved", value=2.0, message="x",
                         fired_at=utcnow(), resolved_at=utcnow()))
        db.commit()

    rows = client.get("/api/v1/cluster/activity?limit=5").json()
    assert len(rows) == 5
```

- [ ] **Step 2: Run it to verify it fails**

Run: `./.venv/bin/python -m pytest tests/test_activity_api.py -q`
Expected: `StopIteration` — no row has `kind == "alert"`.

- [ ] **Step 3: Add the third source**

In `backend/proxploy/api/cluster.py`:

1. Extend the model import: `from proxploy.models import Alert, AlertRule, App, AuditEvent, Host, Job, User, Vm`.
2. Rewrite the docstring paragraph that says *"Alerts join this feed in Phase 7 when the evaluator exists"* to describe the shipped behaviour.
3. Insert, after the `audit_rows = [...]` list comprehension and before `merged = ...`:

```python
    # Third source (doc 05: "jobs + alerts + audit highlights, merged"). Like
    # the two above it is queried with the FULL `limit`, not `limit // 3` —
    # that is what makes the merged-then-sliced result the true top-`limit`.
    alerts = (db.query(Alert).order_by(Alert.created_at.desc(), Alert.id.desc())
              .limit(limit).all())
    rule_names = {r.id: (r.name, r.severity) for r in db.query(AlertRule)
                  .filter(AlertRule.id.in_({a.rule_id for a in alerts})).all()
                  } if alerts else {}
    alert_rows = [(a.created_at, {
        "kind": "alert", "id": a.id, "at": a.created_at.isoformat() + "Z",
        "title": rule_names.get(a.rule_id, (a.message, "warning"))[0],
        "status": a.state,
        "severity": rule_names.get(a.rule_id, (None, "warning"))[1],
        "target_type": a.target_type, "target_id": a.target_id,
        "actor": None,          # nobody triggers an alert; the evaluator does
        "job_id": None, "progress_pct": None,
        "message": a.message}) for a in alerts]
```

4. Change the merge line to include it:

```python
    merged = sorted(job_rows + audit_rows + alert_rows,
                    key=lambda pair: pair[0], reverse=True)
```

5. Add `"severity": None` and `"message": None` to the `job` and `audit` row dicts so every feed row has the same keys — the frontend `ActivityFeed` maps over one shape.

> `Alert.created_at` is used for ordering rather than `fired_at`: `created_at` is `NOT NULL` on every row (TimestampMixin) while `fired_at` is nullable, and sorting a `None` against a `datetime` raises. They are set to the same instant by the evaluator anyway.

- [ ] **Step 4: Run the tests**

Run: `./.venv/bin/python -m pytest tests/test_activity_api.py tests/test_cluster_api.py -q`
Expected: PASS, 3 new tests.

- [ ] **Step 5: Run the full suite and commit**

```bash
git add backend/proxploy/api/cluster.py backend/tests/test_activity_api.py
git commit -m "feat(cluster): merge alerts into the activity feed, honouring the phase-2 promise"
```

---

## Task 15: Frontend — `alert` SSE event and the real health footer

**Files:**
- Create: `frontend/src/api/alerts.ts`
- Create: `frontend/src/components/HealthFooter.tsx`
- Modify: `frontend/src/api/live.ts`, `frontend/src/components/LiveProvider.tsx`, `frontend/src/components/SidebarNav.tsx`, `frontend/src/api/jobs.ts` (`ActivityRow`), `frontend/src/components/ActivityFeed.tsx`
- Test: `frontend/src/tests/healthfooter.test.tsx`, `frontend/src/tests/live.test.ts` (extend)

**Interfaces:**
- Consumes: Task 13's `GET /alerts?state=firing`, Task 11's `alert` SSE event, Task 14's activity rows.
- Produces, for Task 16:
  - `AlertRow`, `AlertRuleRow`, `MetricSpec` types in `src/api/alerts.ts`
  - `useFiringAlerts()` — `['alerts','firing']`, 60 s refetch (doc 06 §d)
  - `useAlertRules()`, `useAlertMetrics()`, `useAckAlert()`
  - `applyAlert(qc, d, toast?)` in `src/api/live.ts`
  - `<HealthFooter />`

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/tests/healthfooter.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

const state: { alerts: any[]; hosts: any[] } = { alerts: [], hosts: [] }

vi.mock('../api/client', () => ({
  ApiError: class extends Error {},
  api: vi.fn((path: string) => {
    if (path.startsWith('/alerts')) return Promise.resolve(state.alerts)
    if (path === '/cluster/nodes') return Promise.resolve(state.hosts)
    return Promise.resolve(null)
  }),
}))

import { HealthFooter } from '../components/HealthFooter'

const wrap = (ui: React.ReactNode) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

describe('HealthFooter', () => {
  it('reads "All systems healthy" with nodes and no firing alerts', async () => {
    state.alerts = []
    state.hosts = [{ status: 'connected' }, { status: 'connected' },
                   { status: 'connected' }]
    wrap(<HealthFooter />)
    await waitFor(() => expect(screen.getByText(/all systems healthy/i)).toBeInTheDocument())
    expect(screen.getByText(/3 nodes · 0 alerts/i)).toBeInTheDocument()
  })

  it('counts firing alerts and turns the dot red', async () => {
    state.alerts = [
      { id: 1, state: 'firing', severity: 'critical', message: 'host-02 CPU' },
      { id: 2, state: 'firing', severity: 'warning', message: 'redis memory' },
    ]
    state.hosts = [{ status: 'connected' }]
    const { container } = wrap(<HealthFooter />)
    await waitFor(() => expect(screen.getByText(/1 node · 2 alerts/i)).toBeInTheDocument())
    expect(screen.getByText(/2 alerts firing/i)).toBeInTheDocument()
    expect(container.querySelector('.bg-red')).not.toBeNull()
  })

  it('reports an unreachable node even with no alerts', async () => {
    state.alerts = []
    state.hosts = [{ status: 'connected' }, { status: 'unreachable' }]
    wrap(<HealthFooter />)
    await waitFor(() => expect(screen.getByText(/1 node unreachable/i)).toBeInTheDocument())
  })
})
```

Append to `frontend/src/tests/live.test.ts`:

```ts
describe('applyAlert', () => {
  it('invalidates the firing-alerts query and the activity feed', () => {
    const qc = new QueryClient()
    const spy = vi.spyOn(qc, 'invalidateQueries')
    applyAlert(qc, { id: 1, state: 'firing', severity: 'warning', message: 'x' })
    const keys = spy.mock.calls.map(c => JSON.stringify((c[0] as any).queryKey))
    expect(keys).toContain(JSON.stringify(['alerts', 'firing']))
    expect(keys).toContain(JSON.stringify(['cluster', 'activity']))
  })

  it('toasts a firing alert at warning and above', () => {
    const qc = new QueryClient()
    const seen: any[] = []
    applyAlert(qc, { id: 1, state: 'firing', severity: 'warning', message: 'hot' },
               (t) => seen.push(t))
    expect(seen).toEqual([{ kind: 'err', text: 'hot', alertId: 1 }])
  })

  it('stays quiet for an info-severity alert (doc 06: warning+)', () => {
    const qc = new QueryClient()
    const seen: any[] = []
    applyAlert(qc, { id: 1, state: 'firing', severity: 'info', message: 'meh' },
               (t) => seen.push(t))
    expect(seen).toEqual([])
  })

  it('toasts a resolution as good news, whatever the severity', () => {
    const qc = new QueryClient()
    const seen: any[] = []
    applyAlert(qc, { id: 1, state: 'resolved', severity: 'critical',
                     message: 'Resolved: host-02 CPU' }, (t) => seen.push(t))
    expect(seen).toEqual([{ kind: 'ok', text: 'Resolved: host-02 CPU', alertId: 1 }])
  })
})
```

Add `applyAlert` to that file's existing import from `../api/live`, and `QueryClient`/`vi` if not already imported.

- [ ] **Step 2: Run them to verify they fail**

Run: `npm test -- healthfooter live`
Expected: `Failed to resolve import "../components/HealthFooter"` and `applyAlert is not a function`.

- [ ] **Step 3: Write the API module**

Create `frontend/src/api/alerts.ts`:

```ts
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'

export type AlertRow = {
  id: number; rule_id: number; rule_name: string | null
  severity: 'info' | 'warning' | 'critical'
  target_type: string | null; target_id: number | null
  target_label: string | null
  state: 'firing' | 'resolved'; value: number | null; message: string | null
  fired_at: string | null; resolved_at: string | null
  acked_by: number | null; acked_by_email: string | null; acked_at: string | null
}

export type AlertRuleRow = {
  id: number; name: string; metric: string
  target_type: 'host' | 'app' | 'vm' | 'any'; target_id: number | null
  operator: 'gt' | 'lt'; threshold: number; duration_s: number
  severity: 'info' | 'warning' | 'critical'
  channel_ids: number[]; enabled: boolean
}

/** GET /alert-rules/metrics — the enum lives on the backend, never twice. */
export type MetricSpec = { metric: string; targets: string[]; needs_threshold: boolean }

/** Doc 06 §d: `['alerts','firing']`, 60 s, health-footer source. */
export function useFiringAlerts() {
  return useQuery({
    queryKey: ['alerts', 'firing'],
    queryFn: () => api<AlertRow[]>('/alerts?state=firing'),
    refetchInterval: 60_000,
  })
}

export function useAlertHistory(limit = 50) {
  return useQuery({
    queryKey: ['alerts', 'history', limit],
    queryFn: () => api<AlertRow[]>(`/alerts?limit=${limit}`),
  })
}

export function useAlertRules(enabled = true) {
  return useQuery({
    queryKey: ['alert-rules'],
    queryFn: () => api<AlertRuleRow[]>('/alert-rules'),
    enabled,
  })
}

export function useAlertMetrics(enabled = true) {
  return useQuery({
    queryKey: ['alert-rules', 'metrics'],
    queryFn: () => api<{ metrics: MetricSpec[] }>('/alert-rules/metrics'),
    staleTime: 5 * 60_000,     // an enum, not live data
    enabled,
  })
}

export function useAckAlert() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api<AlertRow>(`/alerts/${id}/ack`, { method: 'POST' }),
    onSettled: () => qc.invalidateQueries({ queryKey: ['alerts'] }),
  })
}
```

- [ ] **Step 4: Handle the SSE event**

Append to `frontend/src/api/live.ts`:

```ts
type AlertDelta = {
  id: number; state: 'firing' | 'resolved'
  severity: 'info' | 'warning' | 'critical'; message: string
}
type AlertToastFn = (t: { kind: 'ok' | 'err'; text: string; alertId: number }) => void

/** SSE `alert` event → invalidate `['alerts','firing']`; toast for `firing` at
 *  warning+ severity (doc 06 §d, verbatim).
 *
 *  Invalidate rather than patch: the delta carries four fields and the table
 *  renders eleven (rule name, target label, ack state…), so patching would
 *  write a half-row into the cache. Doc 06's rule is "patch when the delta is
 *  complete, invalidate when it isn't".
 *
 *  A `resolved` transition always toasts, at any severity — an info-level
 *  alert that quietly went away is still worth one line of good news, and it
 *  is the only signal that an earlier toast is stale. */
export function applyAlert(qc: QueryClient, d: AlertDelta, toast?: AlertToastFn) {
  qc.invalidateQueries({ queryKey: ['alerts', 'firing'] })
  qc.invalidateQueries({ queryKey: ['cluster', 'activity'] })
  if (d.state === 'resolved') {
    toast?.({ kind: 'ok', text: d.message, alertId: d.id })
    return
  }
  if (d.severity === 'info') return
  toast?.({ kind: 'err', text: d.message, alertId: d.id })
}
```

In `frontend/src/components/LiveProvider.tsx`, add `applyAlert` to the `../api/live` import and wire the event alongside the others:

```tsx
    wire('alert', (d) => applyAlert(qc, d, (t) => {
      if (!inApp.current) return   // notify.inapp gates the surface, not the data
      const show = t.kind === 'ok' ? toast.success : toast.error
      show(t.text, { description: 'alert' })
    }))
```

- [ ] **Step 5: Write the health footer**

Create `frontend/src/components/HealthFooter.tsx`:

```tsx
import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { api } from '../api/client'
import { useFiringAlerts } from '../api/alerts'
import type { NodeRow } from '../api/hooks'

/** Doc 06 §(b) `HealthFooter`: `.side-foot` — "All systems healthy", green dot,
 *  "3 nodes · 0 alerts". Bound to `/alerts?state=firing` + host status; the dot
 *  turns `--red` when anything is firing.
 *
 *  Until Phase 7 this was three hard-coded lines in SidebarNav that always said
 *  "All systems healthy" — the one piece of UI that must never lie. */
export function HealthFooter() {
  const alerts = useFiringAlerts()
  const nodes = useQuery({
    queryKey: ['cluster', 'nodes'],
    queryFn: () => api<NodeRow[]>('/cluster/nodes'),
    refetchInterval: 30_000,
  })

  const firing = alerts.data?.length ?? 0
  const rows = nodes.data ?? []
  const down = rows.filter((n) => n.status !== 'connected').length
  const critical = (alerts.data ?? []).some((a) => a.severity === 'critical')
  const unhealthy = firing > 0 || down > 0

  const headline = firing > 0
    ? `${firing} alert${firing === 1 ? '' : 's'} firing`
    : down > 0
      ? `${down} node${down === 1 ? '' : 's'} unreachable`
      : 'All systems healthy'

  const dot = !unhealthy ? 'bg-green shadow-[0_0_6px_rgba(63,207,142,.6)]'
    : critical || down > 0 ? 'bg-red shadow-[0_0_6px_rgba(232,90,90,.6)]'
    : 'bg-amber shadow-[0_0_6px_rgba(245,181,68,.6)]'

  return (
    <Link to={'/alerts' as never}
          className="block border-t border-line-soft px-4 py-3 text-[12px] text-text-2 hover:bg-panel-2">
      <span className={`mr-2 inline-block h-2 w-2 rounded-full ${dot}`} />
      {headline}
      <span className="mt-0.5 block font-mono text-[11px] text-text-3">
        {rows.length} node{rows.length === 1 ? '' : 's'} · {firing} alert{firing === 1 ? '' : 's'}
      </span>
    </Link>
  )
}
```

In `frontend/src/components/SidebarNav.tsx`, replace the hard-coded footer `<div>` with `<HealthFooter />` (importing it), and add an Alerts entry to the Infrastructure group **above** Settings:

```tsx
  { label: 'Infrastructure', items: [
    { label: 'Storage', to: '/storage' },
    { label: 'Network', to: '/network' },
    { label: 'Backups', to: '/backups' },
    { label: 'Alerts', to: '/alerts' },
    { label: 'Settings', to: '/settings' },
  ]},
```

- [ ] **Step 6: Widen the activity row type**

In `frontend/src/api/jobs.ts`:

```ts
export type ActivityRow = {
  kind: 'job' | 'audit' | 'alert'; id: number; at: string; title: string
  status: string | null; target_type: string | null; target_id: number | null
  actor: string | null; job_id: number | null; progress_pct: number | null
  severity: string | null; message: string | null
}
```

In `frontend/src/components/ActivityFeed.tsx`, extend `TINT` and the badge so an alert row is legible rather than falling through to the neutral grey:

```tsx
const TINT: Record<string, string> = {
  succeeded: 'bg-green-dim text-green',
  ok: 'bg-green-dim text-green',
  resolved: 'bg-green-dim text-green',
  failed: 'bg-red-dim text-red',
  error: 'bg-red-dim text-red',
  denied: 'bg-red-dim text-red',
  firing: 'bg-red-dim text-red',
  running: 'bg-blue-dim text-blue',
  queued: 'bg-blue-dim text-blue',
  canceled: 'bg-panel-2 text-text-3',
  interrupted: 'bg-amber-dim text-amber',
}

const BADGE: Record<string, string> = { job: 'JOB', audit: 'AUD', alert: 'ALT' }
```

and in `Item`, replace the badge expression with `{BADGE[row.kind] ?? '—'}`.

- [ ] **Step 7: Run the tests**

Run: `npm test`
Expected: PASS — 121 existing + 7 new.

- [ ] **Step 8: Type-check and lint**

Run: `npm run build && npm run lint`
Expected: clean.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/api/alerts.ts frontend/src/api/live.ts frontend/src/api/jobs.ts frontend/src/components/ frontend/src/tests/
git commit -m "feat(ui): alert SSE handling and a health footer that can say something is wrong

The footer said 'All systems healthy' unconditionally since Phase 1 — the
one piece of UI that must never lie."
```

---

## Task 16: Frontend — the `/alerts` page

**Files:**
- Create: `frontend/src/routes/alerts.tsx`, `frontend/src/components/AlertRuleForm.tsx`
- Modify: `frontend/src/router.tsx`
- Test: `frontend/src/tests/alerts.test.tsx`

**Interfaces:**
- Consumes: Task 15's `src/api/alerts.ts` hooks, Task 12's `/alert-rules` + `/alert-rules/metrics`, Task 13's `/alerts` + ack.
- Produces: `alertsRoute` for `router.tsx`.

**Design.** Doc 06 has no `/alerts` route in the prototype, so it is built from the same vocabulary as `/settings` (its `Card` shell and table styling) — no new visual language. Two cards: **Firing** (message, target, severity pill, fired-ago, Ack button; the empty state is the good news) and **Rules** (table + inline `AlertRuleForm`, lock-veiled when `alerts.rules` is unentitled, matching how `settings.tsx` treats `notify.channels`). Alert history sits under Firing behind a "Show resolved" toggle so the page opens on what is wrong now.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/tests/alerts.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

const posted: { path: string; method: string; body: any }[] = []
let features: Record<string, boolean> = { 'alerts.rules': true }
let firing: any[] = []
let rules: any[] = []

vi.mock('../api/client', () => ({
  ApiError: class extends Error {},
  api: vi.fn((path: string, opts?: RequestInit) => {
    const method = (opts?.method ?? 'GET').toUpperCase()
    if (method !== 'GET') {
      posted.push({ path, method, body: opts?.body ? JSON.parse(String(opts.body)) : null })
      return Promise.resolve({ id: 99 })
    }
    if (path === '/entitlements') return Promise.resolve({ tier: 'builtin', features, grace: null })
    if (path === '/alerts?state=firing') return Promise.resolve(firing)
    if (path.startsWith('/alerts')) return Promise.resolve(firing)
    if (path === '/alert-rules/metrics') return Promise.resolve({ metrics: [
      { metric: 'cpu_pct', targets: ['host', 'app', 'vm'], needs_threshold: true },
      { metric: 'disk_pct', targets: ['host'], needs_threshold: true },
      { metric: 'host_offline', targets: ['host'], needs_threshold: false },
    ]})
    if (path === '/alert-rules') return Promise.resolve(rules)
    if (path === '/notifications/channels') return Promise.resolve([])
    if (path === '/hosts') return Promise.resolve([{ id: 1, name: 'host-01' }])
    return Promise.resolve([])
  }),
}))

import { AlertsPage } from '../routes/alerts'

const wrap = () => {
  const qc = new QueryClient({ defaultOptions: {
    queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={qc}><AlertsPage /></QueryClientProvider>)
}

describe('AlertsPage', () => {
  it('says nothing is firing when nothing is', async () => {
    posted.length = 0; firing = []; rules = []
    wrap()
    await waitFor(() => expect(screen.getByText(/nothing is firing/i)).toBeInTheDocument())
  })

  it('lists a firing alert with its target and severity', async () => {
    posted.length = 0
    firing = [{ id: 7, rule_id: 1, rule_name: 'CPU high', severity: 'critical',
                target_type: 'host', target_id: 1, target_label: 'host-02',
                state: 'firing', value: 92, message: 'host-02 CPU > 85% for 5m',
                fired_at: new Date().toISOString(), resolved_at: null,
                acked_by: null, acked_by_email: null, acked_at: null }]
    rules = []
    wrap()
    await waitFor(() => expect(screen.getByText(/host-02 CPU > 85% for 5m/)).toBeInTheDocument())
    expect(screen.getByText('critical')).toBeInTheDocument()
    expect(screen.getByText('host-02')).toBeInTheDocument()
  })

  it('acks an alert', async () => {
    posted.length = 0
    firing = [{ id: 7, rule_id: 1, rule_name: 'CPU high', severity: 'warning',
                target_type: 'host', target_id: 1, target_label: 'host-02',
                state: 'firing', value: 92, message: 'hot',
                fired_at: new Date().toISOString(), resolved_at: null,
                acked_by: null, acked_by_email: null, acked_at: null }]
    rules = []
    wrap()
    await waitFor(() => screen.getByRole('button', { name: /^ack$/i }))
    fireEvent.click(screen.getByRole('button', { name: /^ack$/i }))
    await waitFor(() => expect(posted.length).toBe(1))
    expect(posted[0]).toMatchObject({ path: '/alerts/7/ack', method: 'POST' })
  })

  it('shows an already-acked alert as acknowledged instead of an Ack button', async () => {
    posted.length = 0
    firing = [{ id: 7, rule_id: 1, rule_name: 'CPU high', severity: 'warning',
                target_type: 'host', target_id: 1, target_label: 'host-02',
                state: 'firing', value: 92, message: 'hot',
                fired_at: new Date().toISOString(), resolved_at: null,
                acked_by: 1, acked_by_email: 'admin@example.com',
                acked_at: new Date().toISOString() }]
    rules = []
    wrap()
    await waitFor(() => expect(screen.getByText(/admin@example.com/)).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: /^ack$/i })).toBeNull()
  })

  it('lock-veils the rules card when alerts.rules is unentitled', async () => {
    posted.length = 0; firing = []; rules = []
    features = { 'alerts.rules': false }
    wrap()
    await waitFor(() => expect(screen.getByText(/not included in your plan/i)).toBeInTheDocument())
    features = { 'alerts.rules': true }
  })

  it('creates a rule from the form', async () => {
    posted.length = 0; firing = []; rules = []
    wrap()
    await waitFor(() => screen.getByRole('button', { name: /new rule/i }))
    fireEvent.click(screen.getByRole('button', { name: /new rule/i }))
    fireEvent.change(screen.getByLabelText(/name/i), { target: { value: 'CPU high' } })
    fireEvent.change(screen.getByLabelText(/threshold/i), { target: { value: '85' } })
    fireEvent.change(screen.getByLabelText(/for at least/i), { target: { value: '300' } })
    fireEvent.click(screen.getByRole('button', { name: /create rule/i }))
    await waitFor(() => expect(posted.length).toBe(1))
    expect(posted[0].path).toBe('/alert-rules')
    expect(posted[0].body).toMatchObject({
      name: 'CPU high', metric: 'cpu_pct', threshold: 85, duration_s: 300,
      operator: 'gt', severity: 'warning',
    })
  })

  it('hides threshold and operator for a status metric', async () => {
    posted.length = 0; firing = []; rules = []
    wrap()
    await waitFor(() => screen.getByRole('button', { name: /new rule/i }))
    fireEvent.click(screen.getByRole('button', { name: /new rule/i }))
    fireEvent.change(screen.getByLabelText(/^metric$/i), { target: { value: 'host_offline' } })
    await waitFor(() => expect(screen.queryByLabelText(/threshold/i)).toBeNull())
  })

  it('offers only the target kinds the chosen metric supports', async () => {
    posted.length = 0; firing = []; rules = []
    wrap()
    await waitFor(() => screen.getByRole('button', { name: /new rule/i }))
    fireEvent.click(screen.getByRole('button', { name: /new rule/i }))
    fireEvent.change(screen.getByLabelText(/^metric$/i), { target: { value: 'disk_pct' } })
    const select = screen.getByLabelText(/target/i) as HTMLSelectElement
    const opts = [...select.options].map(o => o.value)
    expect(opts).toContain('host')
    expect(opts).not.toContain('vm')      // the backend would 422 it anyway
  })

  it('toggles a rule off', async () => {
    posted.length = 0; firing = []
    rules = [{ id: 3, name: 'CPU high', metric: 'cpu_pct', target_type: 'any',
               target_id: null, operator: 'gt', threshold: 85, duration_s: 300,
               severity: 'warning', channel_ids: [], enabled: true }]
    wrap()
    await waitFor(() => screen.getByRole('button', { name: /disable/i }))
    fireEvent.click(screen.getByRole('button', { name: /disable/i }))
    await waitFor(() => expect(posted.length).toBe(1))
    expect(posted[0]).toMatchObject({ path: '/alert-rules/3', method: 'PATCH',
                                      body: { enabled: false } })
  })
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npm test -- alerts`
Expected: `Failed to resolve import "../routes/alerts"`.

- [ ] **Step 3: Write the rule form**

Create `frontend/src/components/AlertRuleForm.tsx`:

```tsx
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { api, ApiError } from '../api/client'
import { useAlertMetrics } from '../api/alerts'
import { Button } from './ui/button'

const input = 'w-full rounded-ctl border border-line bg-panel-2 px-3 py-2 text-[13px] text-text'
const label = 'mb-1 block text-[11.5px] uppercase tracking-wide text-text-3'

type HostRow = { id: number; name: string }

/** Create one alert rule. The metric enum, and which target kinds each metric
 *  supports, come from GET /alert-rules/metrics — never a second hard-coded
 *  copy that can drift from services/alerts.py::METRIC_TARGETS. */
export function AlertRuleForm({ onSaved }: { onSaved: () => void }) {
  const qc = useQueryClient()
  const metrics = useAlertMetrics()
  const specs = metrics.data?.metrics ?? []

  const [name, setName] = useState('')
  const [metric, setMetric] = useState('cpu_pct')
  const [targetType, setTargetType] = useState('any')
  const [targetId, setTargetId] = useState('')
  const [operator, setOperator] = useState<'gt' | 'lt'>('gt')
  const [threshold, setThreshold] = useState('85')
  const [durationS, setDurationS] = useState('300')
  const [severity, setSeverity] = useState('warning')

  const spec = specs.find((s) => s.metric === metric)
  const needsThreshold = spec?.needs_threshold ?? true
  // 'any' only makes sense when more than one kind is on offer; a host-only
  // metric collapses to a host target rather than pretending otherwise.
  const targetKinds = spec?.targets ?? ['host', 'app', 'vm']
  const targetOptions = targetKinds.length > 1 ? ['any', ...targetKinds] : targetKinds

  const hosts = useQuery({
    queryKey: ['hosts'], queryFn: () => api<HostRow[]>('/hosts'),
    enabled: targetType === 'host',
  })

  const create = useMutation({
    mutationFn: () => api('/alert-rules', {
      method: 'POST',
      body: JSON.stringify({
        name, metric,
        target_type: targetType,
        target_id: targetType === 'any' ? null : Number(targetId) || null,
        operator, threshold: needsThreshold ? Number(threshold) : 0,
        duration_s: Number(durationS) || 0, severity, channel_ids: [],
        enabled: true,
      }),
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['alert-rules'] })
      onSaved()
    },
    // The backend's 422s are the useful ones ("disk_pct can only target host"),
    // so surface the message rather than a generic failure.
    onError: (e) => toast.error(
      e instanceof ApiError && typeof (e.body as any)?.detail === 'string'
        ? (e.body as any).detail
        : 'Could not create that rule — check the fields and try again.'),
  })

  function pickMetric(next: string) {
    setMetric(next)
    const kinds = specs.find((s) => s.metric === next)?.targets ?? []
    // Reset a target the new metric cannot carry (disk_pct on a VM), or the
    // form would post a combination the backend correctly rejects.
    if (kinds.length === 1) {
      setTargetType(kinds[0])
    } else if (targetType !== 'any' && !kinds.includes(targetType)) {
      setTargetType('any')
    }
  }

  return (
    <form className="grid grid-cols-1 gap-3 sm:grid-cols-2"
          onSubmit={(e) => { e.preventDefault(); create.mutate() }}>
      <div className="sm:col-span-2">
        <label className={label} htmlFor="ar-name">Name</label>
        <input id="ar-name" className={input} value={name} required
               onChange={(e) => setName(e.target.value)} />
      </div>

      <div>
        <label className={label} htmlFor="ar-metric">Metric</label>
        <select id="ar-metric" className={input} value={metric}
                onChange={(e) => pickMetric(e.target.value)}>
          {specs.map((s) => <option key={s.metric} value={s.metric}>{s.metric}</option>)}
        </select>
      </div>

      <div>
        <label className={label} htmlFor="ar-target">Target</label>
        <select id="ar-target" className={input} value={targetType}
                onChange={(e) => { setTargetType(e.target.value); setTargetId('') }}>
          {targetOptions.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
      </div>

      {targetType === 'host' && (
        <div>
          <label className={label} htmlFor="ar-host">Host</label>
          <select id="ar-host" className={input} value={targetId}
                  onChange={(e) => setTargetId(e.target.value)}>
            <option value="">Select…</option>
            {(hosts.data ?? []).map((h) =>
              <option key={h.id} value={h.id}>{h.name}</option>)}
          </select>
        </div>
      )}

      {needsThreshold && (
        <>
          <div>
            <label className={label} htmlFor="ar-op">Condition</label>
            <select id="ar-op" className={input} value={operator}
                    onChange={(e) => setOperator(e.target.value as 'gt' | 'lt')}>
              <option value="gt">above</option>
              <option value="lt">below</option>
            </select>
          </div>
          <div>
            <label className={label} htmlFor="ar-threshold">Threshold</label>
            <input id="ar-threshold" className={input} type="number" step="any"
                   value={threshold} onChange={(e) => setThreshold(e.target.value)} />
          </div>
        </>
      )}

      <div>
        <label className={label} htmlFor="ar-duration">For at least (seconds)</label>
        <input id="ar-duration" className={input} type="number" min="0"
               value={durationS} onChange={(e) => setDurationS(e.target.value)} />
      </div>

      <div>
        <label className={label} htmlFor="ar-severity">Severity</label>
        <select id="ar-severity" className={input} value={severity}
                onChange={(e) => setSeverity(e.target.value)}>
          <option value="info">info</option>
          <option value="warning">warning</option>
          <option value="critical">critical</option>
        </select>
      </div>

      <div className="sm:col-span-2">
        <Button type="submit" disabled={create.isPending}>Create rule</Button>
        <span className="ml-3 text-[12px] text-text-3">
          Notifications go to every channel subscribed to <code>alert.fired</code>.
        </span>
      </div>
    </form>
  )
}
```

- [ ] **Step 4: Write the page**

Create `frontend/src/routes/alerts.tsx`:

```tsx
import { useState } from 'react'
import { createRoute } from '@tanstack/react-router'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { shellRoute } from './shell'
import { api } from '../api/client'
import { useAckAlert, useAlertHistory, useAlertRules, useFiringAlerts } from '../api/alerts'
import type { AlertRow, AlertRuleRow } from '../api/alerts'
import { useEntitlements } from '../api/hooks'
import { AlertRuleForm } from '../components/AlertRuleForm'
import { Button } from '../components/ui/button'

const card = 'rounded-card border border-line-soft bg-panel p-5'
const th = 'text-[10.5px] uppercase tracking-wide text-text-3'

const SEV: Record<string, string> = {
  info: 'bg-blue-dim text-blue',
  warning: 'bg-amber-dim text-amber',
  critical: 'bg-red-dim text-red',
}

function ago(iso: string | null): string {
  if (!iso) return '—'
  const s = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000))
  if (s < 60) return `${s}s ago`
  if (s < 3600) return `${Math.round(s / 60)}m ago`
  if (s < 86400) return `${Math.round(s / 3600)}h ago`
  return `${Math.round(s / 86400)}d ago`
}

function AlertRowView({ a, onAck, acking }:
  { a: AlertRow; onAck: (id: number) => void; acking: boolean }) {
  return (
    <tr className="border-t border-line-soft hover:bg-panel-2">
      <td className="py-2">
        <span className={`rounded-tile px-2 py-0.5 font-mono text-[10.5px] ${SEV[a.severity] ?? SEV.warning}`}>
          {a.severity}
        </span>
      </td>
      <td className="py-2 text-[13px] text-text">{a.message}</td>
      <td className="font-mono text-[12px] text-text-2">{a.target_label ?? '—'}</td>
      <td className="font-mono text-[12px] text-text-3">{ago(a.fired_at)}</td>
      <td className="py-2 text-right">
        {a.acked_at
          ? <span className="text-[11.5px] text-text-3">
              acknowledged by {a.acked_by_email ?? 'someone'}
            </span>
          : <Button variant="ghost" className="px-2 py-1 text-[11px]"
                    disabled={acking} onClick={() => onAck(a.id)}>Ack</Button>}
      </td>
    </tr>
  )
}

export function AlertsPage() {
  const ent = useEntitlements()
  const qc = useQueryClient()
  const firing = useFiringAlerts()
  const [showResolved, setShowResolved] = useState(false)
  const history = useAlertHistory(50)
  const ack = useAckAlert()

  const rulesAllowed = ent.data != null && ent.has('alerts.rules')
  const rules = useAlertRules(rulesAllowed)
  const [adding, setAdding] = useState(false)

  const toggleRule = useMutation({
    mutationFn: (r: AlertRuleRow) => api(`/alert-rules/${r.id}`, {
      method: 'PATCH', body: JSON.stringify({ enabled: !r.enabled }),
    }),
    onError: () => toast.error('Could not update that rule — try again.'),
    onSettled: () => qc.invalidateQueries({ queryKey: ['alert-rules'] }),
  })
  const removeRule = useMutation({
    mutationFn: (id: number) => api(`/alert-rules/${id}`, { method: 'DELETE' }),
    onError: () => toast.error('Could not remove that rule — try again.'),
    onSettled: () => qc.invalidateQueries({ queryKey: ['alert-rules'] }),
  })

  const resolved = (history.data ?? []).filter((a) => a.state === 'resolved')

  return (
    <div className="max-w-4xl space-y-5">
      <h1 className="font-display text-[22px] font-semibold">Alerts</h1>

      <section className={card}>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="font-display text-[15px] font-semibold">Firing</h2>
          <Button variant="ghost" onClick={() => setShowResolved((s) => !s)}>
            {showResolved ? 'Hide resolved' : 'Show resolved'}
          </Button>
        </div>
        {(firing.data ?? []).length === 0 ? (
          <p className="text-[12.5px] text-text-3">
            Nothing is firing. Rules are checked every poll cycle.
          </p>
        ) : (
          <table className="w-full text-left">
            <thead><tr className={th}>
              <th className="pb-2">Severity</th><th>Alert</th><th>Target</th>
              <th>Since</th><th /></tr></thead>
            <tbody>
              {(firing.data ?? []).map((a) => (
                <AlertRowView key={a.id} a={a} acking={ack.isPending}
                              onAck={(id) => ack.mutate(id)} />
              ))}
            </tbody>
          </table>
        )}

        {showResolved && (
          <div className="mt-5 border-t border-line-soft pt-4">
            <h3 className="mb-2 text-[12px] uppercase tracking-wide text-text-3">
              Recently resolved
            </h3>
            {resolved.length === 0 ? (
              <p className="text-[12.5px] text-text-3">No resolved alerts yet.</p>
            ) : (
              <table className="w-full text-left">
                <tbody>
                  {resolved.map((a) => (
                    <tr key={a.id} className="border-t border-line-soft">
                      <td className="py-2 text-[13px] text-text-2">{a.message}</td>
                      <td className="font-mono text-[12px] text-text-3">
                        {ago(a.resolved_at)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}
      </section>

      <section className={card}>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="font-display text-[15px] font-semibold">Rules</h2>
          {rulesAllowed && (
            <Button variant="ghost" onClick={() => setAdding((a) => !a)}>
              {adding ? 'Close' : 'New rule'}
            </Button>
          )}
        </div>
        {!rulesAllowed ? (
          <p className="text-[12.5px] text-text-3">
            {ent.data == null ? 'Loading…' : 'Not included in your plan.'}
          </p>
        ) : (
          <>
            <table className="w-full text-left text-[13px]">
              <thead><tr className={th}>
                <th className="pb-2">Name</th><th>Condition</th><th>Target</th>
                <th>Severity</th><th>State</th><th /></tr></thead>
              <tbody>
                {(rules.data ?? []).map((r) => (
                  <tr key={r.id} className="border-t border-line-soft hover:bg-panel-2">
                    <td className="py-2">{r.name}</td>
                    <td className="font-mono text-[12px] text-text-2">
                      {r.metric}
                      {r.metric.endsWith('_pct')
                        ? ` ${r.operator === 'gt' ? '>' : '<'} ${r.threshold}%`
                        : ''}
                      {r.duration_s ? ` for ${Math.round(r.duration_s / 60)}m` : ''}
                    </td>
                    <td className="font-mono text-[12px] text-text-3">
                      {r.target_type}{r.target_id != null ? ` ${r.target_id}` : ''}
                    </td>
                    <td>
                      <span className={`rounded-tile px-2 py-0.5 font-mono text-[10.5px] ${SEV[r.severity] ?? SEV.warning}`}>
                        {r.severity}
                      </span>
                    </td>
                    <td className={r.enabled ? 'text-green' : 'text-text-3'}>
                      {r.enabled ? 'enabled' : 'disabled'}
                    </td>
                    <td className="py-2 text-right">
                      <Button variant="ghost" className="px-2 py-1 text-[11px]"
                              disabled={toggleRule.isPending}
                              onClick={() => toggleRule.mutate(r)}>
                        {r.enabled ? 'Disable' : 'Enable'}
                      </Button>
                      <Button variant="danger" className="ml-2 px-2 py-1 text-[11px]"
                              onClick={() => {
                                if (window.confirm(`Remove alert rule "${r.name}"? Its fired alerts go with it.`)) {
                                  removeRule.mutate(r.id)
                                }
                              }}>Remove</Button>
                    </td>
                  </tr>
                ))}
                {!rules.data?.length && (
                  <tr><td colSpan={6} className="py-4 text-text-3">
                    No rules yet. Add one to be told when a host runs hot.
                  </td></tr>
                )}
              </tbody>
            </table>
            {adding && (
              <div className="mt-4 border-t border-line-soft pt-4">
                <AlertRuleForm onSaved={() => setAdding(false)} />
              </div>
            )}
          </>
        )}
      </section>
    </div>
  )
}

export const alertsRoute = createRoute({
  getParentRoute: () => shellRoute,
  path: '/alerts',
  component: AlertsPage,
})
```

- [ ] **Step 5: Register the route**

In `frontend/src/router.tsx`, add `import { alertsRoute } from './routes/alerts'` and put `alertsRoute` in the `shellRoute.addChildren([...])` list, before `settingsRoute`.

- [ ] **Step 6: Run the tests, build and lint**

Run: `npm test && npm run build && npm run lint`
Expected: PASS, 9 new tests, clean build. `src/tests/nav.test.tsx` may assert the nav item list — update it for the new Alerts entry if it does.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/routes/alerts.tsx frontend/src/components/AlertRuleForm.tsx frontend/src/router.tsx frontend/src/tests/
git commit -m "feat(ui): /alerts page — firing list with ack, resolved history, rule CRUD

The rule form renders its metric enum and per-metric target kinds from
GET /alert-rules/metrics rather than keeping a second copy that can drift."
```

---

## Task 17: Frontend — schedules in Settings and on Backups

**Files:**
- Create: `frontend/src/api/schedules.ts`, `frontend/src/components/ScheduleForm.tsx`
- Modify: `frontend/src/routes/settings.tsx`, `frontend/src/routes/backups.tsx`
- Test: `frontend/src/tests/schedules.test.tsx`, `frontend/src/tests/backups.test.tsx` (extend)

**Interfaces:**
- Consumes: Task 3's `/schedules` routes.
- Produces: `ScheduleRow`, `useSchedules()`, `<ScheduleForm jobKind? params? onSaved />`.

**Two placeholders this task is required to remove.** `frontend/src/routes/backups.tsx` currently ships a **disabled** "New job" button titled *"Scheduled backup jobs arrive with the Phase 7 scheduler."* and a "Next scheduled" stat card reading `—` with the note *"Scheduled backups arrive with the Phase 7 scheduler; every run today is one you started."* `frontend/src/routes/settings.tsx` ships a General card reading *"Scheduled auto-updates and catalog sync configuration arrive in Phases 4–7; this page grows with them."* All three are Phase 7's bill. Leaving any of them is leaving the task unfinished.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/tests/schedules.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

const posted: { path: string; method: string; body: any }[] = []
let schedules: any[] = []

vi.mock('../api/client', () => ({
  ApiError: class extends Error {},
  api: vi.fn((path: string, opts?: RequestInit) => {
    const method = (opts?.method ?? 'GET').toUpperCase()
    if (method !== 'GET') {
      posted.push({ path, method, body: opts?.body ? JSON.parse(String(opts.body)) : null })
      return Promise.resolve({ id: 5, job: { id: 1, kind: 'backup.run' } })
    }
    if (path === '/schedules') return Promise.resolve(schedules)
    if (path === '/hosts') return Promise.resolve([{ id: 1, name: 'host-01' }])
    if (path === '/entitlements') return Promise.resolve({
      tier: 'builtin', features: { 'sched.windows': true, 'store.auto_update': true },
      grace: null })
    return Promise.resolve([])
  }),
}))

import { ScheduleForm } from '../components/ScheduleForm'
import { SchedulesCard } from '../routes/settings'

const wrap = (ui: React.ReactNode) => {
  const qc = new QueryClient({ defaultOptions: {
    queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

describe('ScheduleForm', () => {
  it('posts name, job kind, cron and timezone', async () => {
    posted.length = 0
    wrap(<ScheduleForm onSaved={() => {}} />)
    fireEvent.change(screen.getByLabelText(/name/i), { target: { value: 'Nightly backup' } })
    fireEvent.change(screen.getByLabelText(/what to run/i), { target: { value: 'backup.run' } })
    fireEvent.change(screen.getByLabelText(/cron/i), { target: { value: '0 2 * * *' } })
    fireEvent.click(screen.getByRole('button', { name: /create schedule/i }))
    await waitFor(() => expect(posted.length).toBe(1))
    expect(posted[0].path).toBe('/schedules')
    expect(posted[0].body).toMatchObject({
      name: 'Nightly backup', job_kind: 'backup.run', cron: '0 2 * * *',
    })
    expect(typeof posted[0].body.timezone).toBe('string')
  })

  it('defaults the timezone to the browser zone rather than UTC', () => {
    posted.length = 0
    wrap(<ScheduleForm onSaved={() => {}} />)
    const tz = (screen.getByLabelText(/timezone/i) as HTMLInputElement).value
    expect(tz).toBe(Intl.DateTimeFormat().resolvedOptions().timeZone)
  })

  it('asks which host a backup schedule targets', async () => {
    posted.length = 0
    wrap(<ScheduleForm onSaved={() => {}} />)
    fireEvent.change(screen.getByLabelText(/what to run/i), { target: { value: 'backup.run' } })
    await waitFor(() => expect(screen.getByLabelText(/host/i)).toBeInTheDocument())
  })

  it('honours a pinned job kind and hides the picker', () => {
    posted.length = 0
    wrap(<ScheduleForm jobKind="backup.run" onSaved={() => {}} />)
    expect(screen.queryByLabelText(/what to run/i)).toBeNull()
  })
})

describe('SchedulesCard', () => {
  it('lists schedules with their next run', async () => {
    posted.length = 0
    schedules = [{ id: 1, name: 'Nightly backup', job_kind: 'backup.run',
                   cron: '0 2 * * *', timezone: 'UTC', params: { host_id: 1 },
                   enabled: true, created_by: 1,
                   last_run_at: null, next_run_at: '2026-08-02T02:00:00Z' }]
    wrap(<SchedulesCard />)
    await waitFor(() => expect(screen.getByText('Nightly backup')).toBeInTheDocument())
    expect(screen.getByText('0 2 * * *')).toBeInTheDocument()
  })

  it('runs a schedule now', async () => {
    posted.length = 0
    schedules = [{ id: 1, name: 'Nightly backup', job_kind: 'backup.run',
                   cron: '0 2 * * *', timezone: 'UTC', params: {}, enabled: true,
                   created_by: 1, last_run_at: null, next_run_at: null }]
    wrap(<SchedulesCard />)
    await waitFor(() => screen.getByRole('button', { name: /run now/i }))
    fireEvent.click(screen.getByRole('button', { name: /run now/i }))
    await waitFor(() => expect(posted.length).toBe(1))
    expect(posted[0]).toMatchObject({ path: '/schedules/1/run', method: 'POST' })
  })

  it('disables a schedule', async () => {
    posted.length = 0
    schedules = [{ id: 1, name: 'Nightly backup', job_kind: 'backup.run',
                   cron: '0 2 * * *', timezone: 'UTC', params: {}, enabled: true,
                   created_by: 1, last_run_at: null, next_run_at: null }]
    wrap(<SchedulesCard />)
    await waitFor(() => screen.getByRole('button', { name: /disable/i }))
    fireEvent.click(screen.getByRole('button', { name: /disable/i }))
    await waitFor(() => expect(posted.length).toBe(1))
    expect(posted[0]).toMatchObject({ path: '/schedules/1', method: 'PATCH',
                                      body: { enabled: false } })
  })

  it('marks a system-owned schedule so it is not mistaken for a user one', async () => {
    posted.length = 0
    schedules = [{ id: 1, name: 'Catalog refresh', job_kind: 'catalog.refresh',
                   cron: '0 4 * * *', timezone: 'UTC', params: {}, enabled: true,
                   created_by: null, last_run_at: null, next_run_at: null }]
    wrap(<SchedulesCard />)
    await waitFor(() => expect(screen.getByText(/system/i)).toBeInTheDocument())
  })
})
```

Append to `frontend/src/tests/backups.test.tsx`:

```tsx
it('opens a schedule dialog from "New job" instead of a disabled button', async () => {
  // The Phase 6 placeholder rendered a disabled button titled "…arrive with
  // the Phase 7 scheduler". Phase 7 owes it a working dialog.
  const { BackupsPage } = await import('../routes/backups')
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={qc}><BackupsPage /></QueryClientProvider>)
  const btn = await screen.findByRole('button', { name: /new job/i })
  expect(btn).not.toBeDisabled()
  fireEvent.click(btn)
  await waitFor(() => expect(screen.getByLabelText(/cron/i)).toBeInTheDocument())
})
```

> Match this test's mock/setup to whatever `backups.test.tsx` already establishes at the top of that file — reuse its `vi.mock('../api/client')` rather than adding a second one, and extend that mock to answer `/schedules` with `[]`.

- [ ] **Step 2: Run them to verify they fail**

Run: `npm test -- schedules backups`
Expected: `Failed to resolve import "../components/ScheduleForm"`, and the backups assertion fails on the disabled button.

- [ ] **Step 3: Write the API module**

Create `frontend/src/api/schedules.ts`:

```ts
import { useQuery } from '@tanstack/react-query'
import { api } from './client'

export type ScheduleRow = {
  id: number; name: string; job_kind: string; cron: string; timezone: string
  params: Record<string, unknown>; enabled: boolean
  created_by: number | null           // null = a schedule Proxploy seeded itself
  last_run_at: string | null; next_run_at: string | null
}

/** Job kinds worth offering in the UI. Deliberately not every registered
 *  handler: `vm.delete` on a cron is not a feature, it is a foot-gun. The
 *  backend accepts any registered kind, so this list is the curated surface,
 *  not the security boundary. */
export const SCHEDULABLE: { kind: string; label: string; needs: 'host' | 'app' | null }[] = [
  { kind: 'backup.run', label: 'Backup guests on a host', needs: 'host' },
  { kind: 'backup.prune', label: 'Apply backup retention', needs: 'host' },
  { kind: 'app.update', label: 'Update an app', needs: 'app' },
  { kind: 'catalog.refresh', label: 'Refresh the app catalog', needs: null },
  { kind: 'metrics.maintain', label: 'Roll up and prune metrics', needs: null },
]

export function useSchedules() {
  return useQuery({
    queryKey: ['schedules'],
    queryFn: () => api<ScheduleRow[]>('/schedules'),
  })
}
```

- [ ] **Step 4: Write the form**

Create `frontend/src/components/ScheduleForm.tsx`:

```tsx
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { api, ApiError } from '../api/client'
import { SCHEDULABLE } from '../api/schedules'
import { Button } from './ui/button'

const input = 'w-full rounded-ctl border border-line bg-panel-2 px-3 py-2 text-[13px] text-text'
const label = 'mb-1 block text-[11.5px] uppercase tracking-wide text-text-3'

type Named = { id: number; name: string }

/** Create one schedule. `jobKind` pins the kind and hides the picker, which is
 *  how the Backups page's "New job" reuses this without a second component. */
export function ScheduleForm({ jobKind, onSaved }:
  { jobKind?: string; onSaved: () => void }) {
  const qc = useQueryClient()
  const [name, setName] = useState('')
  const [kind, setKind] = useState(jobKind ?? 'backup.run')
  const [cron, setCron] = useState('0 2 * * *')
  // The browser's zone, not UTC: someone typing "2am" means 2am where they
  // live, and the backend stores an IANA name so DST is handled for them.
  const [tz, setTz] = useState(Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC')
  const [targetId, setTargetId] = useState('')

  const spec = SCHEDULABLE.find((s) => s.kind === kind)
  const needs = spec?.needs ?? null

  const targets = useQuery({
    queryKey: needs === 'app' ? ['apps'] : ['hosts'],
    queryFn: () => api<Named[]>(needs === 'app' ? '/apps' : '/hosts'),
    enabled: needs != null,
  })

  const create = useMutation({
    mutationFn: () => {
      const params: Record<string, number> = {}
      if (needs === 'host' && targetId) params.host_id = Number(targetId)
      if (needs === 'app' && targetId) params.app_id = Number(targetId)
      return api('/schedules', {
        method: 'POST',
        body: JSON.stringify({ name, job_kind: kind, cron, timezone: tz,
                               params, enabled: true }),
      })
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['schedules'] })
      onSaved()
    },
    // The backend's 422 carries the actual cron parser error ("Wrong number of
    // fields; got 4, expected 5"), which is far more useful than "invalid".
    onError: (e) => toast.error(
      e instanceof ApiError && typeof (e.body as any)?.detail === 'string'
        ? (e.body as any).detail
        : 'Could not create that schedule — check the fields and try again.'),
  })

  return (
    <form className="grid grid-cols-1 gap-3 sm:grid-cols-2"
          onSubmit={(e) => { e.preventDefault(); create.mutate() }}>
      <div className="sm:col-span-2">
        <label className={label} htmlFor="sc-name">Name</label>
        <input id="sc-name" className={input} value={name} required
               onChange={(e) => setName(e.target.value)} />
      </div>

      {!jobKind && (
        <div>
          <label className={label} htmlFor="sc-kind">What to run</label>
          <select id="sc-kind" className={input} value={kind}
                  onChange={(e) => { setKind(e.target.value); setTargetId('') }}>
            {SCHEDULABLE.map((s) =>
              <option key={s.kind} value={s.kind}>{s.label}</option>)}
          </select>
        </div>
      )}

      {needs && (
        <div>
          <label className={label} htmlFor="sc-target">
            {needs === 'app' ? 'App' : 'Host'}
          </label>
          <select id="sc-target" className={input} value={targetId}
                  onChange={(e) => setTargetId(e.target.value)}>
            <option value="">Select…</option>
            {(targets.data ?? []).map((t) =>
              <option key={t.id} value={t.id}>{t.name}</option>)}
          </select>
        </div>
      )}

      <div>
        <label className={label} htmlFor="sc-cron">Cron (5 fields)</label>
        <input id="sc-cron" className={`${input} font-mono`} value={cron} required
               onChange={(e) => setCron(e.target.value)} />
        <span className="mt-1 block text-[11px] text-text-3">
          min hour day-of-month month day-of-week — e.g. <code>0 2 * * *</code> is 02:00 daily
        </span>
      </div>

      <div>
        <label className={label} htmlFor="sc-tz">Timezone</label>
        <input id="sc-tz" className={`${input} font-mono`} value={tz} required
               onChange={(e) => setTz(e.target.value)} />
      </div>

      <div className="sm:col-span-2">
        <Button type="submit" disabled={create.isPending}>Create schedule</Button>
      </div>
    </form>
  )
}
```

- [ ] **Step 5: Add the Settings card and replace the General placeholder**

In `frontend/src/routes/settings.tsx`, export a `SchedulesCard` (so the test can mount it alone) and render it in place of the "General" placeholder card:

```tsx
export function SchedulesCard() {
  const qc = useQueryClient()
  const schedules = useSchedules()
  const [adding, setAdding] = useState(false)

  const toggle = useMutation({
    mutationFn: (s: ScheduleRow) => api(`/schedules/${s.id}`, {
      method: 'PATCH', body: JSON.stringify({ enabled: !s.enabled }),
    }),
    onError: () => toast.error('Could not update that schedule — try again.'),
    onSettled: () => qc.invalidateQueries({ queryKey: ['schedules'] }),
  })
  const runNow = useMutation({
    mutationFn: (id: number) => api(`/schedules/${id}/run`, { method: 'POST' }),
    onSuccess: () => toast.success('Started — follow it in the activity drawer.'),
    onError: () => toast.error('Could not start that job — try again.'),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ['schedules'] })
      qc.invalidateQueries({ queryKey: ['jobs'] })
    },
  })
  const remove = useMutation({
    mutationFn: (id: number) => api(`/schedules/${id}`, { method: 'DELETE' }),
    onError: () => toast.error('Could not remove that schedule — try again.'),
    onSettled: () => qc.invalidateQueries({ queryKey: ['schedules'] }),
  })

  return (
    <Card title="Schedules"
          action={<Button variant="ghost" onClick={() => setAdding(a => !a)}>
            {adding ? 'Close' : 'New schedule'}
          </Button>}>
      <table className="w-full text-left text-[13px]">
        <thead><tr className="text-[10.5px] uppercase tracking-wide text-text-3">
          <th className="pb-2">Name</th><th>Runs</th><th>Cron</th><th>Next</th>
          <th>State</th><th /></tr></thead>
        <tbody>
          {(schedules.data ?? []).map(s => (
            <tr key={s.id} className="border-t border-line-soft hover:bg-panel-2">
              <td className="py-2">
                {s.name}
                {s.created_by == null && (
                  <span className="ml-2 rounded-tile bg-panel-2 px-1.5 py-0.5
                                   font-mono text-[10px] uppercase text-text-3">
                    system
                  </span>
                )}
              </td>
              <td className="font-mono text-[12px] text-text-2">{s.job_kind}</td>
              <td className="font-mono text-[12px] text-text-2">{s.cron}</td>
              <td className="font-mono text-[11.5px] text-text-3">
                {s.next_run_at ? new Date(s.next_run_at).toLocaleString() : '—'}
                <span className="ml-1">{s.timezone}</span>
              </td>
              <td className={s.enabled ? 'text-green' : 'text-text-3'}>
                {s.enabled ? 'enabled' : 'disabled'}
              </td>
              <td className="py-2 text-right whitespace-nowrap">
                <Button variant="ghost" className="px-2 py-1 text-[11px]"
                        disabled={runNow.isPending}
                        onClick={() => runNow.mutate(s.id)}>Run now</Button>
                <Button variant="ghost" className="ml-2 px-2 py-1 text-[11px]"
                        disabled={toggle.isPending}
                        onClick={() => toggle.mutate(s)}>
                  {s.enabled ? 'Disable' : 'Enable'}
                </Button>
                <Button variant="danger" className="ml-2 px-2 py-1 text-[11px]"
                        onClick={() => {
                          if (window.confirm(`Remove schedule "${s.name}"?`)) {
                            remove.mutate(s.id)
                          }
                        }}>Remove</Button>
              </td>
            </tr>
          ))}
          {!schedules.data?.length && (
            <tr><td colSpan={6} className="py-4 text-text-3">
              No schedules yet. Add one for nightly backups or an auto-update window.
            </td></tr>
          )}
        </tbody>
      </table>
      {adding && <div className="mt-4 border-t border-line-soft pt-4">
        <ScheduleForm onSaved={() => setAdding(false)} />
      </div>}
    </Card>
  )
}
```

Replace the General card body's placeholder sentence with something true now that schedules exist:

```tsx
      <Card title="General">
        <p className="text-[12.5px] text-text-3">
          Auto-update windows, scheduled backups and catalog sync are all
          schedules — add them above. Alert rules live on the{' '}
          <Link to={'/alerts' as never} className="text-amber">Alerts</Link> page.
        </p>
      </Card>
```

Add the needed imports to `settings.tsx`: `Link` from `@tanstack/react-router`, `useSchedules`/`ScheduleRow` from `../api/schedules`, `ScheduleForm` from `../components/ScheduleForm`.

- [ ] **Step 6: Wire the Backups page**

In `frontend/src/routes/backups.tsx`:

1. Replace the disabled "New job" button with a live one that opens a dialog rendering `<ScheduleForm jobKind="backup.run" … />` in the same dialog shell `RunDialog` uses. Delete the `title="Scheduled backup jobs arrive with the Phase 7 scheduler."` attribute — the placeholder is paid.
2. Fill the "Next scheduled" stat card from `useSchedules()`:

```tsx
  const schedules = useSchedules()
  const nextBackup = (schedules.data ?? [])
    .filter((s) => s.enabled && s.job_kind === 'backup.run' && s.next_run_at)
    .sort((a, b) => (a.next_run_at! < b.next_run_at! ? -1 : 1))[0]
```

```tsx
        <StatCard label="Next scheduled"
          value={nextBackup ? new Date(nextBackup.next_run_at!).toLocaleString() : '—'}
          note={nextBackup
            ? `${nextBackup.name} · ${nextBackup.cron} ${nextBackup.timezone}`
            : 'No backup schedule yet — "New job" creates one.'} />
```

- [ ] **Step 7: Run the tests, build and lint**

Run: `npm test && npm run build && npm run lint`
Expected: PASS, 9 new tests. `src/tests/settings.test.tsx` asserts the old General-card copy — update it.

- [ ] **Step 8: Confirm no Phase 7 placeholder survives**

Run:

```bash
grep -rn "Phase 7\|Phases 4–7\|Phase-7" frontend/src/
```

Expected: no hit that promises future work. Any survivor is an unpaid bill from this task.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/api/schedules.ts frontend/src/components/ScheduleForm.tsx frontend/src/routes/settings.tsx frontend/src/routes/backups.tsx frontend/src/tests/
git commit -m "feat(ui): schedules card in Settings, live 'New job' and next-run on Backups

Pays off the three Phase 7 placeholders the earlier phases left behind."
```

---

## Task 18: Frontend — update badge, "Update to X", and "Update all"

**Files:**
- Modify: `frontend/src/routes/apps.tsx`, `frontend/src/routes/cluster.tsx`, `frontend/src/api/hooks.ts`
- Test: `frontend/src/tests/updates.test.tsx`

**Interfaces:**
- Consumes: Task 6's `GET/POST /apps/{id}/update`, Task 7's `POST /apps/update-all`.
- Produces: nothing downstream.

**Doc 06 asks for exactly three things**, all quoted from its route table: the app-detail head shows a *"update available" badge*; the Overview KV grid ends with an *"Update to vX" button*; the Cluster page's Apps section has an *"Update all"* action. `AppCard` already renders its `UPDATE` corner tag from `app.update_available` — Task 4 is what finally makes that field non-null, so the card needs no change.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/tests/updates.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

const posted: { path: string; method: string; body: any }[] = []
let app: any = null
let updateInfo: any = null

vi.mock('../api/client', () => ({
  ApiError: class extends Error {},
  api: vi.fn((path: string, opts?: RequestInit) => {
    const method = (opts?.method ?? 'GET').toUpperCase()
    if (method !== 'GET') {
      posted.push({ path, method, body: opts?.body ? JSON.parse(String(opts.body)) : null })
      if (path === '/apps/update-all') return Promise.resolve({ jobs: [{ id: 1 }], skipped: [] })
      return Promise.resolve({ job: { id: 1, kind: 'app.update' } })
    }
    if (path.endsWith('/update')) return Promise.resolve(updateInfo)
    if (path.startsWith('/apps/')) return Promise.resolve(app)
    if (path === '/entitlements') return Promise.resolve({
      tier: 'builtin', features: { 'store.update': true, 'store.update_all': true },
      grace: null })
    return Promise.resolve([])
  }),
}))

import { UpdatePanel } from '../routes/apps'
import { UpdateAllButton } from '../routes/cluster'

const wrap = (ui: React.ReactNode) => {
  const qc = new QueryClient({ defaultOptions: {
    queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

describe('UpdatePanel', () => {
  it('says up to date when nothing is pending', async () => {
    posted.length = 0
    app = { id: 1, name: 'Redis', update_available: null }
    updateInfo = { update_available: null, from_ref: 'a'.repeat(40),
                   to_ref: 'a'.repeat(40), diff_vs_upstream: null }
    wrap(<UpdatePanel appId={1} app={app} />)
    await waitFor(() => expect(screen.getByText(/up to date/i)).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: /update to/i })).toBeNull()
  })

  it('offers "Update to <sha>" when one is available', async () => {
    posted.length = 0
    app = { id: 1, name: 'Redis', update_available: 'b'.repeat(7) }
    updateInfo = { update_available: 'b'.repeat(7), from_ref: 'a'.repeat(40),
                   to_ref: 'b'.repeat(40), diff_vs_upstream: '--- upstream\n+++ pinned\n' }
    wrap(<UpdatePanel appId={1} app={app} />)
    await waitFor(() => expect(
      screen.getByRole('button', { name: new RegExp(`update to ${'b'.repeat(7)}`, 'i') })
    ).toBeInTheDocument())
  })

  it('requires the root-consent checkbox before it will post', async () => {
    posted.length = 0
    app = { id: 1, name: 'Redis', update_available: 'b'.repeat(7) }
    updateInfo = { update_available: 'b'.repeat(7), from_ref: 'a'.repeat(40),
                   to_ref: 'b'.repeat(40), diff_vs_upstream: null }
    wrap(<UpdatePanel appId={1} app={app} />)
    const btn = await screen.findByRole('button', { name: /update to/i })
    expect(btn).toBeDisabled()
    fireEvent.click(screen.getByLabelText(/runs as root/i))
    await waitFor(() => expect(btn).not.toBeDisabled())
    fireEvent.click(btn)
    await waitFor(() => expect(posted.length).toBe(1))
    expect(posted[0]).toMatchObject({ path: '/apps/1/update', method: 'POST',
                                      body: { consent: true } })
  })

  it('shows the upstream diff so the operator sees what will run', async () => {
    posted.length = 0
    app = { id: 1, name: 'Redis', update_available: 'b'.repeat(7) }
    updateInfo = { update_available: 'b'.repeat(7), from_ref: 'a'.repeat(40),
                   to_ref: 'b'.repeat(40),
                   diff_vs_upstream: '--- upstream\n+++ pinned\n-old\n+new\n' }
    wrap(<UpdatePanel appId={1} app={app} />)
    await waitFor(() => expect(screen.getByText(/\+new/)).toBeInTheDocument())
  })
})

describe('UpdateAllButton', () => {
  it('posts update-all with consent after confirming', async () => {
    posted.length = 0
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    wrap(<UpdateAllButton />)
    fireEvent.click(screen.getByRole('button', { name: /update all/i }))
    await waitFor(() => expect(posted.length).toBe(1))
    expect(posted[0]).toMatchObject({ path: '/apps/update-all', method: 'POST',
                                      body: { consent: true } })
  })

  it('posts nothing when the confirm is dismissed', async () => {
    posted.length = 0
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    wrap(<UpdateAllButton />)
    fireEvent.click(screen.getByRole('button', { name: /update all/i }))
    await new Promise((r) => setTimeout(r, 0))
    expect(posted.length).toBe(0)
  })
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npm test -- updates`
Expected: `UpdatePanel is not exported from '../routes/apps'`.

- [ ] **Step 3: Add the update types**

In `frontend/src/api/hooks.ts`:

```ts
export type UpdateInfo = {
  update_available: string | null
  from_ref: string | null
  to_ref: string | null
  diff_vs_upstream: string | null
}
```

- [ ] **Step 4: Write and mount `UpdatePanel`**

In `frontend/src/routes/apps.tsx`, add (exported, so the test can mount it directly):

```tsx
/** Doc 06 App detail Overview: the Details KV grid's "Update" row plus an
 *  "Update to vX" button. X is a short commit sha, not a version — see
 *  services/appstore.py::mark_updates_available for why that is the only
 *  honest thing community-scripts lets us say. */
export function UpdatePanel({ appId, app }:
  { appId: number; app: { name: string; update_available: string | null } }) {
  const qc = useQueryClient()
  const [consent, setConsent] = useState(false)
  const info = useQuery({
    queryKey: ['apps', appId, 'update'],
    queryFn: () => api<UpdateInfo>(`/apps/${appId}/update`),
  })
  const run = useMutation({
    mutationFn: () => api(`/apps/${appId}/update`, {
      method: 'POST', body: JSON.stringify({ consent: true }),
    }),
    onSuccess: () => toast.success('Update started — follow it in the activity drawer.'),
    onError: () => toast.error('Could not start the update — try again.'),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ['apps'] })
      qc.invalidateQueries({ queryKey: ['jobs'] })
    },
  })

  const pending = info.data?.update_available ?? app.update_available
  if (!pending) {
    return <div className="text-[12.5px] text-text-3">Up to date.</div>
  }
  return (
    <div>
      <div className="mb-3 font-mono text-[12px] text-text-2">
        {info.data?.from_ref?.slice(0, 7) ?? '?'} → {info.data?.to_ref?.slice(0, 7) ?? pending}
      </div>
      {info.data?.diff_vs_upstream && (
        <pre className="mb-3 max-h-64 overflow-auto rounded-tile border border-line-soft
                        bg-panel-2 p-3 font-mono text-[11.5px] text-text-2">
          {info.data.diff_vs_upstream}
        </pre>
      )}
      <label className="mb-3 flex items-start gap-2 text-[12.5px] text-text-2">
        <input type="checkbox" checked={consent}
               onChange={(e) => setConsent(e.target.checked)} />
        <span>
          I understand this runs as root on the node hosting {app.name}.
        </span>
      </label>
      <Button disabled={!consent || run.isPending} onClick={() => run.mutate()}>
        Update to {pending}
      </Button>
    </div>
  )
}
```

Mount it in the app-detail Overview, in a card beneath the KV grid, and change the KV grid's `Update` row so it reads the same field it already does (`app.update_available ?? 'Up to date'` — unchanged). Add the "update available" badge to the detail head next to the name:

```tsx
        {app.update_available && (
          <span className="ml-2 rounded-tile bg-amber-dim px-2 py-0.5
                           font-mono text-[10.5px] uppercase text-amber">
            update available
          </span>
        )}
```

Add the imports `apps.tsx` needs: `useMutation`, `useQueryClient` from `@tanstack/react-query`, `toast` from `sonner`, `UpdateInfo` from `../api/hooks`, `Button` from `../components/ui/button`.

- [ ] **Step 5: Write and mount `UpdateAllButton`**

In `frontend/src/routes/cluster.tsx`, add (exported):

```tsx
/** Doc 06 Cluster overview: the Apps section's "Update all" action. One
 *  confirm covers the whole batch — the backend still requires explicit
 *  consent, and enqueues one job per stale app so each has its own transcript. */
export function UpdateAllButton() {
  const qc = useQueryClient()
  const run = useMutation({
    mutationFn: () => api<{ jobs: { id: number }[]; skipped: { reason: string }[] }>(
      '/apps/update-all', { method: 'POST', body: JSON.stringify({ consent: true }) }),
    onSuccess: (r) => {
      if (r.jobs.length === 0) {
        // Never a bare silence: "nothing happened" and "it is broken" look
        // identical otherwise.
        toast('Nothing to update — every app is on its catalog commit.')
        return
      }
      toast.success(`Updating ${r.jobs.length} app${r.jobs.length === 1 ? '' : 's'} — `
                    + 'follow them in the activity drawer.')
    },
    onError: () => toast.error('Could not start the updates — try again.'),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ['apps'] })
      qc.invalidateQueries({ queryKey: ['jobs'] })
    },
  })
  return (
    <Button variant="ghost" disabled={run.isPending} onClick={() => {
      if (window.confirm('Update every app that has a newer catalog commit? '
                         + 'Each update runs a community script as root on its node.')) {
        run.mutate()
      }
    }}>Update all</Button>
  )
}
```

Render it in the Apps section header next to the existing "View all" link, per doc 06's route table (*"Apps section (first 8 app cards, 'View all', 'Update all')"*).

- [ ] **Step 6: Run the tests, build and lint**

Run: `npm test && npm run build && npm run lint`
Expected: PASS, 6 new tests.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/routes/apps.tsx frontend/src/routes/cluster.tsx frontend/src/api/hooks.ts frontend/src/tests/updates.test.tsx
git commit -m "feat(ui): update-available badge, 'Update to <sha>' with diff + consent, 'Update all'"
```

---

## Task 19: Definition of Done, notes, doc amendments, buildlog

**Files:**
- Create: `backend/dod_verify_phase7.py` (throwaway, **not committed** — same as `dod_verify_phase5.py` / `dod_verify_phase6.py`)
- Create: `docs/notes/phase-7-operate.md`
- Modify: `docs/03-technology-dependency-map.md`, `docs/02-system-architecture.md`, `docs/04-data-model.md`, `buildlog.md`

**Doc 10's Phase 7 DoD, verbatim:** *"an unattended weekend: scheduled backups and an auto-update window run, an induced CPU alert fires and resolves with notifications both ways, and Monday's job history tells the whole story."*

Verified without a live PVE and without a browser (the standing limitation of this box, stated in every prior phase's notes): `tests.support.make_app` + `FakePVE` + the fake SSH factory drive the real routes, the real `JobBackend`, the real `Scheduler` and the real evaluator.

- [ ] **Step 1: Write the DoD script**

Create `backend/dod_verify_phase7.py`, modelled on `dod_verify_phase6.py`'s structure (`_login` helper, `TestClient`, `FakePVE`), proving four clauses:

1. **A scheduled backup runs.** Create a schedule with `job_kind="backup.run"` and a cron already in the past for its `next_run_at`; call `proxploy.jobs.scheduler.tick(app)` directly rather than waiting on wall-clock; assert a `Job(kind="backup.run", schedule_id=<id>, requested_by=None)` exists, that it reaches a terminal state via `app.state.jobs.wait(job_id)`, and that `schedules.next_run_at` advanced past `now`.
2. **An auto-update window runs.** Seed an app pinned behind its catalog entry; create a `job_kind="app.update"` schedule due now; `tick`; assert the `app.update` job ran through the fake SSH executor, that `app_scripts` gained a version pinned to the new sha, and that `apps.update_available` cleared.
3. **A CPU alert fires and resolves, with a notification each way.** Monkeypatch `proxploy.services.notifier.send_one` to record calls. Seed a channel and a `cpu_pct > 85 for 0s` rule; write breaching samples; `evaluate` → assert one `firing` transition, one `alert.fired` send, one `alert` SSE frame on a `bus.subscribe()` queue. Write healthy samples; `evaluate` → assert one `resolved` transition and a second send. Assert the alert row's `state`, `fired_at` and `resolved_at`.
4. **Monday's history tells the story.** `GET /api/v1/cluster/activity?limit=20` contains the backup job, the update job, and both alert rows; every one carries a non-null `at`; the alert rows carry `kind == "alert"` and their severity.

Run it:

```bash
./.venv/bin/python dod_verify_phase7.py
```

Expected: every clause prints `OK` and the script exits 0. If a clause cannot be proven without live hardware, print it as an explicit `SKIPPED (needs live PVE)` line rather than silently passing — and record the skip in the notes file below.

- [ ] **Step 2: Run both suites one final time**

```bash
cd backend && ./.venv/bin/python -m pytest tests/ -m "not pve_integration and not e2e" -q
cd ../frontend && npm test && npm run build && npm run lint
```

Expected: backend well above its 499-passed baseline, frontend well above 121. Record the exact numbers — they go in the buildlog.

- [ ] **Step 3: Confirm the schema really did not move**

```bash
cd backend && ./.venv/bin/python -m alembic -c alembic.ini heads
```

Expected: `2330a95b98d2 (head)`, unchanged from Phase 6. A new revision here means someone added a migration this phase did not need — go back and find out why.

- [ ] **Step 4: Write the phase notes**

Create `docs/notes/phase-7-operate.md` following `docs/notes/phase-6-infra.md`'s shape (`## What shipped, per subsystem`, then a section per finding). It must contain, at minimum:

- **APScheduler 4 does not exist.** PyPI's maximum stable is 3.11.3; 4.x is `a1`–`a6` only, verified 2026-08-01. Docs 02/03/04/09/10 all named "APScheduler 4". Doc 03 marks Scheduling "Provisional (seam: `Scheduler`)", so this shipped on 3.11.3, and only `CronTrigger` is used — the tick loop in `jobs/scheduler.py` replaces `BaseScheduler` entirely, because doc 04 makes the `schedules` table authoritative and a second in-memory registry would be two sources of truth to reconcile on every CRUD write.
- **Zero migrations, again.** `schedules`, `alert_rules` and `alerts` have existed with full column parity since migration 0001. Alembic head unchanged at `2330a95b98d2`.
- **The poller never wrote `mem_pct` or `disk_pct`.** Doc 04's `alert_rules.metric` enum named both. Any memory or disk rule would have sat `enabled` and never fired. Fixed in Task 8; `disk_pct` is host-only and Task 12 rejects guest disk rules at write time rather than accepting one that cannot fire.
- **`metrics_loop` is gone.** Doc 04 requires pruning to run "as scheduled system jobs (visible in the activity feed like any other job)"; it now does, hourly, via the seeded `Metrics maintenance` schedule. Rollup cadence moved from 5 min to hourly with a wider idempotent lookback — charts under six hours read raw samples, so nothing user-visible lags.
- **RESIDUAL LIMITATION — the community-scripts update path.** A `ct/<slug>.sh` decides install-vs-update itself inside `build.func`'s `start`. Proxploy cannot see that decision, so `app.update` brackets the SSH run with a CT-must-exist preflight and a no-new-CT post-check, and fails loudly naming any stray container. Whether a given entry's update path is non-interactive is a property of that upstream script; `services/classifier.py` classifies **install** feasibility only. An update path that prompts aborts under `catch_errors` and the job fails with the transcript archived. Classifying update paths is separate, later work.
- **RESIDUAL LIMITATION — no browser on this box.** Every frontend claim rests on Vitest + jsdom. `/alerts`, the health footer, the Schedules card and the update controls have never been rendered in a real browser. Same gap Phases 5 and 6 recorded.
- **`update_available` is a commit sha, not a version.** community-scripts publishes no version numbers; the honest signal is "pinned commit is behind the catalog commit", and doc 06's "Update to vX" renders the short sha.

- [ ] **Step 5: Amend the design docs**

Three amendments, each marked as an amendment with its date and reason (Phase 6's doc-05 amendment is the precedent for the format):

1. `docs/03-technology-dependency-map.md` — the Scheduling row: version `APScheduler 3.11` (not 4), MIT **verified** (not †), and a note that only `CronTrigger` is used, the `Scheduler` seam being satisfied by `jobs/scheduler.py`. Add `tzlocal` (MIT, transitive).
2. `docs/02-system-architecture.md` — lines 34, 108, 244 and 315 say "APScheduler 4". Correct the version and, at line 315, the claim that "APScheduler jobs roll raw samples into rollups": that is now the `metrics.maintain` job fired by the `schedules` tick.
3. `docs/04-data-model.md` §`schedules` — the sentence "APScheduler's own state is reconstructed from these rows at boot" is now literally true in a stronger sense than written: there is no APScheduler state at all. Reword to say the tick loop reads this table directly.

- [ ] **Step 6: Write the buildlog entry**

Append a Phase 7 section to `buildlog.md` in the established narrative voice, covering: what shipped per subsystem; the three verified findings that contradicted the docs (APScheduler 4 not existing, the missing `mem_pct`/`disk_pct` samples, zero migrations); the two residual limitations; final suite counts from Step 2; the Alembic head from Step 3; and the commit range for the phase (`git log --oneline b36846c..HEAD | tail -1` gives the first commit).

- [ ] **Step 7: Commit**

```bash
git add docs/ buildlog.md
git commit -m "docs(phase-7): verification notes, doc 02/03/04 amendments, buildlog entry

APScheduler 4 does not exist as a release — amends the four docs that named
it. Records the poller's missing mem_pct/disk_pct samples and the two
residual limitations (community-scripts update path, no browser here)."
```

- [ ] **Step 8: Confirm the working tree is clean and the throwaway script is not committed**

```bash
git status --short
```

Expected: empty, and `backend/dod_verify_phase7.py` untracked or deleted — matching how `dod_verify_phase5.py` and `dod_verify_phase6.py` were handled.

---

## Self-Review

Run against doc 10 §"Phase 7 — Operate" and docs 04/05/06.

**1. Spec coverage**

| Spec requirement | Task |
|---|---|
| Update pipeline: per-app update, same pin/diff/consent/stream/archive path as install | 4, 5, 6 |
| Update-all queue with per-app results | 7 |
| Scheduler in production, `schedules` CRUD + UI | 1, 2, 3, 17 |
| Auto-update windows | 3 (`store.auto_update` gate), 17 |
| Scheduled backup jobs | 3, 17 |
| Catalog refresh on a schedule | 2 (`SYSTEM_SCHEDULES`) |
| Metric/audit pruning as scheduled jobs | 2 (`metrics.maintain`) |
| `alert_rules` CRUD | 12 |
| Evaluator riding the poll loop | 9, 11 |
| Firing / resolved / acknowledge lifecycle | 9, 13 |
| Alert history | 13, 16 |
| Routing through Notifier | 10 |
| Event-class → channel routing UI | 10 (backend), 16 (rule form states the routing) |
| Doc 05 `/schedules` ×5, `/alert-rules` ×4, `/alerts` ×2, `/apps/{id}/update`, `/apps/update-all` | 3, 6, 7, 12, 13 |
| Doc 05 SSE `alert` event | 11, 15 |
| Doc 06 HealthFooter bound to `/alerts?state=firing` | 15 |
| Doc 06 `['alerts','firing']` 60 s query | 15 |
| Doc 06 "update available" badge + "Update to vX" | 18 |
| Doc 06 Cluster "Update all" | 18 |
| Doc 06 Backups "New job" + "Next scheduled" | 17 |
| Doc 10 DoD (unattended weekend) | 19 |

**Gaps accepted, and why, rather than left silent:**

- **`audit_events` pruning is not scheduled.** Doc 04 §retention is explicit that audit rows have *"no automatic pruning by default"* and that the opt-in `audit.retention` policy is an export-then-prune flow gated on rows landing in a completed archive — with `proxploy audit export` as the CLI entry point. No CLI exists yet (that is Phase 9 "Deliver"), and scheduling a delete without the export half would be exactly the data loss doc 04 forbids. `metrics.maintain` covers metric pruning, which is what doc 10 Phase 7 actually names. Recorded in the Task 19 notes.
- **Per-rule channel selection has no UI control.** The backend honours `alert_rules.channel_ids` fully (Tasks 10, 12) and the rule form posts `[]`, meaning "use the normal event subscription" — which is the sane default and the one doc 04 describes. A channel multi-select is a small additive change to `AlertRuleForm`; it is not required by any doc 06 line and is not worth a task of its own.
- **`backup_failed` alerts read `jobs`, not `backups`.** Doc 04 lists the metric without defining its source. The `backup.run` job's terminal status is the fact Proxploy actually owns; PBS verify state lives in `backups.verify_state` and is a different question (did the archive verify) from this one (did the run fail). Noted in `services/alerts.py`.

**2. Placeholder scan** — every step carries the literal code or the literal command. Three steps deliberately hand judgement to the implementer rather than guessing, and each says so explicitly and says what to check: Task 5 Step 1 (the `tests/fakes/ssh.py` and `FakePVE` helper names — verify against `test_appstore_install.py` before writing), Task 17 Step 1 (reuse `backups.test.tsx`'s existing mock), Task 19 Step 1 (the DoD script's clause-by-clause shape). No "TBD", no "add error handling", no "similar to Task N".

**3. Type consistency**

- `next_fire(cron, tz, after)` — same signature in Tasks 1, 2, 3.
- `tick(app, now=None)` — Task 1 defines it, Task 2's `Scheduler.run` calls it, Task 19's DoD script calls it directly.
- `_target(params)` — Task 1 defines it; Task 3's `run_schedule_now` imports it by that exact name.
- `pinned_ref(db, app_id)` / `mark_updates_available(db)` / `SHORT_SHA` — Task 4 defines, Tasks 5 and 6 consume.
- `_update_state(db, app_id)` — Task 6 defines, Task 7 reads the same three fields (`entry.upstream_sha`, `latest.upstream_ref`) inline rather than importing it, so no ordering dependency inside the module.
- `UpdateIn` — defined in Task 6 but **used** in Task 7's earlier-registered route; Task 7 Step 3 explicitly says to hoist the model definition above `update_all_apps`.
- `METRIC_TARGETS` / `STATUS_METRICS` — Task 9 defines, Task 12 imports both by name.
- `alert_out(a, rules, labels, emails)` — Task 13 defines with four args; Task 14 does not call it (it builds its own feed-shaped row), so no arity mismatch.
- `channels_for(db, event, only_ids=None)` / `notify(app, event, title, body, only_ids=None)` — Task 10 widens both; `JobBackend._notify_async` calls `notify` with four positional args and is unaffected by a trailing keyword-defaulted parameter.
- Frontend: `AlertRow`, `AlertRuleRow`, `MetricSpec`, `ScheduleRow`, `UpdateInfo` each declared once; `applyAlert(qc, d, toast?)` matches `LiveProvider`'s call; `useFiringAlerts` used by both `HealthFooter` and `AlertsPage`.
- `ActivityRow` gains `severity` and `message` in Task 15; Task 14 adds those keys to **all three** row kinds on the backend so the type is honest for every row.

**4. Cross-task ordering risks, called out where they bite**

- Task 2 must land before Task 3: `create_schedule` calls `validate()`, which checks `HANDLERS` — and `metrics.maintain` only exists after Task 2.
- Task 8 must land before Task 9's `mem_pct`/`disk_pct` tests mean anything.
- Task 12 must land before Task 16 (the rule form fetches `/alert-rules/metrics`).
- Task 14 changes the shape of every activity row; Task 15 updates the frontend type. If they are worked out of order the frontend compiles either way (the new keys are optional at runtime) but `ActivityFeed`'s alert badge renders as `—` until both land.
