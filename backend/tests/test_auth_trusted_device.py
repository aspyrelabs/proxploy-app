"""Remember this device for 30 days: a browser that already proved the second
factor can skip the code step until the trust expires or is revoked.

The credential under test BYPASSES two-factor, so most of this file is about
the ways it must stop working rather than the way it works.
"""
import pyotp
from fastapi.testclient import TestClient

from proxploy.models import AuditEvent, TrustedDevice, User, utcnow
from proxploy.services import totp
from tests.support import make_app

EMAIL = "admin@example.com"
PASSWORD = "correct-horse-battery"
COOKIE = "pp_trusted"


def _enable_totp(app):
    db = app.state.sessionmaker()
    user = db.query(User).filter_by(email=EMAIL).one()
    ss = app.state.secretstore
    result = totp.start_enrollment(db, ss, user)
    totp.confirm(db, ss, user, pyotp.TOTP(result["secret"]).now())
    return result


def _login_with_code(c, h, secret, *, remember):
    """Full two-step login. Returns the /auth/totp response."""
    c.cookies.delete("pp_session")
    r = c.post("/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD}, headers=h)
    assert r.json().get("totp_required") is True, r.text
    return c.post("/api/v1/auth/totp", headers=h, json={
        "pending": r.json()["pending"], "code": pyotp.TOTP(secret).now(),
        "remember": remember})


def _password_only(c, h):
    c.cookies.delete("pp_session")
    return c.post("/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD},
                  headers=h)


def test_remembering_a_device_lets_the_next_login_skip_the_code(tmp_path, csrf_header,
                                                                bootstrap_admin):
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        h = csrf_header(c)
        secret = _enable_totp(app)["secret"]

        assert _login_with_code(c, h, secret, remember=True).status_code == 200
        assert COOKIE in c.cookies

        # Second login, same browser: password only, no code asked for.
        r = _password_only(c, h)
        assert r.status_code == 200
        body = r.json()
        assert body.get("totp_required") is not True, body
        assert body["ok"] is True
        assert "pp_session" in c.cookies


def test_the_skipped_second_factor_is_audited(tmp_path, csrf_header, bootstrap_admin):
    """A 2FA bypass that leaves no trace is not one worth shipping."""
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        h = csrf_header(c)
        secret = _enable_totp(app)["secret"]
        _login_with_code(c, h, secret, remember=True)
        _password_only(c, h)

        with app.state.sessionmaker() as db:
            rows = [a for a in db.query(AuditEvent).filter_by(action="auth.login").all()
                    if (a.params or {}).get("via") == "trusted_device"]
            assert len(rows) == 1


def test_not_ticking_the_box_mints_nothing(tmp_path, csrf_header, bootstrap_admin):
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        h = csrf_header(c)
        secret = _enable_totp(app)["secret"]
        _login_with_code(c, h, secret, remember=False)

        assert COOKIE not in c.cookies
        with app.state.sessionmaker() as db:
            assert db.query(TrustedDevice).count() == 0
        assert _password_only(c, h).json().get("totp_required") is True


def test_a_device_trusted_for_one_account_cannot_skip_another_users_code(
        tmp_path, csrf_header, bootstrap_admin):
    """The whole reason the row carries user_id."""
    from proxploy.services.authn import hash_password

    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        h = csrf_header(c)
        secret = _enable_totp(app)["secret"]
        _login_with_code(c, h, secret, remember=True)
        assert COOKIE in c.cookies

        with app.state.sessionmaker() as db:
            other = User(email="other@example.com", password_hash=hash_password(PASSWORD),
                         is_active=True)
            db.add(other)
            db.commit()
            totp.confirm(db, app.state.secretstore, other,
                         pyotp.TOTP(totp.start_enrollment(
                             db, app.state.secretstore, other)["secret"]).now())

        c.cookies.delete("pp_session")
        r = c.post("/api/v1/auth/login", headers=h,
                   json={"email": "other@example.com", "password": PASSWORD})
        assert r.json().get("totp_required") is True, "another user's trust was honoured"


def test_an_expired_trust_asks_for_the_code_again(tmp_path, csrf_header, bootstrap_admin):
    from datetime import timedelta

    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        h = csrf_header(c)
        secret = _enable_totp(app)["secret"]
        _login_with_code(c, h, secret, remember=True)

        with app.state.sessionmaker() as db:
            row = db.query(TrustedDevice).one()
            row.expires_at = utcnow() - timedelta(seconds=1)
            db.commit()

        assert _password_only(c, h).json().get("totp_required") is True


def test_revoking_a_device_asks_for_the_code_again(tmp_path, csrf_header, bootstrap_admin):
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        h = csrf_header(c)
        secret = _enable_totp(app)["secret"]
        _login_with_code(c, h, secret, remember=True)

        listed = c.get("/api/v1/auth/trusted-devices").json()
        assert len(listed) == 1 and "token_hash" not in listed[0]
        assert c.delete(f"/api/v1/auth/trusted-devices/{listed[0]['id']}",
                        headers=h).status_code == 200

        assert _password_only(c, h).json().get("totp_required") is True


def test_disabling_two_factor_drops_every_trusted_device(tmp_path, csrf_header,
                                                         bootstrap_admin):
    """The trust was in the old factor. Re-enrolling later must not inherit it."""
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        h = csrf_header(c)
        secret = _enable_totp(app)["secret"]
        _login_with_code(c, h, secret, remember=True)

        r = c.request("DELETE", "/api/v1/auth/totp", headers=h,
                      json={"password": PASSWORD})
        assert r.status_code == 200, r.text
        with app.state.sessionmaker() as db:
            assert db.query(TrustedDevice).filter(
                TrustedDevice.revoked_at.is_(None)).count() == 0


def test_spending_a_recovery_code_drops_every_trusted_device(tmp_path, csrf_header,
                                                             bootstrap_admin):
    """That is the "I lost my authenticator" path. A device still trusted from
    before the loss defeats the point of recovering at all."""
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        h = csrf_header(c)
        enrolled = _enable_totp(app)
        _login_with_code(c, h, enrolled["secret"], remember=True)

        c.cookies.delete("pp_session")
        r = c.post("/api/v1/auth/login", headers=h,
                   json={"email": EMAIL, "password": PASSWORD})
        # the trusted cookie is present, so force the code path by revoking it
        # is NOT what we want here: a recovery code can only be spent when the
        # code step actually runs, which it does for a device we have not
        # trusted. Use a fresh client instead.
        assert r.status_code == 200

    with TestClient(app) as c2:
        h2 = csrf_header(c2)
        r = c2.post("/api/v1/auth/login", headers=h2,
                    json={"email": EMAIL, "password": PASSWORD})
        assert r.json().get("totp_required") is True
        r = c2.post("/api/v1/auth/totp", headers=h2, json={
            "pending": r.json()["pending"], "code": enrolled["recovery_codes"][0]})
        assert r.status_code == 200, r.text

    with app.state.sessionmaker() as db:
        assert db.query(TrustedDevice).filter(
            TrustedDevice.revoked_at.is_(None)).count() == 0


def test_a_password_reset_drops_every_trusted_device(tmp_path, csrf_header,
                                                     bootstrap_admin):
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        h = csrf_header(c)
        secret = _enable_totp(app)["secret"]
        _login_with_code(c, h, secret, remember=True)

        with app.state.sessionmaker() as db:
            uid = db.query(User).filter_by(email=EMAIL).one().id
        r = c.post(f"/api/v1/users/{uid}/password", headers=h,
                   json={"password": "a-different-correct-horse"})
        assert r.status_code == 200, r.text
        with app.state.sessionmaker() as db:
            assert db.query(TrustedDevice).filter(
                TrustedDevice.revoked_at.is_(None)).count() == 0
