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
