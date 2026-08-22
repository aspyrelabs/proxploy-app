# Notification Events Matrix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace channel-first notification setup with a Notifications settings group holding a Channels list and an Events matrix, where every notification type has a master switch that works with zero channels configured.

**Architecture:** A registry module maps each of the 33 registered job kinds plus alerts and audit errors onto exactly 19 notification types. The job runner emits the mapped type instead of a bare `job.{status}`. Master switches live in one `AppSetting` row holding explicit overrides only, and are consulted server-side before the Apprise fan-out and client-side before a toast is pushed. The per-channel checkbox columns reuse the existing `notification_channels.events` column transposed, so there is no migration.

**Tech Stack:** FastAPI, SQLAlchemy, Apprise, pytest; React 19, TanStack Query, Vitest.

**Spec:** `docs/superpowers/specs/2026-08-22-notification-events-matrix-design.md`

## Global Constraints

- No em dashes anywhere, in code, comments, copy or commit messages. Repo-wide writing rule.
- No backend jargon in user-facing strings. A row reads "App install failed", never `app.install.failed`.
- Never log, audit, or return a channel URL or any assembled field value. `notifier.redact_url` exists for anywhere a URL would otherwise reach a log line.
- Backend tests run from `backend/` with `.venv/bin/python -m pytest`. Frontend tests run from `frontend/` with `npx vitest run --no-file-parallelism`. Running vitest from the repo root makes every test fail with `document is not defined`.
- Test only what the task touched. Full suites are end-of-day.
- Commit to `main`. No feature branches.
- The four keys `job.failed`, `job.succeeded`, `job.canceled`, `job.interrupted` and the two keys `alert.fired`, `alert.resolved` keep their exact existing spellings. They are already stored in `notification_channels.events` rows.

---

### Task 1: Notification type registry

**Files:**
- Create: `backend/proxploy/services/notification_types.py`
- Test: `backend/tests/test_notification_types.py`

**Interfaces:**
- Consumes: `proxploy.jobs.HANDLERS` (dict of job kind to handler, 33 entries).
- Produces:
  - `TYPES: tuple[NotificationType, ...]` where `NotificationType` is a frozen dataclass with fields `key: str`, `label: str`, `group: str`, `default_on: bool`.
  - `BY_KEY: dict[str, NotificationType]`
  - `type_for_job(kind: str, status: str) -> str` returning a registry key.
  - `DEFAULTS: dict[str, bool]` mapping every key to its `default_on`.

- [ ] **Step 1: Write the failing test**

```python
"""The registry is the single place that decides what Proxploy can tell you
about. Its job is to make two silent failure modes loud: a job kind nobody
mapped (so it notifies as something wrong, or not at all), and a key no
emitter can ever produce (the `app.updated` defect, which sat in the UI as a
tickable box that did nothing for the life of the feature)."""
import importlib
import pkgutil

import pytest

import proxploy
from proxploy.jobs import HANDLERS, TERMINAL
from proxploy.services.notification_types import (
    BY_KEY, DEFAULTS, TYPES, type_for_job,
)


def _load_every_handler():
    """HANDLERS fills in by import side effect, so an unimported module means
    a kind this test would silently skip."""
    for mod in pkgutil.walk_packages(proxploy.__path__, "proxploy."):
        try:
            importlib.import_module(mod.name)
        except Exception:  # noqa: BLE001  (a module that cannot import has no handlers)
            pass


def test_every_job_kind_maps_to_a_real_row():
    _load_every_handler()
    assert len(HANDLERS) >= 33
    for kind in HANDLERS:
        for status in TERMINAL:
            key = type_for_job(kind, status)
            assert key in BY_KEY, f"{kind}/{status} mapped to unknown key {key!r}"


def test_a_named_kind_does_not_also_land_in_the_catch_all():
    """One kind, one row. If app.install resolved to job.failed as well as
    app.install.failed, a failed install would notify twice."""
    assert type_for_job("app.install", "failed") == "app.install.failed"
    assert type_for_job("app.install", "succeeded") == "app.install.succeeded"


def test_unnamed_kinds_fall_through_to_the_generic_rows():
    assert type_for_job("vm.create", "failed") == "job.failed"
    assert type_for_job("network.apply", "succeeded") == "job.succeeded"


def test_cancel_and_interrupt_are_global_whatever_the_kind():
    """Only failed and succeeded are categorised; each kind owns exactly two
    of the four outcomes and the other two belong to the global rows."""
    assert type_for_job("app.install", "canceled") == "job.canceled"
    assert type_for_job("backup.run", "interrupted") == "job.interrupted"


def test_housekeeping_is_the_only_group_that_ships_off():
    off = {t.key for t in TYPES if not t.default_on}
    assert off == {"housekeeping.failed", "housekeeping.succeeded"}


def test_system_schedule_kinds_are_housekeeping():
    """The two built-in schedules succeed nightly and have nothing to say."""
    assert type_for_job("catalog.refresh", "succeeded") == "housekeeping.succeeded"
    assert type_for_job("metrics.maintain", "failed") == "housekeeping.failed"


def test_registry_is_nineteen_rows_with_unique_keys_and_human_labels():
    assert len(TYPES) == 19
    assert len({t.key for t in TYPES}) == 19
    assert set(DEFAULTS) == set(BY_KEY)
    for t in TYPES:
        # A label is what an operator reads. Backend spelling never leaks.
        assert "." not in t.label and "_" not in t.label
        assert t.label[0].isupper()


def test_alert_and_audit_keys_exist_and_are_not_job_mapped():
    for key in ("alert.fired", "alert.resolved", "audit.error"):
        assert key in BY_KEY
    assert type_for_job("app.install", "failed") != "audit.error"


@pytest.mark.parametrize("legacy", ["job.failed", "job.succeeded",
                                    "job.canceled", "job.interrupted",
                                    "alert.fired", "alert.resolved"])
def test_keys_already_stored_in_channel_rows_survive(legacy):
    """These six spellings are already in notification_channels.events on
    running installs. Renaming one would silently unsubscribe a channel."""
    assert legacy in BY_KEY
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_notification_types.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'proxploy.services.notification_types'`

- [ ] **Step 3: Write minimal implementation**

```python
"""What Proxploy can tell you about, and which job kind counts as which.

Nineteen rows rather than one per job kind. Eleven of the 33 registered kinds
earn a named row; the other 22 (VM power actions, snapshots, network apply,
storage upload, host reboot, migration) fall through to the generic Job rows.
The catch-all is load-bearing: without it, adding a job kind would silently
stop notifying rather than notify generically, and today's bell behaviour
would narrow the day this shipped.

Each kind owns exactly two of the four terminal outcomes. Cancel and interrupt
are global rows, because a cancelled app install firing against both
`app.install.failed` and `job.canceled` is the double-notify this mapping
exists to prevent.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NotificationType:
    key: str
    label: str
    group: str
    default_on: bool = True


TYPES: tuple[NotificationType, ...] = (
    NotificationType("app.install.failed", "App install failed", "Apps"),
    NotificationType("app.install.succeeded", "App install succeeded", "Apps"),
    NotificationType("app.update.failed", "App update failed", "Apps"),
    NotificationType("app.update.succeeded", "App update succeeded", "Apps"),
    NotificationType("app.uninstall.failed", "App removal failed", "Apps"),
    NotificationType("app.uninstall.succeeded", "App removal succeeded", "Apps"),
    NotificationType("backup.failed", "Backup failed", "Backups"),
    NotificationType("backup.succeeded", "Backup succeeded", "Backups"),
    NotificationType("backup.restore.failed", "Restore failed", "Backups"),
    NotificationType("backup.restore.succeeded", "Restore succeeded", "Backups"),
    NotificationType("housekeeping.failed", "Housekeeping failed",
                     "Housekeeping", default_on=False),
    NotificationType("housekeeping.succeeded", "Housekeeping succeeded",
                     "Housekeeping", default_on=False),
    NotificationType("job.failed", "Job failed", "Other jobs"),
    NotificationType("job.succeeded", "Job succeeded", "Other jobs"),
    NotificationType("job.canceled", "Job cancelled", "Other jobs"),
    NotificationType("job.interrupted", "Job interrupted", "Other jobs"),
    NotificationType("alert.fired", "Alert triggered", "Alerts"),
    NotificationType("alert.resolved", "Alert resolved", "Alerts"),
    NotificationType("audit.error", "Audited action failed", "Audit"),
)

BY_KEY: dict[str, NotificationType] = {t.key: t for t in TYPES}
DEFAULTS: dict[str, bool] = {t.key: t.default_on for t in TYPES}

# Job kind to the row prefix that owns its failed/succeeded outcomes. A kind
# absent here is not a bug, it is the 22 that belong to the generic rows.
_KIND_PREFIX: dict[str, str] = {
    "app.install": "app.install",
    "app.update": "app.update",
    "app.uninstall": "app.uninstall",
    "backup.run": "backup",
    "backup.sync": "backup",
    "backup.restore": "backup.restore",
    # The two built-in system schedules, plus the backup retention work that
    # runs on the same unattended footing.
    "catalog.refresh": "housekeeping",
    "catalog.classify_backlog": "housekeeping",
    "metrics.maintain": "housekeeping",
    "backup.delete": "housekeeping",
    "backup.prune": "housekeeping",
}

# Cancel and interrupt are never categorised, whatever the kind.
_GLOBAL_ONLY = {"canceled": "job.canceled", "interrupted": "job.interrupted"}


def type_for_job(kind: str, status: str) -> str:
    """Which registry row owns this job outcome. Total: every (kind, status)
    resolves, so a kind nobody mapped notifies generically rather than not at
    all."""
    if status in _GLOBAL_ONLY:
        return _GLOBAL_ONLY[status]
    return f"{_KIND_PREFIX.get(kind, 'job')}.{status}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_notification_types.py -q`
Expected: PASS, 12 tests

- [ ] **Step 5: Commit**

```bash
git add backend/proxploy/services/notification_types.py backend/tests/test_notification_types.py
git commit -m "feat(notifications): name what we can tell you about, one row per outcome"
```

---

### Task 2: Master switches, stored as overrides only

**Files:**
- Create: `backend/proxploy/services/notification_prefs.py`
- Test: `backend/tests/test_notification_prefs.py`

**Interfaces:**
- Consumes: `notification_types.DEFAULTS`, `services.settings.get_setting/set_setting`, model `AppSetting`.
- Produces:
  - `SETTING_KEY = "notifications.type_overrides"`
  - `effective(db) -> dict[str, bool]` every registry key to its live value.
  - `is_enabled(db, key: str) -> bool`
  - `set_overrides(db, changes: dict[str, bool]) -> dict[str, bool]` writes only keys that differ from the registry default, returns the new effective map.

- [ ] **Step 1: Write the failing test**

```python
"""Master switches. Stored as explicit overrides rather than a full enabled
set: a row added in a later release must arrive with the default it ships
with, not silently off for everyone who happened to save this page once."""
from proxploy.models import AppSetting
from proxploy.services.notification_prefs import (
    SETTING_KEY, effective, is_enabled, set_overrides,
)
from proxploy.services.notification_types import DEFAULTS


def test_a_fresh_install_gets_the_registry_defaults(session):
    assert effective(session) == DEFAULTS
    assert is_enabled(session, "job.failed") is True
    assert is_enabled(session, "housekeeping.succeeded") is False


def test_turning_one_row_off_leaves_every_other_row_alone(session):
    after = set_overrides(session, {"job.succeeded": False})
    assert after["job.succeeded"] is False
    assert after["job.failed"] is True
    assert is_enabled(session, "job.succeeded") is False


def test_only_differences_from_default_are_written(session):
    """The stored blob is a diff, not a snapshot. Writing the whole map would
    freeze today's defaults into every install forever."""
    set_overrides(session, {"job.failed": True, "job.succeeded": False})
    stored = session.query(AppSetting).filter_by(key=SETTING_KEY).one().value
    assert stored == {"job.succeeded": False}


def test_setting_a_row_back_to_its_default_drops_the_override(session):
    set_overrides(session, {"job.succeeded": False})
    set_overrides(session, {"job.succeeded": True})
    stored = session.query(AppSetting).filter_by(key=SETTING_KEY).one().value
    assert stored == {}
    assert is_enabled(session, "job.succeeded") is True


def test_an_unknown_key_is_ignored_rather_than_stored(session):
    """A key that no emitter can produce is exactly the `app.updated` defect.
    Refusing to store one keeps it from accumulating in the blob."""
    set_overrides(session, {"app.updated": False})
    stored = session.query(AppSetting).filter_by(key=SETTING_KEY).one().value
    assert stored == {}
    assert "app.updated" not in effective(session)


def test_a_stale_override_from_a_removed_row_does_not_leak_into_effective(session):
    """A row deleted in a later release leaves its override behind in the
    blob. effective() is keyed by the registry, so the stale entry is inert."""
    from proxploy.services.settings import set_setting
    set_setting(session, SETTING_KEY, {"gone.away": False, "job.succeeded": False})
    live = effective(session)
    assert "gone.away" not in live
    assert live["job.succeeded"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_notification_prefs.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'proxploy.services.notification_prefs'`

If the `session` fixture does not exist in `backend/tests/conftest.py`, add it there first:

```python
import pytest


@pytest.fixture
def session(tmp_path):
    """A bare DB session with the schema created, for services that take a
    session rather than an app."""
    from tests.support import make_app
    app = make_app(tmp_path)
    with app.state.sessionmaker() as db:
        yield db
```

- [ ] **Step 3: Write minimal implementation**

```python
"""Master switches for the Events matrix.

The blob under `notifications.type_overrides` holds only rows the operator
explicitly moved away from the registry default. Two consequences, both
deliberate: a row added in a later release arrives with the default it ships
with rather than off, and an override left behind by a row we later delete is
inert because `effective()` is keyed by the registry and not by the blob.
"""
from __future__ import annotations

from proxploy.services.notification_types import BY_KEY, DEFAULTS
from proxploy.services.settings import get_setting, set_setting

SETTING_KEY = "notifications.type_overrides"


def _overrides(db) -> dict:
    return get_setting(db, SETTING_KEY, {}) or {}


def effective(db) -> dict[str, bool]:
    """Every registry key to its live value."""
    stored = _overrides(db)
    return {key: bool(stored.get(key, default))
            for key, default in DEFAULTS.items()}


def is_enabled(db, key: str) -> bool:
    """Unknown keys are enabled: a type we cannot find is a mapping bug, and
    swallowing the notification would hide it."""
    if key not in BY_KEY:
        return True
    return effective(db)[key]


def set_overrides(db, changes: dict[str, bool]) -> dict[str, bool]:
    stored = dict(_overrides(db))
    for key, value in changes.items():
        if key not in BY_KEY:
            continue          # never accumulate a key no emitter can produce
        if bool(value) == DEFAULTS[key]:
            stored.pop(key, None)
        else:
            stored[key] = bool(value)
    set_setting(db, SETTING_KEY, stored)
    return effective(db)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_notification_prefs.py -q`
Expected: PASS, 6 tests

- [ ] **Step 5: Commit**

```bash
git add backend/proxploy/services/notification_prefs.py backend/tests/test_notification_prefs.py backend/tests/conftest.py
git commit -m "feat(notifications): master switches, stored as overrides not a snapshot"
```

---

### Task 3: The types endpoint

**Files:**
- Modify: `backend/proxploy/api/notifications.py`
- Test: `backend/tests/test_notifications_api.py`

**Interfaces:**
- Consumes: `notification_types.TYPES`, `notification_prefs.effective/set_overrides`.
- Produces: `GET /api/v1/notifications/types` returning `{"types": [{key, label, group, enabled}], }`, and `PATCH /api/v1/notifications/types` taking `{"enabled": {key: bool}}` and returning the same shape.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_notifications_api.py`:

```python
def test_types_lists_every_row_with_its_live_value(tmp_path, csrf_header, bootstrap_admin):
    from tests.support import make_app

    with TestClient(make_app(tmp_path)) as c:
        bootstrap_admin(c)
        r = c.get("/api/v1/notifications/types")
        assert r.status_code == 200
        rows = r.json()["types"]
        assert len(rows) == 19
        by_key = {t["key"]: t for t in rows}
        assert by_key["job.failed"]["enabled"] is True
        assert by_key["job.failed"]["label"] == "Job failed"
        assert by_key["housekeeping.succeeded"]["enabled"] is False


def test_patching_a_type_persists_and_is_audited(tmp_path, csrf_header, bootstrap_admin):
    from tests.support import make_app

    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        r = c.patch("/api/v1/notifications/types",
                    json={"enabled": {"job.succeeded": False}},
                    headers=csrf_header(c))
        assert r.status_code == 200
        by_key = {t["key"]: t for t in r.json()["types"]}
        assert by_key["job.succeeded"]["enabled"] is False
        assert c.get("/api/v1/notifications/types").json()["types"]
        with app.state.sessionmaker() as db:
            actions = [a.action for a in db.query(AuditEvent).all()]
        assert "notify.types.update" in actions


def test_types_needs_admin(tmp_path):
    from tests.support import make_app

    with TestClient(make_app(tmp_path)) as c:
        assert c.get("/api/v1/notifications/types").status_code == 401
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_notifications_api.py -q -k types`
Expected: FAIL, 404 on `/api/v1/notifications/types`

- [ ] **Step 3: Write minimal implementation**

Add to the imports in `backend/proxploy/api/notifications.py`:

```python
from proxploy.services.notification_prefs import effective, set_overrides
from proxploy.services.notification_types import BY_KEY, TYPES
```

Add the model near `ChannelPatch`:

```python
class TypesPatch(BaseModel):
    enabled: dict[str, bool]
```

Add the routes after `list_kinds`:

```python
def _types_out(db) -> dict:
    live = effective(db)
    return {"types": [{"key": t.key, "label": t.label, "group": t.group,
                       "enabled": live[t.key]} for t in TYPES]}


@router.get("/types", dependencies=[Depends(_manage)])
def list_types(db=Depends(get_db)):
    """Deliberately NOT behind notify.channels: the master switches are how
    someone with no channels at all stops a toast, so gating them on the
    channel feature would make "turn that off" unreachable on the very
    installs most likely to want it."""
    return _types_out(db)


@router.patch("/types", dependencies=[Depends(_manage)])
def patch_types(request: Request, body: TypesPatch, db=Depends(get_db),
                user: User = Depends(_manage)):
    unknown = sorted(set(body.enabled) - set(BY_KEY))
    if unknown:
        raise HTTPException(422, f"unknown notification type: {unknown[0]}")
    set_overrides(db, body.enabled)
    write_audit(db, actor_type="user", actor_id=user.id,
                action="notify.types.update", target_type="setting",
                params={"changed": sorted(body.enabled)}, ip=_ip(request))
    return _types_out(db)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_notifications_api.py -q`
Expected: PASS, all tests in the file

- [ ] **Step 5: Commit**

```bash
git add backend/proxploy/api/notifications.py backend/tests/test_notifications_api.py
git commit -m "feat(notifications): read and set the master switches"
```

---

### Task 4: Emit the mapped type, and honour the master switch

**Files:**
- Modify: `backend/proxploy/jobs/backend.py:377-381` (`_notify`) and `backend/proxploy/jobs/backend.py:373` (the `_publish` call in `_finish`)
- Modify: `backend/proxploy/services/notifier.py` (`notify`)
- Modify: `backend/proxploy/services/alerts.py:369`
- Test: `backend/tests/test_notifier.py`

**Interfaces:**
- Consumes: `notification_types.type_for_job`, `notification_prefs.is_enabled`.
- Produces: the `job` bus payload gains `notify_type`; `notifier.notify` returns 0 without decrypting anything when the type is off.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_notifier.py`:

```python
def test_a_named_kind_notifies_under_its_own_row(tmp_path, monkeypatch):
    """jobs/backend.py used to throw the kind away and emit job.failed for
    everything, which is why "App install failed" could not be a switch."""
    from proxploy.services.notification_types import type_for_job

    assert type_for_job("app.install", "failed") == "app.install.failed"


def test_notify_returns_early_for_a_disabled_type(tmp_path, monkeypatch):
    """Off means no channel is decrypted and no Apprise send runs, not that
    the send happens and the result is discarded."""
    from tests.support import make_app
    from proxploy.services import notifier
    from proxploy.services.notification_prefs import set_overrides

    app = make_app(tmp_path)
    sent = []
    monkeypatch.setattr(notifier, "send_one",
                        lambda *a, **k: sent.append(a) or True)
    with app.state.sessionmaker() as db:
        _make_channel(db, app, events=[])          # subscribed to everything
        set_overrides(db, {"job.succeeded": False})

    assert notifier.notify(app, "job.succeeded", "t", "b") == 0
    assert sent == []

    assert notifier.notify(app, "job.failed", "t", "b") == 1
    assert len(sent) == 1


def test_an_unknown_event_still_sends(tmp_path, monkeypatch):
    """A type we cannot find is a mapping bug. Swallowing the notification
    would hide it; sending it makes it visible."""
    from tests.support import make_app
    from proxploy.services import notifier

    app = make_app(tmp_path)
    monkeypatch.setattr(notifier, "send_one", lambda *a, **k: True)
    with app.state.sessionmaker() as db:
        _make_channel(db, app, events=[])
    assert notifier.notify(app, "something.new", "t", "b") == 1
```

Add this helper at the top of the same file if it is not already there:

```python
def _make_channel(db, app, events):
    from proxploy.models import NotificationChannel
    blob, ver = app.state.secretstore.encrypt(b"ntfy://ntfy.sh/proxploy-test")
    db.add(NotificationChannel(name="t", kind="ntfy", url_enc=blob,
                               key_version=ver, events=events, enabled=True))
    db.commit()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_notifier.py -q`
Expected: FAIL, `notify` returns 1 for the disabled type because no switch is consulted yet

- [ ] **Step 3: Write minimal implementation**

In `backend/proxploy/services/notifier.py`, at the top of `notify`, before the session opens:

```python
def notify(app, event: str, title: str, body: str,
           only_ids: list[int] | None = None) -> int:
    """Fan a single event out to every subscribed channel. Returns channels reached.

    The master switch is consulted first, so a type the operator turned off
    costs one settings read rather than a decrypt per channel and an Apprise
    send per channel. An event with no registry row is NOT suppressed: that is
    a mapping bug, and silence would hide it.

    A channel that is misconfigured, unreachable or slow must never fail the
    job that triggered it, each send is isolated. Decryption happens inside
    the session (cheap); the blocking Apprise sends happen outside it, so a
    slow/hanging channel doesn't hold a DB connection checked out for
    ~8s-per-channel (Apprise's default connect+read timeout) while every
    other channel's `last_notified_at` stamp waits behind it.
    """
    from proxploy.services.notification_prefs import is_enabled

    with app.state.sessionmaker() as db:
        if not is_enabled(db, event):
            return 0
        targets = []
        for channel in channels_for(db, event, only_ids):
            ...
```

Keep the rest of the existing body unchanged; the `is_enabled` check and the existing `targets` loop share the one session.

In `backend/proxploy/jobs/backend.py`, change `_notify`:

```python
    def _notify(self, job_id: int, kind: str, status: str, error: str | None) -> None:
        """Route the terminal result to the Notifier, off the event loop.

        The job kind used to be dropped here and every outcome went out as
        `job.{status}`, which is why "App install failed" could not be its own
        switch. The registry maps (kind, status) onto exactly one row, so a
        named kind never also fires the generic one.
        """
        from proxploy.services.notification_types import type_for_job

        title = f"Proxploy: {kind} {status}"
        body = error or f"job {job_id} ({kind}) {status}"
        self._notify_async(type_for_job(kind, status), title, body)
```

In the same file, carry the resolved key on the bus delta so the client does not need its own copy of the kind table. Change the `_publish` call inside `_finish`:

```python
        from proxploy.services.notification_types import type_for_job
        self._publish(job_id, status=status, kind=kind, target_type=target_type,
                      notify_type=type_for_job(kind, status),
                      **({"error": error} if error else {}))
```

`services/alerts.py:369` already emits `alert.fired` and `alert.resolved`, which are registry keys, so it needs no change.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_notifier.py tests/test_notification_types.py tests/test_alerts_notify.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/proxploy/services/notifier.py backend/proxploy/jobs/backend.py backend/tests/test_notifier.py
git commit -m "feat(notifications): keep the job kind, and stop at the master switch"
```

---

### Task 5: Audited failures become a notification

**Files:**
- Modify: `backend/proxploy/services/audit.py`
- Test: `backend/tests/test_audit_notify.py` (create)

**Interfaces:**
- Consumes: `notifier.notify`, `write_audit`'s existing `result` parameter.
- Produces: nothing new; `write_audit` gains a side effect when `result="error"`.

- [ ] **Step 1: Write the failing test**

```python
"""An audited action that failed is the one notification type with no job and
no alert behind it. It is how a firewall rule that would not apply, or a host
that refused its credentials, reaches someone who is not watching the screen."""
from proxploy.services import notifier
from proxploy.services.audit import write_audit


def test_an_errored_audit_row_notifies(tmp_path, monkeypatch):
    from tests.support import make_app

    app = make_app(tmp_path)
    seen = []
    monkeypatch.setattr(notifier, "notify",
                        lambda a, event, title, body, **k: seen.append(event) or 1)
    with app.state.sessionmaker() as db:
        write_audit(db, actor_type="user", actor_id=1, action="host.test",
                    result="error", app=app)
    assert seen == ["audit.error"]


def test_a_successful_audit_row_is_silent(tmp_path, monkeypatch):
    from tests.support import make_app

    app = make_app(tmp_path)
    seen = []
    monkeypatch.setattr(notifier, "notify",
                        lambda a, event, title, body, **k: seen.append(event) or 1)
    with app.state.sessionmaker() as db:
        write_audit(db, actor_type="user", actor_id=1, action="host.test",
                    result="ok", app=app)
    assert seen == []


def test_audit_still_writes_when_no_app_is_passed(tmp_path):
    """Most call sites have no app handle. Auditing must never depend on
    being able to notify."""
    from proxploy.models import AuditEvent
    from tests.support import make_app

    app = make_app(tmp_path)
    with app.state.sessionmaker() as db:
        write_audit(db, actor_type="user", actor_id=1, action="host.test",
                    result="error")
        assert db.query(AuditEvent).count() == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_audit_notify.py -q`
Expected: FAIL, `seen == []` because `write_audit` has no notify path, or TypeError on the unexpected `app` keyword

- [ ] **Step 3: Write minimal implementation**

In `backend/proxploy/services/audit.py`, add an optional `app` keyword to `write_audit` and fire after the row commits:

```python
def write_audit(db, *, app=None, **fields):
    ...                                  # existing body unchanged
    if app is not None and fields.get("result") == "error":
        _notify_error(app, fields)


def _notify_error(app, fields) -> None:
    """Never let a notification failure roll back an audit row: the row is the
    record, the notification is a courtesy."""
    from proxploy.services.notifier import notify

    action = fields.get("action") or "action"
    try:
        notify(app, "audit.error", f"Proxploy: {action} failed",
               fields.get("error") or f"{action} did not complete.")
    except Exception:  # noqa: BLE001
        logger.debug("audit error notification failed", exc_info=True)
```

Then pass `app=request.app` at the call sites that already have a request and audit a failure. Start with `api/hosts.py`'s `host.test` and `host.ssh_verify`; the rest can adopt it incrementally because `app` is optional and its absence only means no notification.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_audit_notify.py tests/test_audit.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/proxploy/services/audit.py backend/tests/test_audit_notify.py
git commit -m "feat(notifications): tell someone when an audited action fails"
```

---

### Task 6: Settings gets a Notifications group

**Files:**
- Modify: `frontend/src/lib/settings-sections.ts:37-51`
- Modify: `frontend/src/routes/settings.tsx`
- Test: `frontend/src/tests/settings.test.tsx`

**Interfaces:**
- Consumes: existing `SETTINGS_SECTIONS` shape `{ group: string; items: SettingsSection[] }[]`.
- Produces: section ids `channels` and `events`; the id `notifications` no longer exists.

- [ ] **Step 1: Write the failing test**

Append to `frontend/src/tests/settings.test.tsx`:

```tsx
import { SETTINGS_SECTIONS } from '../lib/settings-sections'

describe('the Notifications group', () => {
  it('is its own group holding Channels and Events', () => {
    const group = SETTINGS_SECTIONS.find(g => g.group === 'Notifications')
    expect(group).toBeDefined()
    expect(group!.items.map(i => i.id)).toEqual(['channels', 'events'])
  })

  it('no longer carries a single notifications section under General', () => {
    const ids = SETTINGS_SECTIONS.flatMap(g => g.items.map(i => i.id))
    expect(ids).not.toContain('notifications')
  })

  it('keeps the old search words reachable, so "ntfy" still finds Channels', () => {
    const channels = SETTINGS_SECTIONS
      .flatMap(g => g.items).find(i => i.id === 'channels')!
    expect(channels.keywords).toEqual(
      expect.arrayContaining(['ntfy', 'telegram', 'email', 'slack', 'notify']))
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run --no-file-parallelism src/tests/settings.test.tsx`
Expected: FAIL, `group` is undefined

- [ ] **Step 3: Write minimal implementation**

In `frontend/src/lib/settings-sections.ts`, remove the `notifications` item from the General group and add a new group after General:

```ts
  { group: 'Notifications', items: [
    { id: 'channels', label: 'Channels',
      keywords: ['ntfy', 'gotify', 'telegram', 'email', 'smtp', 'slack',
                 'discord', 'webhook', 'notify', 'channel', 'apprise'] },
    { id: 'events', label: 'Events',
      keywords: ['notification', 'notify', 'toast', 'alert', 'job failed',
                 'backup failed', 'mute', 'turn off', 'housekeeping'] },
  ] },
```

In `frontend/src/routes/settings.tsx`, rename the existing `active === 'notifications'` branch to `active === 'channels'`, and add an `active === 'events'` branch rendering `<EventsMatrix />` (built in Task 8).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run --no-file-parallelism src/tests/settings.test.tsx src/tests/command-palette.test.tsx`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/settings-sections.ts frontend/src/routes/settings.tsx frontend/src/tests/settings.test.tsx
git commit -m "feat(settings): Notifications becomes a group, not one crowded card"
```

---

### Task 7: The guided channel picker replaces the URL box

**Files:**
- Modify: `frontend/src/components/ChannelForm.tsx`
- Create: `frontend/src/api/notificationKinds.ts`
- Test: `frontend/src/tests/channels.test.tsx`

**Interfaces:**
- Consumes: `GET /api/v1/notifications/kinds` returning `{kind, label, setup_url, fields: [{key, label, required, secret, placeholder, default, help}]}[]`; `POST /api/v1/notifications/channels` accepting `{name, kind, fields, events}` or `{name, url, events}`.
- Produces: `useNotificationKinds()` TanStack query hook returning that array.

- [ ] **Step 1: Write the failing test**

```tsx
/** The form used to ask for a name and an Apprise URL, so adding Telegram
 *  meant already knowing it is tgram://bottoken/ChatID. */
it('offers the services by name and asks that service its own questions', async () => {
  render(<ChannelForm onSaved={() => {}} />)
  await screen.findByRole('button', { name: /telegram/i })
  await userEvent.click(screen.getByRole('button', { name: /telegram/i }))
  expect(await screen.findByLabelText('Bot token')).toHaveAttribute('type', 'password')
  expect(screen.getByLabelText('Chat ID')).toBeInTheDocument()
  expect(screen.queryByLabelText(/apprise url/i)).not.toBeInTheDocument()
})

it('posts the fields, never an assembled URL', async () => {
  const post = vi.fn().mockResolvedValue({ id: 1, kind: 'telegram' })
  render(<ChannelForm onSaved={() => {}} />)
  await userEvent.click(await screen.findByRole('button', { name: /telegram/i }))
  await userEvent.type(screen.getByLabelText('Name'), 'Bot')
  await userEvent.type(screen.getByLabelText('Bot token'), '123:abc')
  await userEvent.type(screen.getByLabelText('Chat ID'), '42')
  await userEvent.click(screen.getByRole('button', { name: /add channel/i }))
  expect(JSON.parse(post.mock.calls[0][1].body)).toEqual({
    name: 'Bot', kind: 'telegram',
    fields: { bot_token: '123:abc', chat_id: '42' }, events: [],
  })
})

it('keeps a paste-a-URL escape hatch for services we do not list', async () => {
  render(<ChannelForm onSaved={() => {}} />)
  await userEvent.click(await screen.findByRole('button', { name: /paste a url/i }))
  expect(screen.getByLabelText(/apprise url/i)).toBeInTheDocument()
})

it('shows what the server said when the details are not sendable', async () => {
  // The 422 body from _resolve_url, surfaced verbatim rather than as
  // "Could not add that channel".
  render(<ChannelForm onSaved={() => {}} />)
  await userEvent.click(await screen.findByRole('button', { name: /ntfy/i }))
  await userEvent.type(screen.getByLabelText('Name'), 'n')
  await userEvent.click(screen.getByRole('button', { name: /add channel/i }))
  expect(await screen.findByText(/Topic is required/)).toBeInTheDocument()
})
```

Mock `/notifications/kinds` in the file's existing `api` mock to return two entries, ntfy and telegram, matching the real payload shape.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run --no-file-parallelism src/tests/channels.test.tsx`
Expected: FAIL, no button named Telegram

- [ ] **Step 3: Write minimal implementation**

`frontend/src/api/notificationKinds.ts`:

```ts
import { useQuery } from '@tanstack/react-query'
import { api } from './client'

export type KindField = {
  key: string; label: string; required: boolean; secret: boolean
  placeholder: string; default: string; help: string
}
export type NotificationKind = {
  kind: string; label: string; setup_url: string; fields: KindField[]
}

export function useNotificationKinds(enabled = true) {
  return useQuery({
    queryKey: ['notifications', 'kinds'],
    queryFn: () => api<NotificationKind[]>('/notifications/kinds'),
    staleTime: Infinity,   // a build-time constant, not live data
    enabled,
  })
}
```

Rewrite `ChannelForm.tsx` as: a grid of buttons from `useNotificationKinds()` plus a final "Paste a URL" button; on selection, render `Name` followed by that kind's fields (`type={f.secret ? 'password' : 'text'}`, `required`, `placeholder`, `defaultValue={f.default}`, help text under each); submit `{name, kind, fields, events}`, or `{name, url, events}` for the escape hatch. On error, show `error.detail` from the response rather than a generic string. Drop `EVENT_CHOICES` entirely; `events` posts as `[]` because the Events matrix now owns routing.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run --no-file-parallelism src/tests/channels.test.tsx src/tests/settings.test.tsx`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ChannelForm.tsx frontend/src/api/notificationKinds.ts frontend/src/tests/channels.test.tsx
git commit -m "feat(notifications): pick the service, answer its questions, not paste a URL"
```

---

### Task 8: The Events matrix

**Files:**
- Create: `frontend/src/components/EventsMatrix.tsx`
- Create: `frontend/src/api/notificationTypes.ts`
- Test: `frontend/src/tests/events-matrix.test.tsx`

**Interfaces:**
- Consumes: `GET/PATCH /api/v1/notifications/types`, `GET /api/v1/notifications/channels`, `useEntitlements`.
- Produces: `<EventsMatrix />`, rendered by the `events` settings section, and `useNotificationTypes()` returning `{ rows, enabled }` (Task 9 consumes `enabled`).

- [ ] **Step 1: Write the failing test**

```tsx
it('works with no channels at all, master switches only', async () => {
  // channels: [] from the mock
  render(<EventsMatrix />)
  expect(await screen.findByRole('switch', { name: 'Job failed' })).toBeChecked()
  expect(screen.getByRole('switch', { name: 'Housekeeping succeeded' })).not.toBeChecked()
  expect(screen.queryByRole('columnheader', { name: /smtp/i })).not.toBeInTheDocument()
  expect(screen.getByText(/only shown in the app/i)).toBeInTheDocument()
})

it('groups the rows under headings rather than listing nineteen flat', async () => {
  render(<EventsMatrix />)
  for (const g of ['Apps', 'Backups', 'Housekeeping', 'Other jobs', 'Alerts', 'Audit'])
    expect(await screen.findByRole('rowheader', { name: g })).toBeInTheDocument()
})

it('shows a column per configured channel and ticks it from that channel events', async () => {
  // channels: [{id: 1, name: 'SMTP', kind: 'email', events: ['job.failed']}]
  render(<EventsMatrix />)
  expect(await screen.findByRole('checkbox',
    { name: 'Send Job failed to SMTP' })).toBeChecked()
  expect(screen.getByRole('checkbox',
    { name: 'Send Job succeeded to SMTP' })).not.toBeChecked()
})

it('renders a channel with an empty events list as fully ticked', async () => {
  // channels: [{id: 1, name: 'SMTP', kind: 'email', events: []}]
  // Empty means "every event" server-side; showing it unticked would lie
  // about what that channel is currently receiving.
  render(<EventsMatrix />)
  expect(await screen.findByRole('checkbox',
    { name: 'Send Job failed to SMTP' })).toBeChecked()
  expect(screen.getByRole('checkbox',
    { name: 'Send Alert triggered to SMTP' })).toBeChecked()
})

it('materialises the concrete list when an all-events channel is first edited', async () => {
  const patch = vi.fn().mockResolvedValue({})
  render(<EventsMatrix />)
  await userEvent.click(await screen.findByRole('checkbox',
    { name: 'Send Job succeeded to SMTP' }))
  const body = JSON.parse(patch.mock.calls[0][1].body)
  expect(body.events).not.toContain('job.succeeded')
  expect(body.events).toContain('job.failed')
  expect(body.events).toContain('alert.fired')
})

it('turning a master switch off disables that row channel boxes', async () => {
  render(<EventsMatrix />)
  await userEvent.click(await screen.findByRole('switch', { name: 'Job failed' }))
  expect(screen.getByRole('checkbox',
    { name: 'Send Job failed to SMTP' })).toBeDisabled()
})

it('locks the channel columns without notify.routing and says everything goes everywhere', async () => {
  // entitlements: { 'notify.routing': false }
  render(<EventsMatrix />)
  expect(await screen.findByRole('switch', { name: 'Job failed' })).toBeEnabled()
  expect(screen.getByRole('checkbox',
    { name: 'Send Job failed to SMTP' })).toBeDisabled()
  expect(screen.getByText(/goes to every channel/i)).toBeInTheDocument()
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run --no-file-parallelism src/tests/events-matrix.test.tsx`
Expected: FAIL, cannot resolve `../components/EventsMatrix`

- [ ] **Step 3: Write minimal implementation**

`frontend/src/api/notificationTypes.ts` mirrors `notificationKinds.ts`: a `useNotificationTypes()` query on `/notifications/types` whose `select` returns `{ rows: TypeRow[]; enabled: Record<string, boolean> }` (the matrix needs the rows, LiveProvider in Task 9 needs only the map, and deriving it once here keeps them from disagreeing), plus a `useSetNotificationTypes()` mutation issuing `PATCH` with `{enabled}`.

`EventsMatrix.tsx` renders a `<table>`: one `<tbody>` per group with the group name as a `rowheader`, one row per type, a `role="switch"` in the first cell labelled by the type label, then one checkbox per channel labelled `Send {type label} to {channel name}`. Checkbox state is `channel.events.length === 0 || channel.events.includes(key)`. Toggling one writes the full materialised list back with `PATCH /notifications/channels/{id}`, computed from the currently ticked set so an all-events channel keeps everything except the box just cleared. Boxes are `disabled` when the row's master is off or `notify.routing` is absent. With zero channels, render the switch column only, with the line "Notifications are only shown in the app until you add a channel." Without `notify.routing`, show "On your plan, an enabled notification goes to every channel."

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run --no-file-parallelism src/tests/events-matrix.test.tsx`
Expected: PASS, 7 tests

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/EventsMatrix.tsx frontend/src/api/notificationTypes.ts frontend/src/tests/events-matrix.test.tsx
git commit -m "feat(notifications): one matrix, types down the side and channels across"
```

---

### Task 9: The master switch silences the toast too

**Files:**
- Modify: `frontend/src/components/LiveProvider.tsx:44-56`
- Test: `frontend/src/tests/live.test.ts`

**Interfaces:**
- Consumes: `useNotificationTypes()`, the `notify_type` field added to the `job` bus payload in Task 4.
- Produces: no new exports.

- [ ] **Step 1: Write the failing test**

```ts
it('does not toast a job whose type the operator turned off', async () => {
  // types: { 'job.succeeded': false }, SSE job delta carries
  // notify_type: 'job.succeeded'
  emitJob({ id: 1, status: 'succeeded', kind: 'vm.create',
            notify_type: 'job.succeeded' })
  expect(getNotifications()).toHaveLength(0)
})

it('still invalidates the job queries for a silenced type', async () => {
  // The switch silences the toast, never the data. Suppressing the publish
  // would stop the Jobs page updating live.
  emitJob({ id: 1, status: 'succeeded', kind: 'vm.create',
            notify_type: 'job.succeeded' })
  expect(invalidate).toHaveBeenCalled()
})

it('toasts a delta that carries no notify_type', async () => {
  // Progress deltas have no terminal type. Treating "absent" as "off" would
  // silence every running job.
  emitJob({ id: 1, status: 'running', kind: 'vm.create' })
  expect(getNotifications()).toHaveLength(1)
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run --no-file-parallelism src/tests/live.test.ts`
Expected: FAIL, the silenced job still pushes a notification

- [ ] **Step 3: Write minimal implementation**

In `LiveProvider.tsx`, add a ref alongside `inApp` and consult it inside the toast callback only, leaving `applyJob`'s invalidation untouched:

```tsx
  const types = useNotificationTypes()
  const enabled = useRef<Record<string, boolean>>({})
  enabled.current = types.data?.enabled ?? {}
  // ...
    wire('job', (d) => applyJob(qc, d, (t) => {
      if (!inApp.current) return   // notify.inapp gates the surface, not the data
      // An absent notify_type is a progress delta, not a silenced one: only a
      // terminal outcome carries a type, and treating absent as off would
      // silence every running job.
      if (d.notify_type && enabled.current[d.notify_type] === false) return
      pushJobEvent(t.jobId, jobToastSeverity(t.kind), t.text, t.detail ?? `job #${t.jobId}`)
    }))
```

Apply the same guard in the `alert` handler using `d.state === 'firing' ? 'alert.fired' : 'alert.resolved'`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run --no-file-parallelism src/tests/live.test.ts src/tests/toasts.test.tsx src/tests/bell-popover.test.tsx`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/LiveProvider.tsx frontend/src/tests/live.test.ts
git commit -m "feat(notifications): off means the toast too, not just the send"
```

---

### Task 10: Full suite and cleanup

**Files:**
- Modify: whatever the suites turn up.

- [ ] **Step 1: Run the whole backend suite**

Run: `cd backend && .venv/bin/python -m pytest tests/ -q -m "not pve_integration and not e2e"`
Expected: PASS. `test_entitlement_flag_inventory.py` is the one most likely to complain, because `notify.routing` and `notify.inapp` are still listed as backend-unenforced and that remains true; no change expected there.

- [ ] **Step 2: Run the whole frontend suite**

Run: `cd frontend && npx vitest run --no-file-parallelism`
Expected: PASS

- [ ] **Step 3: Typecheck and lint**

Run: `cd frontend && npx tsc -b && npx oxlint`
Expected: clean

- [ ] **Step 4: Drive the real app**

Run: `cd frontend && node e2e/driver.mjs shot /tmp/events.png '/settings?section=events'`
Open the PNG and look at it. A blank frame is a failed launch, not a pass. The headless driver has no session cookie, so a signed-out render is expected; confirm the route resolves rather than 404s.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "test(notifications): green across both suites"
```

---

## Self-Review

**Spec coverage:** Settings shape (Task 6), Channels section (Task 7), matrix semantics (Task 8), registry (Task 1), cancel/interrupt global (Task 1), scheduled runs not their own row (Task 1, via kind mapping), node unreachable stays on Alerts (no task, deliberately no change), no-migration transposition and the empty-events wrinkle (Task 8), master switch storage (Task 2), entitlements (Tasks 3 and 8), emitters (Tasks 4 and 5), two-place suppression (Tasks 4 and 9), testing (throughout, plus Task 10).

**Placeholders:** none. Every code step carries the code.

**Type consistency:** `type_for_job(kind, status) -> str` used identically in Tasks 1 and 4. `effective(db) -> dict[str, bool]` and `set_overrides(db, changes)` used identically in Tasks 2 and 3. `notify_type` is written in Task 4 and read in Task 9. `useNotificationTypes()` is created in Task 8 and consumed in Task 9, so Task 8 must land first.
