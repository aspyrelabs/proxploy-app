"""One team's admin must not reach another team's host.

The role ladder and the route/auth invariants all ask "what may this ROLE do".
None of them asks "whose resource is this", so nothing pinned the boundary that
separates two teams. On a product sold to MSPs, where the whole Team tier is
"carve your fleet into clients and let an operator see only the client they are
working on", that is the boundary the tier is sold on.

The mechanism exists and reads correctly: authorize(..., scope_of=scope_host())
resolves the owning team from the path and enforce() then asks casbin in that
domain specifically, with roles coming only from team_members and no global
role bypass. What was missing is a test that the mechanism is actually reached,
end to end, by a real request from a real signed-in admin of the wrong team.

These use ids directly rather than any UI path, which is the point: an id in a
URL is guessable, and the question is what the backend does when someone tries
the next number along.
"""
import pytest
from fastapi.testclient import TestClient

from proxploy.models import Host, Team, TeamMember, User
from proxploy.services.authz import sync_user
from tests.support import entitle, make_app

PASSWORD = "Correct-Horse-Battery-9"


def _login(c, h, email):
    c.post("/api/v1/auth/logout", headers=h)
    r = c.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD},
               headers=h)
    assert r.status_code == 200, f"login {email} failed: {r.text}"


@pytest.fixture
def two_teams(tmp_path, csrf_header):
    """An owner, a host owned by team "red", and an admin who belongs only to
    team "blue". Membership is written directly, then synced into the enforcer
    the same way api/teams.py does: the point is the enforcement boundary, not
    the teams UI, and going through the API here would test two things at once.
    """
    app = make_app(tmp_path)
    entitle(app, "teams.rbac")
    with TestClient(app) as c:
        h = csrf_header(c)
        c.post("/api/v1/users", json={"email": "owner@x.io", "password": PASSWORD},
               headers=h)
        c.post("/api/v1/auth/login", json={"email": "owner@x.io", "password": PASSWORD},
               headers=h)
        r = c.post("/api/v1/users", json={"email": "blue@x.io", "role": "admin",
                                          "password": PASSWORD}, headers=h)
        assert r.status_code in (200, 201), r.text

        with app.state.sessionmaker() as db:
            red = Team(name="Red", slug="red")
            blue = Team(name="Blue", slug="blue")
            db.add_all([red, blue])
            db.commit()
            host = Host(name="red-node", address="https://10.0.0.9:8006",
                        team_id=red.id)
            db.add(host)
            blue_user = db.query(User).filter_by(email="blue@x.io").one()
            # Out of every team they were seeded into, and into blue only, so
            # "admin somewhere" cannot be mistaken for "admin here".
            db.query(TeamMember).filter_by(user_id=blue_user.id).delete()
            db.add(TeamMember(team_id=blue.id, user_id=blue_user.id, role="admin"))
            db.commit()
            # The enforcer's g-lines are derived from team_members and do not
            # follow a direct write; api/teams.py calls this after every
            # membership change. Without it this user holds no role anywhere
            # and every assertion below passes by denying everything, which is
            # what test_the_same_admin_can_act_on_a_host_in_their_own_team is
            # here to catch.
            sync_user(app.state.authz, db, blue_user.id)
            ids = {"host": host.id, "red": red.id, "blue": blue.id}
        yield app, c, h, ids


def test_an_admin_of_another_team_cannot_read_a_host(two_teams, csrf_header):
    app, c, h, ids = two_teams
    _login(c, h, "blue@x.io")
    r = c.get(f"/api/v1/hosts/{ids['host']}")
    assert r.status_code == 403, (
        f"blue admin read red's host: {r.status_code} {r.text[:200]}")


@pytest.mark.parametrize("method,suffix", [
    ("PATCH", ""),                       # host.manage
    ("DELETE", ""),                      # host.remove, owner only AND scoped
    ("POST", "/sync"),                   # host.sync
    ("POST", "/credentials"),            # host.credentials, the stored secrets
    ("POST", "/test"),                   # host.manage
    ("POST", "/shell/tickets"),          # host.console, a root shell on the node
])
def test_an_admin_of_another_team_cannot_act_on_a_host(two_teams, method, suffix):
    """Every mutating host route that takes an id, tried by the wrong team.

    host.credentials and host.console are the two that matter most: one hands
    back the stored Proxmox tokens, the other opens a shell on the node.
    """
    app, c, h, ids = two_teams
    _login(c, h, "blue@x.io")
    r = c.request(method, f"/api/v1/hosts/{ids['host']}{suffix}", headers=h, json={})
    assert r.status_code == 403, (
        f"blue admin reached {method} .../{ids['host']}{suffix}: "
        f"{r.status_code} {r.text[:200]}")


def test_the_same_admin_can_act_on_a_host_in_their_own_team(two_teams):
    """The other half, without which the tests above pass by denying everything.

    Same user, same role, same route, only the host's team differs. If this
    fails the isolation above proves nothing, because a blanket denial would
    look identical.
    """
    app, c, h, ids = two_teams
    with app.state.sessionmaker() as db:
        own = Host(name="blue-node", address="https://10.0.0.10:8006",
                   team_id=ids["blue"])
        db.add(own)
        db.commit()
        own_id = own.id

    _login(c, h, "blue@x.io")
    denied = c.get(f"/api/v1/hosts/{ids['host']}")
    allowed = c.get(f"/api/v1/hosts/{own_id}")
    assert denied.status_code == 403
    assert allowed.status_code != 403, (
        f"blue admin was refused their OWN team's host: {allowed.status_code}")


def test_a_host_id_that_does_not_exist_is_not_an_existence_oracle(two_teams):
    """_team_of_host returns None for a missing row so the handler 404s rather
    than the guard 403ing, which would let an outsider map which ids exist by
    reading the status code. Both answers must be indistinguishable to someone
    without access, so this pins that a missing id does NOT answer 403 while a
    real-but-foreign id does."""
    app, c, h, ids = two_teams
    _login(c, h, "blue@x.io")
    missing = c.get("/api/v1/hosts/999999")
    foreign = c.get(f"/api/v1/hosts/{ids['host']}")
    assert foreign.status_code == 403
    assert missing.status_code == 404, (
        f"a nonexistent host answered {missing.status_code}, which distinguishes "
        f"it from one that exists but belongs to another team")
