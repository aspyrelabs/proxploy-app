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
