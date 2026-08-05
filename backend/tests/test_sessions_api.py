"""Self-service session list/revoke routes (Task 9): GET /auth/sessions and
DELETE /auth/sessions/{sid}. Ownership is enforced by filtering on
user_id=user.id, so another user's session id 404s rather than 403ing --
see api/auth.py::revoke_session_route's comment on why that's not an
existence oracle either way.
"""
from datetime import timedelta

from fastapi.testclient import TestClient

from proxploy.models import SessionRow, User, utcnow
from proxploy.services.authn import _th
from tests.support import make_app

ADMIN_EMAIL = "admin@example.com"
PASSWORD = "correct-horse-battery"


def _login(c, h, email=ADMIN_EMAIL, password=PASSWORD):
    r = c.post("/api/v1/auth/login", json={"email": email, "password": password}, headers=h)
    assert r.status_code == 200
    return r.cookies["pp_session"]


def test_two_logins_listed_with_current_flag_and_revoke(tmp_path, csrf_header, bootstrap_admin):
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)  # session 1
        h = csrf_header(c)
        raw1 = c.cookies["pp_session"]

        raw2 = _login(c, h)  # session 2, same user

        rows = c.get("/api/v1/auth/sessions", cookies={"pp_session": raw2}).json()
        assert len(rows) == 2
        for row in rows:
            assert {"id", "ip", "user_agent", "created_at", "last_seen_at", "current"} <= row.keys()
        current = [row for row in rows if row["current"]]
        assert len(current) == 1

        other = next(row for row in rows if not row["current"])
        assert other["id"] != current[0]["id"]

        d = c.delete(f"/api/v1/auth/sessions/{other['id']}", headers=h, cookies={"pp_session": raw2})
        assert d.status_code == 200

        # the revoked session can no longer authenticate
        assert c.get("/api/v1/auth/me", cookies={"pp_session": raw1}).status_code == 401

        # and it no longer appears in the list -- revoked rows are absent
        rows2 = c.get("/api/v1/auth/sessions", cookies={"pp_session": raw2}).json()
        assert len(rows2) == 1
        assert rows2[0]["id"] == current[0]["id"]


def test_deleting_another_users_session_is_404(tmp_path, csrf_header, bootstrap_admin):
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        h = csrf_header(c)
        admin_raw = c.cookies["pp_session"]

        r = c.post("/api/v1/users", json={"email": "op@example.com",
                    "password": "another-correct-pw", "role": "operator"},
                    headers=h, cookies={"pp_session": admin_raw})
        assert r.status_code == 201
        op_raw = _login(c, h, email="op@example.com", password="another-correct-pw")

        op_sessions = c.get("/api/v1/auth/sessions", cookies={"pp_session": op_raw}).json()
        assert len(op_sessions) == 1
        op_sid = op_sessions[0]["id"]

        # admin tries to revoke the operator's session id -- not found, not forbidden
        r = c.delete(f"/api/v1/auth/sessions/{op_sid}", headers=h, cookies={"pp_session": admin_raw})
        assert r.status_code == 404

        # the operator's session is untouched
        assert c.get("/api/v1/auth/me", cookies={"pp_session": op_raw}).status_code == 200


def test_expired_session_absent_from_list(tmp_path, csrf_header, bootstrap_admin):
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        h = csrf_header(c)
        admin_raw = c.cookies["pp_session"]

        raw2 = _login(c, h)

        with app.state.sessionmaker() as db:
            user = db.query(User).filter_by(email=ADMIN_EMAIL).one()
            row = db.query(SessionRow).filter_by(user_id=user.id, token_hash=_th(raw2)).one()
            row.expires_at = utcnow() - timedelta(hours=1)
            db.commit()

        rows = c.get("/api/v1/auth/sessions", cookies={"pp_session": admin_raw}).json()
        assert len(rows) == 1
        assert rows[0]["current"] is True  # the still-live admin_raw session, not the expired one
