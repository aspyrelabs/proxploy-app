def test_audit_requires_admin(client, csrf_header):
    assert client.get("/api/v1/audit").status_code == 401


def test_audit_lists_login_events(client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    r = client.get("/api/v1/audit", params={"action": "auth.login"})
    assert r.status_code == 200
    events = r.json()
    assert any(e["action"] == "auth.login" and e["result"] == "ok" for e in events)
    assert "X-Total-Count" in r.headers
    # user.create was audited too (wiring proof for state-changing routes)
    r2 = client.get("/api/v1/audit", params={"action": "user.create"})
    assert len(r2.json()) == 1
