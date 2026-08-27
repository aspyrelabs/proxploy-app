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


@pytest.mark.parametrize("kind", ["sessions.cleanup", "jobs.prune",
                                  "db.compact", "update.check"])
def test_new_maintenance_kinds_are_housekeeping_not_generic(kind):
    """An unmapped kind would fall through to job.succeeded/job.failed and
    notify on every nightly run, whatever its default_on setting."""
    assert type_for_job(kind, "succeeded") == "housekeeping.succeeded"
    assert type_for_job(kind, "failed") == "housekeeping.failed"


def test_registry_is_twenty_rows_with_unique_keys_and_human_labels():
    assert len(TYPES) == 20
    assert len({t.key for t in TYPES}) == 20
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
