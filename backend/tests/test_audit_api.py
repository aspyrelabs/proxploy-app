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


def test_audit_paging_is_clamped(client, csrf_header, bootstrap_admin):
    """per_page went straight into LIMIT and page into OFFSET. A caller could
    pull the whole append-only table in one response, and page=0 asked SQLite
    for a negative offset. Same clamp the other paged reads use."""
    bootstrap_admin(client)
    from proxploy.api.audit import AUDIT_PAGE_MAX
    from proxploy.models import AuditEvent

    with client.app.state.sessionmaker() as db:
        for i in range(AUDIT_PAGE_MAX + 25):
            db.add(AuditEvent(actor_type="system", action="test.filler",
                              target_type="host", target_id=i, result="ok"))
        db.commit()
        total = db.query(AuditEvent).count()
    assert total > AUDIT_PAGE_MAX, "the clamp is only proven above the ceiling"

    r = client.get("/api/v1/audit", params={"per_page": 100000000})
    assert r.status_code == 200
    assert len(r.json()) == AUDIT_PAGE_MAX, "asking for everything gets one page"

    # page=0 used to produce OFFSET -50; it must behave as the first page.
    first = client.get("/api/v1/audit", params={"page": 1, "per_page": 5}).json()
    assert client.get("/api/v1/audit", params={"page": 0, "per_page": 5}).json() == first
