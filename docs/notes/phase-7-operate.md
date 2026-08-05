# Phase 7 (Operate) — verification notes

## What shipped, per subsystem

**Scheduler** — `backend/proxploy/jobs/scheduler.py`: `next_fire(cron, tz,
after)` (naive-UTC-in, naive-UTC-out wrapper around `CronTrigger`, strictly-
after semantics so a tick never re-fires the schedule it just fired),
`validate()`, `prime()`/`due()`/`fire_one()`/`tick(app, now=None)` — the whole
pass over `schedules`, and `_target(job_kind, params)`, which derives a fired
job's `target_type`/`target_id` from the job kind's dotted prefix rather than
sniffing param key names (a lifecycle kind carries a bare `target_id`,
`backup.run` carries `host_id`, `app.update` carries `app_id` — sniffing
mis-derived every lifecycle kind before this fix). `SYSTEM_SCHEDULES` seeds
"Catalog refresh" (nightly) and "Metrics maintenance" (hourly) at boot,
one-way: an operator-disabled system row stays disabled across restarts. The
`Scheduler` class (`jobs/scheduler.py`) is a `pollers.Poller`-shaped
supervisor loop wired into `main.py`'s lifespan, ticking every
`scheduler_tick_s` (30s default) and publishing a `job` SSE delta per fired
schedule. `backend/proxploy/api/schedules.py`: `GET`/`POST /schedules`,
`PATCH`/`DELETE /schedules/{id}`, `POST /schedules/{id}/run` (run-now,
bypassing the cron), all validated against the tick loop's own `validate()`
so a 422 at write time is the only way a bad row ever reaches the table.
Frontend: `api/schedules.ts`, `ScheduleForm.tsx`, a Schedules card in
Settings with live "next run" and a manual "Run now", and "Next scheduled" on
the Backups page.

**App updates** — `backend/proxploy/services/appstore.py` gained
`pinned_ref(db, app_id)` (the upstream commit the app's newest `app_scripts`
row came from), `mark_updates_available(db)` (recomputes `apps.
update_available` for every app — derived state, recomputed wholesale rather
than latched, so an app that updated or whose catalog entry rolled back stops
advertising a stale update), and the `app.update` job handler: re-runs the
catalog script pinned to the CURRENT upstream commit over the same SSH path
`app.install` uses, bracketed by a CT-must-exist-before guard and a
no-new-CT-after guard (a community-scripts `ct/*.sh` decides install-vs-
update for itself inside `build.func`, and Proxploy cannot see that
decision — see the residual limitation below). `backend/proxploy/api/
apps.py`: `GET`/`POST /apps/{id}/update` (same pin/diff/consent/stream/
archive gate as install), `POST /apps/update-all` (one job per stale app,
each with its own skip reason rather than one job failing for all). Frontend:
an "update available" badge, "Update to `<sha>`" with the same diff-and-
consent dialog as install, and a Cluster "Update all" button gated on the
`store.update_all` entitlement.

**Alerting** — `backend/proxploy/services/alerts.py`: `METRIC_TARGETS`/
`SUPPORTED_METRICS` (which target kinds each metric can honestly be
evaluated against — `disk_pct` is host-only, api/alerts.py rejects a guest
disk rule at write time), `evaluate(db, now)` (one pass over enabled rules,
continuous-breach `duration_s` semantics — walks samples newest-first and
takes the breaching prefix, so a single healthy dip resets the clock — at
most one open alert per rule×target, automatic recovery resolution, `no
samples` is never a breach), `render_message`, `sse_frame`,
`notify_transitions`. `backend/proxploy/pollers/__init__.py`'s supervisor now
calls `evaluate` every poll cycle when `alerts_enabled`, publishes the `alert`
SSE frame, then fans the transition out through `notify_transitions` — in
that order, so a notifier failure never loses the SSE event (see `services/
alerts.py`'s module docstring; verified live by
`test_a_notifier_failure_does_not_lose_the_sse_event`). `backend/proxploy/
api/alerts.py`: `GET`/`POST /alert-rules`, `PATCH`/`DELETE /alert-rules/{id}`,
`GET /alert-rules/metrics`, `GET /alerts`, `POST /alerts/{id}/ack`.
`backend/proxploy/services/notifier.py` widened `channels_for`/`notify` to
accept `only_ids` (a rule's `channel_ids` overrides the normal event
subscription rather than adding to it). `backend/proxploy/api/cluster.py`'s
`GET /cluster/activity` merges jobs + alerts + audit highlights into one
feed, newest-first, with `kind` discriminating the three. Frontend: `api/
alerts.ts`, `AlertRuleForm.tsx` (app/vm/host target pickers), `routes/
alerts.tsx` (firing list with ack, resolved history, rule CRUD),
`HealthFooter.tsx` (bound to `/alerts?state=firing`, a 60s query per doc 06),
SSE `alert` handling in `LiveProvider.tsx`/`api/live.ts`, and the alert badge
+ severity in `ActivityFeed.tsx`.

**Metrics maintenance** — `backend/proxploy/services/metrics.py` gained the
`metrics.maintain` job (rollup + retention pruning as a real scheduled job,
visible in the activity feed like any other job — doc 04's requirement) and
now persists `mem_pct` and host `disk_pct` samples, which the poller had
never written (see the finding below). `metrics_loop` (the old ad-hoc asyncio
loop) is gone; the "Metrics maintenance" system schedule replaces it, hourly,
via the tick loop.

## Findings that contradicted the docs

**APScheduler 4 does not exist.** PyPI's maximum stable release is 3.11.3;
4.x exists only as `4.0.0a1`–`a6` pre-releases — verified 2026-08-01 (`pip
index versions APScheduler` and the PyPI project page both confirm no stable
4.x has ever shipped). Docs 00, 01, 02, 03, 04, 09 and 10 all named "APScheduler
4" — a wider list than this task's amendment scope: `docs/00-decision-brief.
md:79`, `docs/01-product-spec.md:193`, `docs/09-repository-structure.
md:69` and `docs/10-build-sequence.md:226` still say "APScheduler 4" after
this task and were deliberately left unamended (out of scope — the brief's
Step 5 named only docs 02/03/04). Doc 03 already marked Scheduling "Provisional (seam: `Scheduler`)", so this
shipped on the stable 3.11.3 line, and only `CronTrigger` is used — cron
parsing and DST-correct next-fire arithmetic, the one part of scheduling that
must never be hand-rolled. `jobs/scheduler.py`'s tick loop replaces
`BaseScheduler`/`AsyncIOScheduler`/jobstores entirely: doc 04 makes the
`schedules` table authoritative, and a second in-memory registry synced from
it would be two sources of truth to reconcile on every CRUD write. Docs 02
(lines 34, 108, 244, 315), 03 (Scheduling row) and 04 (`schedules` section)
are amended by this task (Step 5, below). Four docs still say "APScheduler 4"
and were **not** in this task's amendment scope — known remaining stale
references, not fixed here: `docs/00-decision-brief.md:79`, `docs/
01-product-spec.md:193`, `docs/09-repository-structure.md:69`, `docs/
10-build-sequence.md:226`.

**Zero migrations, again.** `schedules`, `alert_rules` and `alerts` have
existed with full column parity since migration 0001 — this phase populates
tables that were already shaped for it, exactly like Phase 6's `backups`
table. Alembic head unchanged at `2330a95b98d2` before and after this phase
(confirmed, Step 3).

**The poller never wrote `mem_pct` or `disk_pct`.** Doc 04's `alert_rules.
metric` enum named both `mem_pct` and `disk_pct` as valid metrics, but the
poller (`pollers/__init__.py`, pre-Phase-7) only ever wrote `cpu_pct`,
`net_in_bps` and `net_out_bps` `MetricSample` rows. Any memory or disk alert
rule created before this phase would have sat `enabled=True` and never fired
— not a crash, not a validation error, just silent absence of the exact
signal the rule promised. Fixed in Task 8: the poller now writes `mem_pct`
for hosts, apps and VMs, and `disk_pct` for hosts only. `disk_pct` is
deliberately host-only: `/cluster/resources` reports `maxdisk` (allocated,
not used) for guests and a `disk` figure that is routinely 0 for QEMU, so a
guest `disk_pct` would be confidently wrong rather than merely missing — Task
12 rejects a guest `disk_pct` rule at write time (422) rather than accepting
one that can never honestly fire.

**`metrics_loop` is gone.** Doc 04 requires pruning to run "as scheduled
system jobs (visible in the activity feed like any other job)"; it now does,
hourly, via the seeded "Metrics maintenance" schedule and the `metrics.
maintain` job kind. Rollup cadence moved from the old loop's 5-minute cycle
to the schedule's hourly one, with a wider idempotent lookback window so a
gap between runs never double-counts or drops samples. Charts under six
hours still read raw samples directly, not rollups, so nothing user-visible
lags from the wider cadence.

**`update_available` is a commit sha, not a version.** community-scripts
publishes no version numbers for its install scripts (doc 01 §3); the only
honest signal Proxploy has is "the commit this app is pinned to (`app_scripts.
upstream_ref`) is behind the commit the catalog now holds (`catalog_entries.
upstream_sha`)". `apps.update_available` stores the short sha an update would
move the app to, and doc 06's "Update to vX" button renders that short sha
literally, not a semantic version.

## Residual limitations

**The community-scripts update path.** A `ct/<slug>.sh` decides
install-vs-update for itself inside `build.func`'s `start` function — the
script finds (or doesn't find) the existing container and branches
accordingly. Proxploy cannot see that decision from the outside, so
`app.update` brackets the SSH run with a CT-must-exist preflight (refuses to
run at all if the target CT is missing, since the script would then certainly
install a *second* container) and a no-new-CT postcheck (fails loudly, naming
any stray container, if one appeared during the run — with a concurrency
exclusion so a legitimate `app.install`/`vm.create`/`vm.clone` running at the
same time isn't blamed for someone else's stray). Whether a given catalog
entry's update path is non-interactive at all is a property of that upstream
script; `services/classifier.py` classifies **install** feasibility only. An
update path that prompts aborts under `catch_errors`' `set -Ee` and the job
fails with the full transcript archived — the honest outcome, not a silent
hang. Classifying update paths the way installs are classified is separate,
larger work, not attempted this phase.

**No browser on this box.** Every frontend claim in this phase rests on
Vitest + jsdom (`alerts.test.tsx`, `healthfooter.test.tsx`, `schedules.
test.tsx`, `updates.test.tsx`, `live.test.ts`). `/alerts`, the health footer,
the Schedules card, and the update controls (badge, "Update to `<sha>`" diff
dialog, "Update all") have never been rendered in a real browser on this
box. Same gap Phases 5 and 6 recorded, and the same standing limitation
carried forward again.

**`backup.prune` scheduling is backend-only; the Schedules UI cannot offer
it.** The `backup.prune` job kind is a real `HANDLERS` entry (`services/
backupjobs.py`) and `POST /schedules` accepts `job_kind="backup.prune"`
through the same direct-API path every other schedulable kind uses — nothing
in the scheduler or the route layer refuses it. But `backup.prune` needs a
storage target plus a retention spec (keep-count / keep-age) to mean
anything, and `ScheduleForm.tsx`'s generic job-kind picker has no field that
can collect a storage+retention pair — every other schedulable kind
(`catalog.refresh`, `metrics.maintain`, `backup.run`, `app.update`,
lifecycle kinds) needs at most a single target id, which the form already
handles. Rather than ship a schedule row that silently 500s or no-ops the
first time it fires (because its `params` are empty), `backup.prune` was
dropped from the frontend's `SCHEDULABLE` list entirely (commit `ae83284`,
"drop unconfigurable backup.prune from schedules, require a target before
submit") — a plan defect caught and corrected during Task 17, not an
oversight left in. An operator who wants scheduled pruning today has to
`POST /schedules` directly with a hand-built `params` object; a dedicated
prune-schedule form (storage picker + retention fields) is future UI work,
not a backend gap.

## Gate numbers (real, captured this run)

| Gate | Command | Result |
|---|---|---|
| DoD script | `./.venv/bin/python dod_verify_phase7.py` | **all four doc-10 Phase 7 DoD clauses print OK, exit 0** — run twice, identical output both times |
| Backend tests | `pytest tests/ -q -m "not pve_integration and not e2e"` | **661 passed, 2 skipped, 4 deselected** (baseline going into this phase was 499 passed, 2 skipped) |
| Frontend tests | `npx vitest run` (via `npm test`) | **154 passed across 30 files** (baseline going into this phase was 121 across 26 files) |
| Frontend build | `npm run build` | **clean** (`tsc -b` + vite build; the one pre-existing "chunk > 500 kB" warning is unchanged, not a new regression) |
| Frontend lint | `npm run lint` (oxlint) | **exit 0** — warning-only output (`only-export-components`, `exhaustive-deps`, one `no-unused-expressions`), the same pre-existing classes as every prior phase; no errors, nothing new introduced by this phase |
| Alembic heads | `alembic -c alembic.ini heads` | **`2330a95b98d2` (head)** — unchanged; this phase adds no migration |

## Commit range

`git log --oneline b36846c..HEAD | tail -1` returns `def0526` ("docs(phase-6):
buildlog entry for final review + fix wave, correct false-negative claim") —
that commit is Phase 6's own closing documentation commit, landed one commit
after the `b36846c` boundary. The first substantive Phase 7 commit is the
next one, `ec5ccb9` ("feat(scheduler): cron math, due selection and one-pass
firing over the schedules table"); 26 commits run from there through `ff73dd4`
("fix(ui): gate Update all on store.update_all entitlement") before this
task's own documentation commit.
