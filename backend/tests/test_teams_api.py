"""Task 6: teams/members CRUD + GET /users. Route template matches
hosts.py/apps.py -- authorize() before require_entitlement(), sync_user()
called after every membership write so the in-memory enforcer reflects the
change without a restart (services/authz.py docstring)."""
import pytest
from fastapi.testclient import TestClient

from proxploy.models import AuditEvent, Host, Team, TeamMember, User
from tests.support import make_app


def _mk_user(client, csrf_header, email, role, password="Correct-Horse-Battery-9"):
    r = client.post("/api/v1/users", json={"email": email, "password": password,
                                           "role": role}, headers=csrf_header(client))
    assert r.status_code == 201, r.text
    return r.json()


def _login(client, csrf_header, email, password="Correct-Horse-Battery-9"):
    r = client.post("/api/v1/auth/login", json={"email": email, "password": password},
                    headers=csrf_header(client))
    assert r.status_code == 200, r.text


def _logout(client, csrf_header):
    client.post("/api/v1/auth/logout", headers=csrf_header(client))


@pytest.fixture
def app_client(tmp_path, csrf_header, bootstrap_admin):
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)   # owner session, default team
        yield c


def test_owner_creates_team(app_client, csrf_header):
    r = app_client.post("/api/v1/teams", json={"name": "Ops"},
                        headers=csrf_header(app_client))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "Ops" and body["slug"] == "ops"
    assert body["member_count"] == 0 and body["host_count"] == 0
    with app_client.app.state.sessionmaker() as db:
        row = db.query(AuditEvent).filter_by(action="team.create").one()
        assert row.target_id == body["id"]


def test_admin_cannot_create_team(app_client, csrf_header):
    _mk_user(app_client, csrf_header, "admin@x.io", "admin")
    _logout(app_client, csrf_header)
    _login(app_client, csrf_header, "admin@x.io")
    r = app_client.post("/api/v1/teams", json={"name": "Ops"},
                        headers=csrf_header(app_client))
    assert r.status_code == 403


def test_member_upsert_immediately_changes_enforcement(app_client, csrf_header):
    r = app_client.post("/api/v1/teams", json={"name": "Ops"},
                        headers=csrf_header(app_client))
    team_id = r.json()["id"]
    with app_client.app.state.sessionmaker() as db:
        h = Host(name="ops-host", address="https://10.0.0.9:8006", node_name="pve1",
                 team_id=team_id)
        db.add(h)
        db.commit()
        host_id = h.id

    v = _mk_user(app_client, csrf_header, "v@x.io", "viewer")
    r = app_client.put(f"/api/v1/teams/{team_id}/members/{v['id']}",
                       json={"role": "admin"}, headers=csrf_header(app_client))
    assert r.status_code == 200, r.text
    assert r.json() == {"user_id": v["id"], "email": "v@x.io",
                        "display_name": None, "last_login_at": None,
                        "role": "admin"}

    _logout(app_client, csrf_header)
    _login(app_client, csrf_header, "v@x.io")
    r = app_client.patch(f"/api/v1/hosts/{host_id}", json={"node_shell_enabled": True},
                         headers=csrf_header(app_client))
    assert r.status_code == 200, r.text   # proves sync_user ran, no restart needed


def test_removing_membership_revokes_it(app_client, csrf_header):
    r = app_client.post("/api/v1/teams", json={"name": "Ops2"},
                        headers=csrf_header(app_client))
    team_id = r.json()["id"]
    with app_client.app.state.sessionmaker() as db:
        h = Host(name="ops-host2", address="https://10.0.0.9:8006", node_name="pve1",
                 team_id=team_id)
        db.add(h)
        db.commit()
        host_id = h.id
    v = _mk_user(app_client, csrf_header, "v2@x.io", "viewer")
    app_client.put(f"/api/v1/teams/{team_id}/members/{v['id']}", json={"role": "admin"},
                   headers=csrf_header(app_client))
    r = app_client.delete(f"/api/v1/teams/{team_id}/members/{v['id']}",
                          headers=csrf_header(app_client))
    assert r.status_code == 200

    _logout(app_client, csrf_header)
    _login(app_client, csrf_header, "v2@x.io")
    r = app_client.patch(f"/api/v1/hosts/{host_id}", json={"node_shell_enabled": True},
                         headers=csrf_header(app_client))
    assert r.status_code == 403


def test_deleting_default_team_is_409(app_client, csrf_header):
    with app_client.app.state.sessionmaker() as db:
        default_id = db.query(Team).filter_by(slug="default").one().id
    r = app_client.delete(f"/api/v1/teams/{default_id}", headers=csrf_header(app_client))
    assert r.status_code == 409


def test_removing_last_default_team_owner_is_409(app_client, csrf_header):
    with app_client.app.state.sessionmaker() as db:
        owner = db.query(User).filter_by(email="admin@example.com").one()
        default_id = db.query(TeamMember).filter_by(user_id=owner.id).one().team_id
        owner_id = owner.id
    r = app_client.delete(f"/api/v1/teams/{default_id}/members/{owner_id}",
                          headers=csrf_header(app_client))
    assert r.status_code == 409
    assert "last owner" in r.json()["detail"]


def test_removing_a_users_only_membership_in_a_non_default_team_is_allowed(app_client,
                                                                            csrf_header):
    """Deliberate: A1's fail-closed design means this leaves the user with no
    teams at all (denied everything) -- but that IS the mechanism for fully
    deauthorizing someone, and the only guard the spec calls for is the
    whole-install lockout case (last owner of the *default* team)."""
    r = app_client.post("/api/v1/teams", json={"name": "Solo"},
                        headers=csrf_header(app_client))
    team_id = r.json()["id"]
    v = _mk_user(app_client, csrf_header, "solo@x.io", "viewer")
    with app_client.app.state.sessionmaker() as db:
        db.query(TeamMember).filter_by(user_id=v["id"]).delete()  # drop default-team row
        db.commit()
    app_client.put(f"/api/v1/teams/{team_id}/members/{v['id']}", json={"role": "owner"},
                   headers=csrf_header(app_client))
    r = app_client.delete(f"/api/v1/teams/{team_id}/members/{v['id']}",
                          headers=csrf_header(app_client))
    assert r.status_code == 200

    _logout(app_client, csrf_header)
    _login(app_client, csrf_header, "solo@x.io")
    assert app_client.get("/api/v1/hosts").status_code == 403  # membership-less: denied


def test_get_users_lists_memberships(app_client, csrf_header):
    v = _mk_user(app_client, csrf_header, "v3@x.io", "operator")
    r = app_client.get("/api/v1/users", headers=csrf_header(app_client))
    assert r.status_code == 200, r.text
    by_email = {u["email"]: u for u in r.json()}
    assert "v3@x.io" in by_email
    entry = by_email["v3@x.io"]
    assert entry["is_active"] is True
    assert any(t["role"] == "operator" for t in entry["teams"])
    assert entry["id"] == v["id"]


def test_teams_and_users_routes_401_anonymous(app_client, csrf_header):
    with TestClient(app_client.app) as anon:
        h = csrf_header(anon)
        assert anon.get("/api/v1/teams").status_code == 401
        assert anon.post("/api/v1/teams", json={"name": "x"}, headers=h).status_code == 401
        assert anon.get("/api/v1/users").status_code == 401


def test_entitlement_gate_blocks_owner_when_off(app_client, csrf_header):
    app_client.app.state.entitlements._features = {}
    try:
        r = app_client.get("/api/v1/teams", headers=csrf_header(app_client))
        assert r.status_code == 403
    finally:
        app_client.app.state.entitlements._features = None


def test_deleting_a_team_drops_its_grants_even_if_the_id_comes_back(app_client,
                                                                   csrf_header):
    """team_members cascades in the DB, but casbin keeps its own g-lines keyed
    on the team id and enforce() never re-reads the table. SQLite hands a
    deleted team's rowid to the next team created, so without the rebuild in
    delete_team the new team silently inherits the old one's grants."""
    r = app_client.post("/api/v1/teams", json={"name": "Old"},
                        headers=csrf_header(app_client))
    old_id = r.json()["id"]
    v = _mk_user(app_client, csrf_header, "ghost@x.io", "viewer")
    app_client.put(f"/api/v1/teams/{old_id}/members/{v['id']}", json={"role": "owner"},
                   headers=csrf_header(app_client))
    assert app_client.delete(f"/api/v1/teams/{old_id}",
                             headers=csrf_header(app_client)).status_code == 200

    r = app_client.post("/api/v1/teams", json={"name": "New"},
                        headers=csrf_header(app_client))
    new_id = r.json()["id"]
    assert new_id == old_id, "this test only means something when the id is reused"

    with app_client.app.state.sessionmaker() as db:
        h = Host(name="new-host", address="https://10.0.0.9:8006", node_name="pve1",
                 team_id=new_id)
        db.add(h)
        db.commit()
        host_id = h.id

    # ghost@x.io was never made a member of "New"; its only surviving
    # membership is viewer in the default team.
    _logout(app_client, csrf_header)
    _login(app_client, csrf_header, "ghost@x.io")
    assert app_client.patch(f"/api/v1/hosts/{host_id}",
                            json={"node_shell_enabled": True},
                            headers=csrf_header(app_client)).status_code == 403
    assert app_client.delete(f"/api/v1/hosts/{host_id}",
                             headers=csrf_header(app_client)).status_code == 403


def test_a_host_in_another_team_does_not_hand_over_its_pve_token_id(app_client,
                                                                   csrf_header):
    """GET /hosts/{id} is the only host read that returns credentials[], and
    public_meta carries the PVE API token id. hosts.py scoped its writes with
    scope_host() from the start but left every id-carrying read global, so a
    viewer in any team could read another team's host detail, node hardware
    (disk serials) and full PVE task logs."""
    r = app_client.post("/api/v1/teams", json={"name": "TeamA"},
                        headers=csrf_header(app_client))
    team_a = r.json()["id"]
    with app_client.app.state.sessionmaker() as db:
        h = Host(name="a-host", address="https://10.0.0.9:8006", node_name="pve1",
                 team_id=team_a)
        db.add(h)
        db.commit()
        host_id = h.id

    r = app_client.post("/api/v1/teams", json={"name": "TeamB"},
                        headers=csrf_header(app_client))
    team_b = r.json()["id"]
    v = _mk_user(app_client, csrf_header, "b@x.io", "viewer")
    app_client.put(f"/api/v1/teams/{team_b}/members/{v['id']}", json={"role": "admin"},
                   headers=csrf_header(app_client))

    _logout(app_client, csrf_header)
    _login(app_client, csrf_header, "b@x.io")
    for path in (f"/api/v1/hosts/{host_id}",
                 f"/api/v1/hosts/{host_id}/nodes/pve1/hardware",
                 f"/api/v1/hosts/{host_id}/tasks"):
        assert app_client.get(path).status_code == 403, path
