"""AuthZ core (doc 08 §6, doc 10 Phase 8): the casbin model, the static
permission matrix, and membership-driven grouping rules. Pure — no HTTP."""
import pytest

from proxploy.api.deps import ROLE_ORDER
from proxploy.models import Team, TeamMember, User
from proxploy.services.authz import PERMISSIONS, build_enforcer, enforce, sync_user
from tests.support import make_db


def _user(db, email, *, role, team):
    u = User(email=email)
    db.add(u); db.commit()
    db.add(TeamMember(team_id=team.id, user_id=u.id, role=role))
    db.commit()
    return u


def _team(db, slug):
    t = Team(name=slug.title(), slug=slug)
    db.add(t); db.commit()
    return t


@pytest.fixture
def world(tmp_path):
    db = make_db(tmp_path)
    a, b = _team(db, "team-a"), _team(db, "team-b")
    return {
        "db": db, "a": a, "b": b,
        "viewer": _user(db, "v@x.io", role="viewer", team=a),
        "operator": _user(db, "o@x.io", role="operator", team=a),
        "admin": _user(db, "ad@x.io", role="admin", team=a),
        "owner": _user(db, "ow@x.io", role="owner", team=a),
    }


def test_matrix_uses_only_known_roles():
    assert set(PERMISSIONS.values()) <= set(ROLE_ORDER)


def test_matrix_reads_are_viewer_and_matrix_has_no_write_at_viewer():
    """Doc 10 DoD: a viewer cannot mutate anything. The matrix itself must
    already say so — every non-read action requires operator or above."""
    for (resource, action), min_role in PERMISSIONS.items():
        if action != "read":
            assert ROLE_ORDER[min_role] >= ROLE_ORDER["operator"], (
                f"({resource}, {action}) grants a mutation to {min_role}")


def test_role_ladder_is_cumulative(world):
    e = build_enforcer(world["db"])
    dom = world["a"].id
    assert enforce(e, world["db"], world["viewer"], "app", "read", team_id=dom)
    assert not enforce(e, world["db"], world["viewer"], "app", "lifecycle", team_id=dom)
    assert enforce(e, world["db"], world["operator"], "app", "lifecycle", team_id=dom)
    assert not enforce(e, world["db"], world["operator"], "app", "install", team_id=dom)
    assert enforce(e, world["db"], world["admin"], "app", "install", team_id=dom)
    assert not enforce(e, world["db"], world["admin"], "host", "remove", team_id=dom)
    assert enforce(e, world["db"], world["owner"], "host", "remove", team_id=dom)


def test_domains_scope_roles_to_their_team(world):
    """An admin of team A is nobody in team B (doc 08 §6)."""
    e = build_enforcer(world["db"])
    assert enforce(e, world["db"], world["admin"], "host", "manage",
                   team_id=world["a"].id)
    assert not enforce(e, world["db"], world["admin"], "host", "manage",
                       team_id=world["b"].id)


def test_global_enforcement_passes_on_any_membership(world):
    """team_id=None = a global resource (settings, catalog, users): the check
    passes if ANY of the user's memberships grants it."""
    db = world["db"]
    e = build_enforcer(db)
    u = world["viewer"]
    assert not enforce(e, db, u, "settings", "manage")
    db.add(TeamMember(team_id=world["b"].id, user_id=u.id, role="admin"))
    db.commit()
    sync_user(e, db, u.id)
    assert enforce(e, db, u, "settings", "manage")


def test_fail_closed_everywhere(world):
    e = build_enforcer(world["db"])
    db = world["db"]
    # unknown resource, unknown action, user with no memberships: all deny
    assert not enforce(e, db, world["owner"], "nonsense", "read",
                       team_id=world["a"].id)
    assert not enforce(e, db, world["owner"], "app", "nonsense",
                       team_id=world["a"].id)
    lone = User(email="ghost@x.io")
    db.add(lone); db.commit()
    assert not enforce(e, db, lone, "app", "read", team_id=world["a"].id)
    assert not enforce(e, db, lone, "app", "read")


def test_sync_user_revokes_a_removed_membership(world):
    db = world["db"]
    e = build_enforcer(db)
    m = (db.query(TeamMember)
         .filter_by(user_id=world["admin"].id, team_id=world["a"].id).one())
    db.delete(m); db.commit()
    sync_user(e, db, world["admin"].id)
    assert not enforce(e, db, world["admin"], "host", "manage",
                       team_id=world["a"].id)
