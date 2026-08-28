def test_first_user_bootstrap_then_login_me_logout(client, csrf_header):
    # first user: unauthenticated create allowed, becomes owner
    r = client.post("/api/v1/users", json={
        "email": "admin@example.com", "password": "Correct-Horse-Battery-9",
        "display_name": "Admin"}, headers=csrf_header(client))
    assert r.status_code == 201
    assert r.json()["role"] == "owner"

    # second unauthenticated create is rejected
    r = client.post("/api/v1/users", json={
        "email": "x@example.com", "password": "Correct-Horse-Battery-9"},
        headers=csrf_header(client))
    assert r.status_code == 401

    r = client.post("/api/v1/auth/login", json={
        "email": "admin@example.com", "password": "Correct-Horse-Battery-9"},
        headers=csrf_header(client))
    assert r.status_code == 200

    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == "admin@example.com"
    assert me.json()["role"] == "owner"

    assert client.post("/api/v1/auth/logout", headers=csrf_header(client)).status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 401


def test_bad_password_rejected_and_audited(client, csrf_header):
    from proxploy.models import AuditEvent

    client.post("/api/v1/users", json={
        "email": "a@example.com", "password": "Correct-Horse-Battery-9"},
        headers=csrf_header(client))
    r = client.post("/api/v1/auth/login", json={
        "email": "a@example.com", "password": "wrong-wrong-wrong"},
        headers=csrf_header(client))
    assert r.status_code == 401

    db = client.app.state.sessionmaker()
    row = db.query(AuditEvent).filter_by(action="auth.login", result="error").one()
    assert row.result == "error"


def test_login_hashes_even_when_the_email_is_unknown(client, csrf_header, monkeypatch):
    """Login must not answer faster for an address that does not exist.

    Asserting on the code path, never on the clock: a wall-clock comparison
    of one argon2 run against none flakes on a loaded CI box. Counting the
    verifications is the same property without the timer. Three logins that
    all fail for different reasons must all do exactly one verification: an
    unknown email, a real account with a wrong password, and an account with
    no password at all (OIDC-only).
    """
    from proxploy.models import User
    from proxploy.services import authn

    client.post("/api/v1/users", json={
        "email": "real@example.com", "password": "Correct-Horse-Battery-9"},
        headers=csrf_header(client))
    db = client.app.state.sessionmaker()
    db.add(User(email="sso@example.com", password_hash=None))
    db.commit()

    calls = []
    real = authn.verify_password
    monkeypatch.setattr(authn, "verify_password",
                        lambda h, pw: (calls.append(h), real(h, pw))[1])

    for email in ("nobody@example.com", "real@example.com", "sso@example.com"):
        r = client.post("/api/v1/auth/login",
                        json={"email": email, "password": "wrong-wrong-wrong"},
                        headers=csrf_header(client))
        assert r.status_code == 401
        assert r.json()["detail"] == "invalid credentials"  # one body for all three

    assert len(calls) == 3, "every failed login must cost one password verification"
    # The two accountless cases verify against the shared dummy, so the work
    # done is the same as for a real account, not a skipped hash.
    assert calls[0] == authn.DUMMY_HASH and calls[2] == authn.DUMMY_HASH
    assert calls[1] != authn.DUMMY_HASH


def test_csrf_required_for_mutations(client):
    r = client.post("/api/v1/users", json={
        "email": "b@example.com", "password": "Correct-Horse-Battery-9"})
    assert r.status_code == 403  # no X-CSRF-Token header


def test_login_rate_limited(client, csrf_header):
    for _ in range(10):
        client.post("/api/v1/auth/login", json={
            "email": "nobody@example.com", "password": "Nope-Nope-Nope-9"},
            headers=csrf_header(client))
    r = client.post("/api/v1/auth/login", json={
        "email": "nobody@example.com", "password": "Nope-Nope-Nope-9"},
        headers=csrf_header(client))
    assert r.status_code == 429
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["status"] == 429


def test_admin_creates_user(client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    r = client.post("/api/v1/users", json={
        "email": "op@example.com", "password": "Correct-Horse-Battery-9",
        "role": "operator"}, headers=csrf_header(client))
    assert r.status_code == 201 and r.json()["role"] == "operator"
