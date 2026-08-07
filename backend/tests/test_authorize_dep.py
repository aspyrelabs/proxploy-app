"""authorize() dependency behaviour (doc 08 §6 enforcement point), proven on
the two routers this task converts (hosts, cluster)."""
import pytest
from fastapi.testclient import TestClient

from proxploy.models import AuditEvent, Host, Team, TeamMember, User
from tests.support import make_app


def _mk_user(client, csrf_header, email, role, password="correct-horse-battery"):
    h = csrf_header(client)
    r = client.post("/api/v1/users", json={"email": email, "password": password,
                                           "role": role}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def _login(client, csrf_header, email, password="correct-horse-battery"):
    r = client.post("/api/v1/auth/login", json={"email": email,
                    "password": password}, headers=csrf_header(client))
    assert r.status_code == 200, r.text


@pytest.fixture
def app_client(tmp_path, csrf_header, bootstrap_admin):
    from tests.support import make_app
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)             # owner session, default team
        yield c


def test_unregistered_permission_pair_fails_at_registration():
    from proxploy.api.deps import authorize
    with pytest.raises(RuntimeError, match="unregistered"):
        authorize("gizmo", "frobnicate")


def test_viewer_reads_hosts_but_cannot_patch(app_client, csrf_header):
    _mk_user(app_client, csrf_header, "v@x.io", "viewer")
    app_client.post("/api/v1/auth/logout", headers=csrf_header(app_client))
    _login(app_client, csrf_header, "v@x.io")
    assert app_client.get("/api/v1/hosts").status_code == 200
    r = app_client.patch("/api/v1/hosts/1", json={"node_shell_enabled": True},
                         headers=csrf_header(app_client))
    assert r.status_code == 403


def test_denied_attempt_writes_an_audit_row(app_client, csrf_header, tmp_path):
    """Doc 08 §7: denials are evidence too."""
    _mk_user(app_client, csrf_header, "v2@x.io", "viewer")
    app_client.post("/api/v1/auth/logout", headers=csrf_header(app_client))
    _login(app_client, csrf_header, "v2@x.io")
    app_client.patch("/api/v1/hosts/1", json={"node_shell_enabled": True},
                     headers=csrf_header(app_client))
    with app_client.app.state.sessionmaker() as db:
        row = (db.query(AuditEvent)
               .filter_by(action="host.manage", result="denied").one())
        assert row.actor_type == "user"


def test_team_scoped_route_checks_the_owning_team(app_client, csrf_header):
    """Admin of team B cannot patch team A's host, the domain comes from
    hosts.team_id, not from 'has admin anywhere'.

    NOTE: the plan's Step 1 test posted to POST /hosts/{id}/sync, which does
    not exist in hosts.py (doc 05 lists it, but no task in this plan adds it
    see the Task 2 report). PATCH /hosts/{id} exercises the identical
    scope_host()-driven domain check on an admin-gated action that does
    exist."""
    with app_client.app.state.sessionmaker() as db:
        team_b = Team(name="B", slug="b")
        db.add(team_b); db.commit()
        h = Host(name="scoped", address="https://10.0.0.9:8006",
                 node_name="pve1")   # team_id NULL -> default team
        db.add(h); db.commit()
        host_id, team_b_id = h.id, team_b.id
    _mk_user(app_client, csrf_header, "badmin@x.io", "viewer")
    with app_client.app.state.sessionmaker() as db:
        u = db.query(User).filter_by(email="badmin@x.io").one()
        m = db.query(TeamMember).filter_by(user_id=u.id).one()
        m.role = "viewer"; db.commit()
        db.add(TeamMember(team_id=team_b_id, user_id=u.id, role="admin"))
        db.commit()
        from proxploy.services.authz import sync_user
        sync_user(app_client.app.state.authz, db, u.id)
    app_client.post("/api/v1/auth/logout", headers=csrf_header(app_client))
    _login(app_client, csrf_header, "badmin@x.io")
    r = app_client.patch(f"/api/v1/hosts/{host_id}",
                         json={"node_shell_enabled": True},
                         headers=csrf_header(app_client))
    assert r.status_code == 403   # admin of B, viewer in the host's team


def test_anonymous_still_gets_401_not_403(app_client, csrf_header):
    h = csrf_header(app_client)
    app_client.post("/api/v1/auth/logout", headers=h)
    assert app_client.get("/api/v1/hosts").status_code == 401
    assert app_client.patch("/api/v1/hosts/1", json={},
                            headers=h).status_code == 401


def test_user_with_no_team_membership_is_denied_reads_too(app_client, csrf_header):
    """Behaviour change from Phase 1's require_role stub (which defaulted a
    membership-less user to 'viewer'): enforce() has no g-line to match for a
    user in zero teams, so even GET /hosts is a 403. Fail-closed is correct
    for Phase 8, but it IS a change worth a named test."""
    _mk_user(app_client, csrf_header, "orphan@x.io", "viewer")
    with app_client.app.state.sessionmaker() as db:
        u = db.query(User).filter_by(email="orphan@x.io").one()
        db.query(TeamMember).filter_by(user_id=u.id).delete()
        db.commit()
        from proxploy.services.authz import sync_user
        sync_user(app_client.app.state.authz, db, u.id)
    app_client.post("/api/v1/auth/logout", headers=csrf_header(app_client))
    _login(app_client, csrf_header, "orphan@x.io")
    assert app_client.get("/api/v1/hosts").status_code == 403
