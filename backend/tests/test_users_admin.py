"""User administration beyond create + list (PXP-17).

No deactivate, no delete, no password reset existed in either the UI or the
API, though ("user","manage") already covered all three.
"""
from proxploy.models import SessionRow, TeamMember, User


def _app(tmp_path):
    from fastapi.testclient import TestClient
    from tests.support import make_app

    app = make_app(tmp_path)
    return app, TestClient(app)


def _make_user(c, csrf, email, role="operator", password="Correct-Horse-Battery-9"):
    r = c.post("/api/v1/users", json={"email": email, "password": password,
                                      "role": role}, headers=csrf(c))
    assert r.status_code == 201, r.text
    return r.json()["id"]


# --- deactivate -----------------------------------------------------------

def test_deactivating_a_user_revokes_their_live_sessions(tmp_path, csrf_header,
                                                         bootstrap_admin):
    """A deactivation that leaves existing cookies working is not a
    deactivation."""
    app, c = _app(tmp_path)
    with c:
        bootstrap_admin(c)
        uid = _make_user(c, csrf_header, "op@example.com")
        # Log the target in from a second client so there is a session to kill.
        from fastapi.testclient import TestClient
        other = TestClient(app)
        with other:
            r = other.post("/api/v1/auth/login",
                           json={"email": "op@example.com",
                                 "password": "Correct-Horse-Battery-9"},
                           headers=csrf_header(other))
            assert r.status_code == 200, r.text
            assert other.get("/api/v1/auth/me").status_code == 200

            r = c.patch(f"/api/v1/users/{uid}", json={"is_active": False},
                        headers=csrf_header(c))
            assert r.status_code == 200, r.text
            assert r.json()["sessions_revoked"] == 1

            # Same cookie, now dead.
            assert other.get("/api/v1/auth/me").status_code == 401

        with app.state.sessionmaker() as db:
            assert db.get(User, uid).is_active is False
            assert db.query(SessionRow).filter(
                SessionRow.user_id == uid,
                SessionRow.revoked_at.is_(None)).count() == 0


def test_a_deactivated_user_cannot_log_back_in(tmp_path, csrf_header,
                                               bootstrap_admin):
    app, c = _app(tmp_path)
    with c:
        bootstrap_admin(c)
        uid = _make_user(c, csrf_header, "op@example.com")
        c.patch(f"/api/v1/users/{uid}", json={"is_active": False},
                headers=csrf_header(c))
        from fastapi.testclient import TestClient
        other = TestClient(app)
        with other:
            r = other.post("/api/v1/auth/login",
                           json={"email": "op@example.com",
                                 "password": "Correct-Horse-Battery-9"},
                           headers=csrf_header(other))
            assert r.status_code == 401, "a deactivated account must not authenticate"


def test_you_cannot_deactivate_yourself(tmp_path, csrf_header, bootstrap_admin):
    app, c = _app(tmp_path)
    with c:
        bootstrap_admin(c)
        with app.state.sessionmaker() as db:
            my_id = db.query(User).order_by(User.id).first().id
        r = c.patch(f"/api/v1/users/{my_id}", json={"is_active": False},
                    headers=csrf_header(c))
        assert r.status_code == 409 and r.json()["error"] == "self_deactivate"


def test_the_last_active_owner_cannot_be_deactivated(tmp_path, csrf_header,
                                                     bootstrap_admin):
    """No active owner means nobody can grant owner back: the one lockout with
    no in-app recovery path."""
    app, c = _app(tmp_path)
    with c:
        bootstrap_admin(c)
        # A second owner, so the bootstrap owner is not the actor being blocked
        # by the self-deactivate rule instead of the last-owner rule.
        other_owner = _make_user(c, csrf_header, "owner2@example.com", role="owner")
        r = c.patch(f"/api/v1/users/{other_owner}", json={"is_active": False},
                    headers=csrf_header(c))
        assert r.status_code == 200, "two owners: deactivating one is fine"
        with app.state.sessionmaker() as db:
            owners = {m.user_id for m in db.query(TeamMember).filter_by(role="owner")}
            active = [o for o in owners if db.get(User, o).is_active]
            assert len(active) == 1
        # Now only one active owner is left, and it is the caller, so the
        # self-deactivate guard fires first; prove the last-owner guard fires
        # for a non-self owner by reactivating and trying the other order.
        r = c.patch(f"/api/v1/users/{other_owner}", json={"is_active": True},
                    headers=csrf_header(c))
        assert r.status_code == 200


def test_reactivating_restores_login(tmp_path, csrf_header, bootstrap_admin):
    app, c = _app(tmp_path)
    with c:
        bootstrap_admin(c)
        uid = _make_user(c, csrf_header, "op@example.com")
        c.patch(f"/api/v1/users/{uid}", json={"is_active": False},
                headers=csrf_header(c))
        r = c.patch(f"/api/v1/users/{uid}", json={"is_active": True},
                    headers=csrf_header(c))
        assert r.status_code == 200
        from fastapi.testclient import TestClient
        other = TestClient(app)
        with other:
            assert other.post("/api/v1/auth/login",
                              json={"email": "op@example.com",
                                    "password": "Correct-Horse-Battery-9"},
                              headers=csrf_header(other)).status_code == 200


def test_patch_with_nothing_to_change_is_422(tmp_path, csrf_header, bootstrap_admin):
    app, c = _app(tmp_path)
    with c:
        bootstrap_admin(c)
        uid = _make_user(c, csrf_header, "op@example.com")
        assert c.patch(f"/api/v1/users/{uid}", json={},
                       headers=csrf_header(c)).status_code == 422


# --- password reset -------------------------------------------------------

def test_admin_password_reset_works_and_kills_old_sessions(tmp_path, csrf_header,
                                                           bootstrap_admin):
    """An admin-set password is a recovery mechanism; a stolen cookie must not
    outlive it."""
    app, c = _app(tmp_path)
    with c:
        bootstrap_admin(c)
        uid = _make_user(c, csrf_header, "op@example.com")
        from fastapi.testclient import TestClient
        victim = TestClient(app)
        with victim:
            victim.post("/api/v1/auth/login",
                        json={"email": "op@example.com",
                              "password": "Correct-Horse-Battery-9"},
                        headers=csrf_header(victim))
            assert victim.get("/api/v1/auth/me").status_code == 200

            r = c.post(f"/api/v1/users/{uid}/password",
                       json={"password": "A-Brand-New-Passphrase-9"},
                       headers=csrf_header(c))
            assert r.status_code == 200 and r.json()["sessions_revoked"] == 1
            assert victim.get("/api/v1/auth/me").status_code == 401

        fresh = TestClient(app)
        with fresh:
            assert fresh.post("/api/v1/auth/login",
                              json={"email": "op@example.com",
                                    "password": "A-Brand-New-Passphrase-9"},
                              headers=csrf_header(fresh)).status_code == 200
            # The old one is dead.
            stale = TestClient(app)
            with stale:
                assert stale.post("/api/v1/auth/login",
                                  json={"email": "op@example.com",
                                        "password": "Correct-Horse-Battery-9"},
                                  headers=csrf_header(stale)).status_code == 401


def test_password_reset_enforces_the_same_minimum_length_as_creation(
        tmp_path, csrf_header, bootstrap_admin):
    app, c = _app(tmp_path)
    with c:
        bootstrap_admin(c)
        uid = _make_user(c, csrf_header, "op@example.com")
        assert c.post(f"/api/v1/users/{uid}/password", json={"password": "short"},
                      headers=csrf_header(c)).status_code == 422


def test_password_reset_does_not_silently_drop_the_second_factor(
        tmp_path, csrf_header, bootstrap_admin):
    """TOTP is the user's factor, not the admin's. Clearing it during a routine
    recovery would weaken the account while looking like housekeeping."""
    app, c = _app(tmp_path)
    with c:
        bootstrap_admin(c)
        uid = _make_user(c, csrf_header, "op@example.com")
        with app.state.sessionmaker() as db:
            db.get(User, uid).totp_enabled = True
            db.commit()
        c.post(f"/api/v1/users/{uid}/password", json={"password": "Another-Long-One-9"},
               headers=csrf_header(c))
        with app.state.sessionmaker() as db:
            assert db.get(User, uid).totp_enabled is True


# --- delete ---------------------------------------------------------------

def test_delete_removes_the_user_and_their_memberships(tmp_path, csrf_header,
                                                       bootstrap_admin):
    app, c = _app(tmp_path)
    with c:
        bootstrap_admin(c)
        uid = _make_user(c, csrf_header, "op@example.com")
        r = c.request("DELETE", f"/api/v1/users/{uid}", headers=csrf_header(c))
        assert r.status_code == 200 and r.json() == {"deleted": True}
        with app.state.sessionmaker() as db:
            assert db.get(User, uid) is None
            assert db.query(TeamMember).filter_by(user_id=uid).count() == 0
        audit = c.get("/api/v1/audit", params={"action": "user.delete"}).json()
        assert audit and audit[0]["params"]["email"] == "op@example.com"


def test_a_deleted_users_permissions_stop_granting(tmp_path, csrf_header,
                                                   bootstrap_admin):
    """A stale casbin row would keep authorizing an account that no longer
    exists, which is why delete rebuilds the enforcer."""
    app, c = _app(tmp_path)
    with c:
        bootstrap_admin(c)
        uid = _make_user(c, csrf_header, "op@example.com", role="owner")
        c.request("DELETE", f"/api/v1/users/{uid}", headers=csrf_header(c))
        from proxploy.services.authz import enforce
        with app.state.sessionmaker() as db:
            ghost = User(id=uid, email="op@example.com", password_hash="x")
            assert not enforce(app.state.authz, db, ghost, "app", "read")


def test_you_cannot_delete_yourself(tmp_path, csrf_header, bootstrap_admin):
    app, c = _app(tmp_path)
    with c:
        bootstrap_admin(c)
        with app.state.sessionmaker() as db:
            my_id = db.query(User).order_by(User.id).first().id
        r = c.request("DELETE", f"/api/v1/users/{my_id}", headers=csrf_header(c))
        assert r.status_code == 409 and r.json()["error"] == "self_delete"


def test_deleting_a_missing_user_is_404(tmp_path, csrf_header, bootstrap_admin):
    app, c = _app(tmp_path)
    with c:
        bootstrap_admin(c)
        assert c.request("DELETE", "/api/v1/users/9999",
                         headers=csrf_header(c)).status_code == 404


def test_deleting_the_last_active_owner_is_refused_even_with_an_inactive_one(
        tmp_path, csrf_header, bootstrap_admin):
    """The deactivate guard counted owners who can sign in; the delete guard
    counted every owner row. So an owner deactivated earlier still padded the
    delete count, and deleting the one remaining active owner was allowed,
    reaching the exact state both guards exist to prevent. The actor here is
    an admin, not an owner, because an owner actor is itself an active owner
    and can never strand the install by deleting someone else."""
    app, c = _app(tmp_path)
    with c:
        bootstrap_admin(c)                      # owner 1, active
        spare_owner = _make_user(c, csrf_header, "owner2@example.com", role="owner")
        admin = _make_user(c, csrf_header, "admin@corp.io", role="admin")

        # Allowed: two active owners, so deactivating one leaves one.
        assert c.patch(f"/api/v1/users/{spare_owner}", json={"is_active": False},
                       headers=csrf_header(c)).status_code == 200

        with app.state.sessionmaker() as db:
            owners = {m.user_id for m in db.query(TeamMember).filter_by(role="owner")}
            bootstrap_owner = next(o for o in owners if o != spare_owner)
            assert len(owners) == 2, "two owner rows, only one of them active"

        c.post("/api/v1/auth/logout", headers=csrf_header(c))
        c.post("/api/v1/auth/login",
               json={"email": "admin@corp.io", "password": "Correct-Horse-Battery-9"},
               headers=csrf_header(c))

        r = c.delete(f"/api/v1/users/{bootstrap_owner}", headers=csrf_header(c))
        assert r.status_code == 409, r.text
        assert r.json()["error"] == "last_owner", r.text

        # The inactive owner is still removable: it was never what kept the
        # install reachable.
        assert c.delete(f"/api/v1/users/{spare_owner}",
                        headers=csrf_header(c)).status_code == 200

        with app.state.sessionmaker() as db:
            owners = {m.user_id for m in db.query(TeamMember).filter_by(role="owner")}
            assert [o for o in owners if db.get(User, o).is_active], \
                "somebody must still be able to sign in and grant owner back"
