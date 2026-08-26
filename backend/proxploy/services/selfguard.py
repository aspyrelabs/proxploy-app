"""Self-management guardrail.

A tool that can stop its own CT can brick its own recovery path. Identity is
recorded at install time as the `self.ctid` / `self.host_id` settings keys.

Deliberate fail-open asymmetry: when nothing is recorded this returns False and
NOTHING is blocked — a false *refusal* is the worse failure. The
typed-confirmation prompt callers put in front of a True answer is the
backstop, not the only guard.
"""
from proxploy.models import App, Host
from proxploy.services.settings import get_setting

DESTRUCTIVE = frozenset({"stop", "shutdown", "restart", "pause"})


def is_self_host_node(db, host: Host, node: str) -> bool:
    """Whether `node` is the specific PVE node Proxploy itself physically runs
    on, within the given Host record (host actions menu: reboot/power off).

    A Host row can represent a whole PVE cluster; only the ENTRY node
    (`host.node_name`, named at enrolment by `_cluster_identity()`) can ever be
    the machine Proxploy runs on. Comparing against `host.node_name` narrows to
    that one node, so rebooting a sibling node of the same cluster is never
    flagged. Fails open (unset or malformed self.host_id) like is_self().
    """
    self_host_id = get_setting(db, "self.host_id")
    if self_host_id is None:
        return False
    try:
        if int(self_host_id) != host.id:
            return False
    except (TypeError, ValueError):
        return False
    return bool(host.node_name) and host.node_name == node


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
