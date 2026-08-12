"""Authorizer seam (doc 08 §6, doc 03 AuthZ row): pycasbin RBAC with domains.

The ONLY module that imports casbin. The enforcer is in-memory: static
p-lines generated from PERMISSIONS below, g-lines derived from team_members.
The casbin_rules table stays empty, doc 04's "mirrored into casbin_rules"
design would be two sources of truth for the same memberships; team_members
is authoritative and the enforcer is a pure function of it (rebuilt at boot,
patched by sync_user() on every membership write). Amendment recorded in
docs/notes/phase-8-scale.md, mirroring Phase 7's APScheduler precedent.
"""
from __future__ import annotations

import casbin

from proxploy.models import TeamMember, User

# RBAC with domains (doc 08 §6): sub = user:<id>, dom = team:<id>,
# obj = resource type, act = verb. p.dom is always "*" (the role→permission
# matrix is identical in every team; WHICH team a user holds a role in is
# what the g-lines scope). Matching is exact: no keyMatch, no regex, so an
# unknown obj/act can never accidentally glob onto a policy.
MODEL_TEXT = """
[request_definition]
r = sub, dom, obj, act

[policy_definition]
p = sub, dom, obj, act

[role_definition]
g = _, _, _

[policy_effect]
e = some(where (p.eft == allow))

[matchers]
m = g(r.sub, p.sub, r.dom) && (p.dom == "*" || p.dom == r.dom) && p.obj == r.obj && p.act == r.act
"""

# (resource, action) -> minimum role. Derived row-by-row from doc 05's Role
# column. This is the single authoritative matrix: authorize() (api/deps.py)
# refuses at import time to build a dependency for a pair not listed here.
# `read` is deliberately the only viewer-reachable action: doc 10's DoD
# ("a viewer cannot mutate anything") is a property of this table first and
# a test (test_rbac_invariant.py) second.
PERMISSIONS: dict[tuple[str, str], str] = {
    ("host", "read"): "viewer",
    ("host", "sync"): "operator",
    ("host", "manage"): "admin",        # onboard, patch, probe
    ("host", "credentials"): "owner",   # rotate stored secrets
    ("host", "remove"): "owner",
    ("host", "power"): "owner",         # reboot/power off the underlying node
    ("host", "console"): "admin",       # node shell tickets (doc 08 §6 note)
    ("app", "read"): "viewer",
    ("app", "lifecycle"): "operator",
    ("app", "configure"): "operator",   # PATCH metadata, guest NICs
    ("app", "update"): "operator",
    ("app", "script_read"): "operator", # GET script + versions (doc 05 L115/117)
    ("app", "script"): "admin",         # PUT script, revert (doc 05: admin)
    ("app", "console"): "operator",
    ("app", "install"): "admin",        # store install
    ("app", "adopt"): "admin",
    ("app", "remove"): "admin",
    ("app", "migrate"): "admin",
    ("vm", "read"): "viewer",
    ("vm", "lifecycle"): "operator",
    ("vm", "configure"): "operator",    # guest NICs
    ("vm", "snapshot"): "operator",     # take/delete
    ("vm", "rollback"): "admin",
    ("vm", "create"): "admin",
    ("vm", "clone"): "admin",
    ("vm", "remove"): "owner",
    ("vm", "console"): "operator",
    ("storage", "read"): "viewer",
    ("storage", "content"): "admin",    # upload/delete volumes
    ("storage", "manage"): "admin",     # attach/edit
    ("storage", "remove"): "owner",     # detach
    ("network", "read"): "viewer",
    ("network", "guest"): "operator",
    ("network", "host"): "admin",
    ("backup", "read"): "viewer",
    ("backup", "run"): "operator",
    ("backup", "restore"): "admin",
    ("backup", "manage"): "admin",      # delete, prune
    ("catalog", "read"): "viewer",
    ("catalog", "refresh"): "admin",
    ("job", "read"): "viewer",
    ("job", "cancel"): "operator",
    ("schedule", "read"): "viewer",
    ("schedule", "manage"): "admin",
    ("schedule", "run"): "operator",
    ("alert", "read"): "viewer",
    ("alert", "ack"): "operator",
    ("alert", "manage"): "admin",
    ("channel", "manage"): "admin",
    ("metric", "read"): "viewer",
    ("audit", "read"): "admin",
    ("audit", "export"): "owner",
    ("settings", "read"): "admin",
    ("settings", "manage"): "admin",
    ("user", "read"): "admin",
    ("user", "manage"): "admin",
    ("team", "read"): "viewer",
    ("team", "manage"): "owner",
    ("entitlement", "read"): "viewer",
    ("entitlement", "manage"): "owner",
    ("meta", "read"): "viewer",
    ("meta", "update"): "owner",        # self-update (Phase 9 route not built yet)
}


def _sub(user_id: int) -> str:
    return f"user:{user_id}"


def _dom(team_id: int) -> str:
    return f"team:{team_id}"


def build_enforcer(db) -> casbin.Enforcer:
    # Deliberately local, not a module-level import: authorize() (api/deps.py)
    # imports THIS module lazily inside route-registration singletons in
    # hosts.py/cluster.py, which are themselves imported as part of
    # proxploy.api's package init. A module-level `from proxploy.api.deps
    # import ROLE_ORDER` here creates a two-way circular import: whichever
    # side loads first deadlocks on the other's not-yet-defined names (hit
    # by test_authz_bootstrap.py, which imports this module before anything
    # has imported proxploy.api). Local import breaks the cycle without
    # changing what ROLE_ORDER means or where it lives.
    from proxploy.api.deps import ROLE_ORDER

    model = casbin.Model()
    model.load_model_from_text(MODEL_TEXT)
    e = casbin.Enforcer(model)  # no adapter: in-memory, nothing auto-saved
    for (resource, action), min_role in PERMISSIONS.items():
        for role, order in ROLE_ORDER.items():
            if order >= ROLE_ORDER[min_role]:
                e.add_policy(f"role:{role}", "*", resource, action)
    for m in db.query(TeamMember).all():
        e.add_grouping_policy(_sub(m.user_id), f"role:{m.role}", _dom(m.team_id))
    return e


def sync_user(enforcer, db, user_id: int) -> None:
    """Re-derive one user's g-lines after a membership write. remove_filtered_
    grouping_policy(0, sub) drops every rule whose field 0 is the subject."""
    enforcer.remove_filtered_grouping_policy(0, _sub(user_id))
    for m in db.query(TeamMember).filter_by(user_id=user_id).all():
        enforcer.add_grouping_policy(_sub(user_id), f"role:{m.role}", _dom(m.team_id))


def enforce(enforcer, db, user: User, resource: str, action: str, *,
            team_id: int | None = None) -> bool:
    """Domain-scoped when team_id is given (host/app/vm resources); otherwise
    a global resource, allowed if ANY of the user's memberships grants it.
    Fail-closed: no membership, unknown resource, unknown action all deny."""
    sub = _sub(user.id)
    if team_id is not None:
        return bool(enforcer.enforce(sub, _dom(team_id), resource, action))
    team_ids = [m.team_id for m in
                db.query(TeamMember.team_id).filter_by(user_id=user.id)]
    return any(enforcer.enforce(sub, _dom(t), resource, action) for t in team_ids)
