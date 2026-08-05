"""TOTP login step (Task 9): password login for a totp_enabled user parks a
pending token instead of setting a session cookie; POST /auth/totp completes
(or burns) it. Enrollment itself (services/totp.py + the enroll/confirm/
disable routes) is Task 8 -- see test_totp.py.
"""
import pyotp
from fastapi.testclient import TestClient

from proxploy.models import AuditEvent, User
from proxploy.services import totp
from tests.support import make_app

EMAIL = "admin@example.com"
PASSWORD = "correct-horse-battery"


def _enable_totp(app):
    """bootstrap_admin's user, enrolled + confirmed. Returns start_enrollment's
    result dict (secret, otpauth_uri, recovery_codes) for the tests below."""
    db = app.state.sessionmaker()
    user = db.query(User).filter_by(email=EMAIL).one()
    ss = app.state.secretstore
    result = totp.start_enrollment(db, ss, user)
    totp.confirm(db, ss, user, pyotp.TOTP(result["secret"]).now())
    return result


def _password_login(c, h):
    """Password step only. bootstrap_admin already logged the client's jar in
    with a pre-TOTP cookie -- callers clear the jar first so a stray old
    cookie can't masquerade as evidence this response set one."""
    r = c.post("/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD}, headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["totp_required"] is True
    assert "pending" in body and body["pending"]
    assert "pp_session" not in r.cookies  # this response never sets a session cookie
    return body["pending"]


def test_password_login_with_totp_enabled_returns_pending_no_cookie(tmp_path, csrf_header,
                                                                     bootstrap_admin):
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        h = csrf_header(c)
        c.cookies.delete("pp_session")
        _enable_totp(app)

        _password_login(c, h)
        assert "pp_session" not in c.cookies

        with app.state.sessionmaker() as db:
            assert db.query(AuditEvent).filter_by(action="auth.login.totp_pending").count() == 1


def test_wrong_code_is_401_and_sets_no_cookie(tmp_path, csrf_header, bootstrap_admin):
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        h = csrf_header(c)
        c.cookies.delete("pp_session")
        _enable_totp(app)
        pending = _password_login(c, h)

        r = c.post("/api/v1/auth/totp", json={"pending": pending, "code": "000000"}, headers=h)
        assert r.status_code == 401
        assert "pp_session" not in r.cookies
        assert "pp_session" not in c.cookies

        with app.state.sessionmaker() as db:
            row = db.query(AuditEvent).filter_by(action="auth.login", result="error").one()
            assert row.result == "error"


def test_right_code_completes_login(tmp_path, csrf_header, bootstrap_admin):
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        h = csrf_header(c)
        c.cookies.delete("pp_session")
        result = _enable_totp(app)
        pending = _password_login(c, h)

        code = pyotp.TOTP(result["secret"]).now()
        r = c.post("/api/v1/auth/totp", json={"pending": pending, "code": code}, headers=h)
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["user"]["email"] == EMAIL
        assert "pp_session" in r.cookies
        assert "pp_session" in c.cookies

        assert c.get("/api/v1/auth/me").status_code == 200

        with app.state.sessionmaker() as db:
            assert db.query(AuditEvent).filter_by(action="auth.login", result="ok").count() >= 1


def test_recovery_code_completes_login_and_is_burned(tmp_path, csrf_header, bootstrap_admin):
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        h = csrf_header(c)
        c.cookies.delete("pp_session")
        result = _enable_totp(app)
        recovery_code = result["recovery_codes"][0]

        pending = _password_login(c, h)
        r = c.post("/api/v1/auth/totp", json={"pending": pending, "code": recovery_code}, headers=h)
        assert r.status_code == 200
        assert "pp_session" in r.cookies

        # the recovery code is now burned: a brand-new login can't complete with it again
        c.cookies.delete("pp_session")
        pending2 = _password_login(c, h)
        r2 = c.post("/api/v1/auth/totp", json={"pending": pending2, "code": recovery_code}, headers=h)
        assert r2.status_code == 401
        assert "pp_session" not in r2.cookies


def test_pending_token_is_single_use(tmp_path, csrf_header, bootstrap_admin):
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        h = csrf_header(c)
        c.cookies.delete("pp_session")
        result = _enable_totp(app)
        pending = _password_login(c, h)
        code = pyotp.TOTP(result["secret"]).now()

        r = c.post("/api/v1/auth/totp", json={"pending": pending, "code": code}, headers=h)
        assert r.status_code == 200

        # reuse of the same (now-consumed) pending token, even with a fresh valid code, fails
        c.cookies.delete("pp_session")
        code2 = pyotp.TOTP(result["secret"]).now()
        r2 = c.post("/api/v1/auth/totp", json={"pending": pending, "code": code2}, headers=h)
        assert r2.status_code == 401
        assert "pp_session" not in r2.cookies


def test_sixth_attempt_burns_the_entry_even_with_the_right_code(tmp_path, csrf_header,
                                                                 bootstrap_admin):
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        h = csrf_header(c)
        c.cookies.delete("pp_session")
        result = _enable_totp(app)
        pending = _password_login(c, h)

        for _ in range(5):  # PENDING_MAX_ATTEMPTS
            r = c.post("/api/v1/auth/totp", json={"pending": pending, "code": "000000"}, headers=h)
            assert r.status_code == 401

        code = pyotp.TOTP(result["secret"]).now()
        r = c.post("/api/v1/auth/totp", json={"pending": pending, "code": code}, headers=h)
        assert r.status_code == 401  # entry was discarded on the 5th wrong attempt
        assert "pp_session" not in r.cookies


def test_expired_pending_is_401(tmp_path, csrf_header, bootstrap_admin):
    app = make_app(tmp_path, totp_pending_ttl_s=0.0)
    with TestClient(app) as c:
        bootstrap_admin(c)
        h = csrf_header(c)
        c.cookies.delete("pp_session")
        result = _enable_totp(app)
        pending = _password_login(c, h)

        code = pyotp.TOTP(result["secret"]).now()
        r = c.post("/api/v1/auth/totp", json={"pending": pending, "code": code}, headers=h)
        assert r.status_code == 401
        assert "pp_session" not in r.cookies
