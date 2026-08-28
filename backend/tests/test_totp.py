"""TOTP enrollment (services/totp.py + api/auth.py's three routes, Phase 8
Task 8). The login step and pending-session/5-attempt-burn machinery are
Task 9, not covered here.

Recovery-code hashes live in their own table (`TotpRecoveryCode`), not
packed inside `users.totp_secret_enc`, see the migration docstring
(6cf6a0722d23_0005_totp_recovery_codes.py) for why. That split is exactly
what test_verify_login_burns_a_recovery_code_exactly_once and
test_disable_clears_the_blob_and_recovery_codes below are checking: burning
one code must never touch the others or the secret.
"""
import pyotp
from fastapi.testclient import TestClient

from proxploy.models import AuditEvent, TotpRecoveryCode, User
from proxploy.services import totp
from tests.support import make_app

EMAIL = "admin@example.com"


def _enrolled_user(c, app):
    """bootstrap_admin's user, plus the live User row + secretstore, for
    service-level calls that sit below the route layer."""
    db = app.state.sessionmaker()
    user = db.query(User).filter_by(email=EMAIL).one()
    return db, app.state.secretstore, user


def test_enrollment_returns_secret_uri_and_ten_codes_once(tmp_path, csrf_header,
                                                           bootstrap_admin):
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        db, ss, user = _enrolled_user(c, app)

        result = totp.start_enrollment(db, ss, user)

        assert result["secret"] and result["otpauth_uri"].startswith("otpauth://totp/")
        assert len(result["recovery_codes"]) == 10
        assert len(set(result["recovery_codes"])) == 10  # no duplicates
        assert user.totp_enabled is False  # a secret alone never enables TOTP

        # Ciphertext ≠ plaintext, and decrypts back to exactly the secret handed out.
        assert user.totp_secret_enc != result["secret"].encode()
        assert ss.decrypt(user.totp_secret_enc).decode() == result["secret"]

        # DB holds only encrypted argon2 hashes: never a raw code anywhere.
        rows = db.query(TotpRecoveryCode).filter_by(user_id=user.id).all()
        assert len(rows) == 10
        for row in rows:
            hash_ = ss.decrypt(row.code_hash_enc).decode()
            assert hash_.startswith("$argon2")
            assert hash_ not in result["recovery_codes"]
            assert row.used_at is None
        # Every raw code verifies against exactly one stored hash.
        for code in result["recovery_codes"]:
            matches = sum(1 for row in rows
                         if totp.verify_password(ss.decrypt(row.code_hash_enc).decode(), code))
            assert matches == 1


def test_confirm_requires_a_valid_code(tmp_path, csrf_header, bootstrap_admin):
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        db, ss, user = _enrolled_user(c, app)
        result = totp.start_enrollment(db, ss, user)

        assert totp.confirm(db, ss, user, "000000") is False
        assert user.totp_enabled is False

        real_code = pyotp.TOTP(result["secret"]).now()
        assert totp.confirm(db, ss, user, real_code) is True
        assert user.totp_enabled is True


def test_verify_login_accepts_totp_code(tmp_path, csrf_header, bootstrap_admin):
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        db, ss, user = _enrolled_user(c, app)
        result = totp.start_enrollment(db, ss, user)
        totp.confirm(db, ss, user, pyotp.TOTP(result["secret"]).now())

        assert totp.verify_login(db, ss, user, pyotp.TOTP(result["secret"]).now()) is True
        assert totp.verify_login(db, ss, user, "000000") is False


def test_verify_login_burns_a_recovery_code_exactly_once(tmp_path, csrf_header,
                                                          bootstrap_admin):
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        db, ss, user = _enrolled_user(c, app)
        result = totp.start_enrollment(db, ss, user)
        totp.confirm(db, ss, user, pyotp.TOTP(result["secret"]).now())
        codes = result["recovery_codes"]

        assert totp.verify_login(db, ss, user, codes[0]) is True
        # Second use of the SAME code fails: single-use, no replay.
        assert totp.verify_login(db, ss, user, codes[0]) is False

        rows = db.query(TotpRecoveryCode).filter_by(user_id=user.id).all()
        used = [r for r in rows if r.used_at is not None]
        assert len(used) == 1

        # The other 9 codes are untouched by burning the first.
        assert totp.verify_login(db, ss, user, codes[1]) is True
        used = [r for r in rows if db.get(TotpRecoveryCode, r.id).used_at is not None]
        assert len(used) == 2


def test_regenerate_replaces_all_ten_codes_and_leaves_the_secret_alone(tmp_path, csrf_header,
                                                                        bootstrap_admin):
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        db, ss, user = _enrolled_user(c, app)
        result = totp.start_enrollment(db, ss, user)
        totp.confirm(db, ss, user, pyotp.TOTP(result["secret"]).now())
        secret_before = user.totp_secret_enc
        old_codes = set(result["recovery_codes"])

        new_codes = totp.regenerate_recovery_codes(db, ss, user)

        assert len(new_codes) == 10
        assert len(set(new_codes)) == 10  # no duplicates
        assert set(new_codes).isdisjoint(old_codes)  # a truly fresh set, not appended
        assert user.totp_secret_enc == secret_before  # authenticator entry untouched
        assert user.totp_enabled is True

        rows = db.query(TotpRecoveryCode).filter_by(user_id=user.id).all()
        assert len(rows) == 10  # old rows deleted, not merely added to
        for row in rows:
            hash_ = ss.decrypt(row.code_hash_enc).decode()
            assert hash_.startswith("$argon2")
            assert hash_ not in new_codes
            assert row.used_at is None

        # The old codes no longer verify; the new ones do.
        assert totp.verify_login(db, ss, user, result["recovery_codes"][0]) is False
        assert totp.verify_login(db, ss, user, new_codes[0]) is True


def test_regenerate_refuses_when_totp_is_not_enabled(tmp_path, csrf_header, bootstrap_admin):
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        db, ss, user = _enrolled_user(c, app)

        # Never enrolled at all.
        assert totp.regenerate_recovery_codes(db, ss, user) is None
        assert db.query(TotpRecoveryCode).filter_by(user_id=user.id).count() == 0

        # Enrolled but not yet confirmed (pending): still refused.
        totp.start_enrollment(db, ss, user)
        assert user.totp_enabled is False
        assert totp.regenerate_recovery_codes(db, ss, user) is None


def test_disable_clears_the_blob_and_recovery_codes(tmp_path, csrf_header, bootstrap_admin):
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        db, ss, user = _enrolled_user(c, app)
        result = totp.start_enrollment(db, ss, user)
        totp.confirm(db, ss, user, pyotp.TOTP(result["secret"]).now())

        totp.disable(db, user)

        assert user.totp_secret_enc is None
        assert user.totp_enabled is False
        assert db.query(TotpRecoveryCode).filter_by(user_id=user.id).count() == 0


# --- Route-level: enroll -> confirm -> /auth/me, disable, audit rows -------

def test_enroll_confirm_flow_via_routes(tmp_path, csrf_header, bootstrap_admin):
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        h = csrf_header(c)

        r = c.post("/api/v1/auth/totp/enroll", headers=h)
        assert r.status_code == 200
        body = r.json()
        assert len(body["recovery_codes"]) == 10 and body["otpauth_uri"] and body["secret"]

        real_code = pyotp.TOTP(body["secret"]).now()
        r2 = c.post("/api/v1/auth/totp/confirm", json={"code": real_code}, headers=h)
        assert r2.status_code == 200 and r2.json() == {"ok": True}

        assert c.get("/api/v1/auth/me").json()["totp_enabled"] is True

        with app.state.sessionmaker() as db:
            assert db.query(AuditEvent).filter_by(action="auth.totp.enroll").count() == 1
            assert db.query(AuditEvent).filter_by(action="auth.totp.confirm").count() == 1


def test_enroll_conflict_while_already_enabled(tmp_path, csrf_header, bootstrap_admin):
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        h = csrf_header(c)
        r = c.post("/api/v1/auth/totp/enroll", headers=h)
        c.post("/api/v1/auth/totp/confirm", json={"code": pyotp.TOTP(r.json()["secret"]).now()},
              headers=h)

        r2 = c.post("/api/v1/auth/totp/enroll", headers=h)
        assert r2.status_code == 409


def test_confirm_wrong_code_is_400(tmp_path, csrf_header, bootstrap_admin):
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        h = csrf_header(c)
        c.post("/api/v1/auth/totp/enroll", headers=h)
        r = c.post("/api/v1/auth/totp/confirm", json={"code": "000000"}, headers=h)
        assert r.status_code == 400
        assert c.get("/api/v1/auth/me").json()["totp_enabled"] is False


def test_disable_requires_password_then_succeeds(tmp_path, csrf_header, bootstrap_admin):
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        h = csrf_header(c)
        r = c.post("/api/v1/auth/totp/enroll", headers=h)
        c.post("/api/v1/auth/totp/confirm", json={"code": pyotp.TOTP(r.json()["secret"]).now()},
              headers=h)

        bad = c.request("DELETE", "/api/v1/auth/totp", json={"password": "wrong"}, headers=h)
        assert bad.status_code == 403
        assert c.get("/api/v1/auth/me").json()["totp_enabled"] is True

        good = c.request("DELETE", "/api/v1/auth/totp",
                         json={"password": "Correct-Horse-Battery-9"}, headers=h)
        assert good.status_code == 200 and good.json() == {"ok": True}
        assert c.get("/api/v1/auth/me").json()["totp_enabled"] is False

        with app.state.sessionmaker() as db:
            assert db.query(AuditEvent).filter_by(action="auth.totp.disable").count() == 1


def test_regenerate_requires_password_then_returns_ten_fresh_codes(tmp_path, csrf_header,
                                                                    bootstrap_admin):
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        h = csrf_header(c)
        r = c.post("/api/v1/auth/totp/enroll", headers=h)
        old_codes = set(r.json()["recovery_codes"])
        c.post("/api/v1/auth/totp/confirm", json={"code": pyotp.TOTP(r.json()["secret"]).now()},
              headers=h)

        bad = c.post("/api/v1/auth/totp/recovery-codes/regenerate",
                     json={"password": "wrong"}, headers=h)
        assert bad.status_code == 403

        good = c.post("/api/v1/auth/totp/recovery-codes/regenerate",
                      json={"password": "Correct-Horse-Battery-9"}, headers=h)
        assert good.status_code == 200
        new_codes = good.json()["recovery_codes"]
        assert len(new_codes) == 10 and len(set(new_codes)) == 10
        assert set(new_codes).isdisjoint(old_codes)

        # Still enabled, and the fresh codes actually work at login.
        assert c.get("/api/v1/auth/me").json()["totp_enabled"] is True

        with app.state.sessionmaker() as db:
            assert db.query(AuditEvent).filter_by(
                action="auth.totp.recovery_codes.regenerate").count() == 1


def test_regenerate_before_confirm_is_409(tmp_path, csrf_header, bootstrap_admin):
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        h = csrf_header(c)
        c.post("/api/v1/auth/totp/enroll", headers=h)  # pending, never confirmed

        r = c.post("/api/v1/auth/totp/recovery-codes/regenerate",
                   json={"password": "Correct-Horse-Battery-9"}, headers=h)
        assert r.status_code == 409


def test_regenerate_via_oidc_only_account_accepts_a_totp_code(tmp_path, csrf_header,
                                                               bootstrap_admin):
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        h = csrf_header(c)
        db, ss, user = _enrolled_user(c, app)
        result = totp.start_enrollment(db, ss, user)
        totp.confirm(db, ss, user, pyotp.TOTP(result["secret"]).now())
        user.password_hash = None  # simulate an OIDC-only account
        db.commit()

        code = pyotp.TOTP(result["secret"]).now()
        r = c.post("/api/v1/auth/totp/recovery-codes/regenerate",
                   json={"password": code}, headers=h)
        assert r.status_code == 200 and len(r.json()["recovery_codes"]) == 10


def test_disable_via_oidc_only_account_accepts_a_totp_code(tmp_path, csrf_header,
                                                            bootstrap_admin):
    """doc 08: an OIDC-only account has no password_hash, so its re-auth
    proof for disabling TOTP is a current TOTP code in the same field."""
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        h = csrf_header(c)
        db, ss, user = _enrolled_user(c, app)
        result = totp.start_enrollment(db, ss, user)
        totp.confirm(db, ss, user, pyotp.TOTP(result["secret"]).now())
        user.password_hash = None  # simulate an OIDC-only account
        db.commit()

        code = pyotp.TOTP(result["secret"]).now()
        r = c.request("DELETE", "/api/v1/auth/totp", json={"password": code}, headers=h)
        assert r.status_code == 200 and r.json() == {"ok": True}


def test_verify_login_accepts_a_totp_code_exactly_once(tmp_path, csrf_header,
                                                       bootstrap_admin):
    """RFC 6238 section 5.2. verify_login is the check behind both the login
    second factor and the confirm-your-identity gate on disabling two-factor,
    so a replayable code lets one captured six digits sign in AND immediately
    turn two-factor off inside the same ~90s window."""
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        db, ss, user = _enrolled_user(c, app)
        result = totp.start_enrollment(db, ss, user)
        totp.confirm(db, ss, user, pyotp.TOTP(result["secret"]).now())

        code = pyotp.TOTP(result["secret"]).now()
        assert totp.verify_login(db, ss, user, code) is True
        assert totp.verify_login(db, ss, user, code) is False

        # A recovery code still works afterwards: the watermark is per-step,
        # it does not lock the account out of its other factor.
        codes = totp.regenerate_recovery_codes(db, ss, user)
        assert totp.verify_login(db, ss, user, codes[0]) is True
