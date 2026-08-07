"""Self-management guardrail (doc 02 §9, doc 08 §1, doc 08 §9 row 14).

A tool that can stop its own CT can brick its own recovery path. Identity is
recorded at install time as the `self.ctid` / `self.host_id` settings keys (the
Phase 9 installer writes them from inside the CT it creates).

Deliberate asymmetry: when nothing is recorded this returns False and NOTHING
is blocked. Detection can miss, Proxploy relocated without re-detection, an
ambiguous hostname, a bare-metal install that is not a CT at all; so a false
*refusal* is the worse failure. The typed-confirmation prompt callers put in
front of a True answer is the backstop, not the only guard.
"""
from proxploy.models import App
from proxploy.services.settings import get_setting

DESTRUCTIVE = frozenset({"stop", "shutdown", "restart", "pause"})


def is_self(db, target_type: str, target_id: int) -> bool:
    if target_type != "app":
        return False  # Proxploy ships as an LXC CT; a VM is never itself
    ctid = get_setting(db, "self.ctid")
    if ctid is None:
        return False
    app = db.get(App, target_id)
    if app is None:
        return False
    try:
        if app.ctid != int(ctid):
            return False
        host_id = get_setting(db, "self.host_id")
        return host_id is None or app.host_id == int(host_id)
    except (TypeError, ValueError):
        # A malformed setting (e.g. "" or "ct-150") must fail open, same as an
        # unset one: see the module docstring's asymmetry.
        return False
