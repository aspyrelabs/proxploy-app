def test_first_user_bootstrap_then_login_me_logout(client, csrf_header):
    # first user: unauthenticated create allowed, becomes owner
    r = client.post("/api/v1/users", json={
        "email": "admin@example.com", "password": "correct-horse-battery",
        "display_name": "Admin"}, headers=csrf_header(client))
    assert r.status_code == 201
    assert r.json()["role"] == "owner"

    # second unauthenticated create is rejected
    r = client.post("/api/v1/users", json={
        "email": "x@example.com", "password": "correct-horse-battery"},
        headers=csrf_header(client))
    assert r.status_code == 401

    r = client.post("/api/v1/auth/login", json={
        "email": "admin@example.com", "password": "correct-horse-battery"},
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
        "email": "a@example.com", "password": "correct-horse-battery"},
        headers=csrf_header(client))
    r = client.post("/api/v1/auth/login", json={
        "email": "a@example.com", "password": "wrong-wrong-wrong"},
        headers=csrf_header(client))
    assert r.status_code == 401

    db = client.app.state.sessionmaker()
    row = db.query(AuditEvent).filter_by(action="auth.login", result="error").one()
    assert row.result == "error"


def test_csrf_required_for_mutations(client):
    r = client.post("/api/v1/users", json={
        "email": "b@example.com", "password": "correct-horse-battery"})
    assert r.status_code == 403  # no X-CSRF-Token header


def test_login_rate_limited(client, csrf_header):
    for _ in range(10):
        client.post("/api/v1/auth/login", json={
            "email": "nobody@example.com", "password": "nope-nope-nope"},
            headers=csrf_header(client))
    r = client.post("/api/v1/auth/login", json={
        "email": "nobody@example.com", "password": "nope-nope-nope"},
        headers=csrf_header(client))
    assert r.status_code == 429
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["status"] == 429


def test_admin_creates_user(client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    r = client.post("/api/v1/users", json={
        "email": "op@example.com", "password": "correct-horse-battery",
        "role": "operator"}, headers=csrf_header(client))
    assert r.status_code == 201 and r.json()["role"] == "operator"
