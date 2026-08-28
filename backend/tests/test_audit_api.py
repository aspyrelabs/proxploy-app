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


# --- what the screen reads (Date, User, Action, Item, Result, IP) -----------

def test_rows_name_the_person_and_the_item(client, csrf_header, bootstrap_admin):
    """The viewer used to render `${actor_type} #${actor_id}` and
    `${target_type} #${target_id}`, so every row read "user #1 did host.sync to
    host #2". Resolved here rather than in the browser, the same way
    api/alerts.py joins `target_label`/`acked_by_email`: the frontend has no way
    to turn an id into a name without a second fetch per row.
    """
    bootstrap_admin(client)
    from tests.support import seed_host_row

    from proxploy.models import AuditEvent
    with client.app.state.sessionmaker() as db:
        h = seed_host_row(db, name="pve-lab-01")
        db.add(AuditEvent(actor_type="user", actor_id=1, action="host.sync",
                          target_type="host", target_id=h.id))
        db.commit()

    rows = client.get("/api/v1/audit", params={"action": "host.sync"}).json()
    assert [r["actor_label"] for r in rows] == ["Admin"]
    assert [r["target_label"] for r in rows] == ["pve-lab-01"]
    # The stored values stay on the row: the filters, the export and the CLI
    # all still speak them.
    assert rows[0]["actor_id"] == 1 and rows[0]["target_type"] == "host"


def test_a_row_survives_the_item_it_names_being_deleted(client, csrf_header,
                                                        bootstrap_admin):
    """An audit log that goes blank when you remove a host is worse than one
    that shows an id: the removal is exactly the event someone came to read.
    """
    bootstrap_admin(client)
    from tests.support import seed_host_row

    from proxploy.models import AuditEvent, Host
    with client.app.state.sessionmaker() as db:
        h = seed_host_row(db, name="doomed-01")
        hid = h.id
        db.add(AuditEvent(actor_type="user", actor_id=1, action="host.remove",
                          target_type="host", target_id=hid))
        db.commit()
        db.delete(db.get(Host, hid))
        db.commit()

    rows = client.get("/api/v1/audit", params={"action": "host.remove"}).json()
    assert len(rows) == 1, "the row must still be listed"
    assert rows[0]["target_label"] is None, "no name to give, and it says so"
    assert rows[0]["target_type"] == "host" and rows[0]["target_id"] == hid


def test_a_non_user_actor_is_not_given_a_person_name(client, csrf_header,
                                                     bootstrap_admin):
    """Schedules and API keys write audit rows too. Labelling a system row with
    a person would be a false attribution on the compliance surface."""
    bootstrap_admin(client)
    from proxploy.models import AuditEvent
    with client.app.state.sessionmaker() as db:
        db.add(AuditEvent(actor_type="system", action="metrics.maintain"))
        db.commit()

    rows = client.get("/api/v1/audit", params={"action": "metrics.maintain"}).json()
    assert rows[0]["actor_type"] == "system"
    assert rows[0]["actor_label"] is None


def test_item_or_action_search_matches_either_half(client, csrf_header,
                                                   bootstrap_admin):
    """One box on the screen, so it matches the action OR the item, and it
    matches substrings: typing "pve-lab" and getting nothing because no action
    is literally named that would read as a broken filter."""
    bootstrap_admin(client)
    from tests.support import seed_host_row

    from proxploy.models import AuditEvent
    with client.app.state.sessionmaker() as db:
        h = seed_host_row(db, name="pve-lab-01")
        db.add(AuditEvent(actor_type="user", actor_id=1, action="host.sync",
                          target_type="host", target_id=h.id))
        db.add(AuditEvent(actor_type="user", actor_id=1, action="app.uninstall",
                          target_type="app", target_id=77))
        db.commit()

    by_item = client.get("/api/v1/audit", params={"search": "pve-lab"}).json()
    assert [r["action"] for r in by_item] == ["host.sync"]
    by_action = client.get("/api/v1/audit", params={"search": "uninstall"}).json()
    assert [r["action"] for r in by_action] == ["app.uninstall"]
    # Substring, not exact.
    assert client.get("/api/v1/audit", params={"search": "PVE-LAB-01"}).json(), \
        "case must not decide whether a filter finds anything"


def test_performed_by_can_ask_for_rows_no_person_wrote(client, csrf_header,
                                                       bootstrap_admin):
    """The old filter was a raw actor_id box, which cannot express "the
    scheduler did this": every system row has actor_id NULL."""
    bootstrap_admin(client)
    from proxploy.models import AuditEvent
    with client.app.state.sessionmaker() as db:
        db.add(AuditEvent(actor_type="system", action="catalog.refresh"))
        db.commit()

    system = client.get("/api/v1/audit", params={"actor_type": "system"}).json()
    assert system and all(r["actor_type"] == "system" for r in system)
    mine = client.get("/api/v1/audit", params={"actor": 1}).json()
    assert mine and all(r["actor_id"] == 1 for r in mine)


def test_labelling_a_page_does_not_run_a_query_per_row(client, csrf_header,
                                                       bootstrap_admin):
    """50 rows resolved one at a time would be 50 extra queries per page turn.
    Lookups are batched per target kind, the way api/alerts.py::_lookups is."""
    bootstrap_admin(client)
    from sqlalchemy import event
    from tests.support import seed_host_row

    from proxploy.models import AuditEvent
    with client.app.state.sessionmaker() as db:
        h = seed_host_row(db, name="busy-01")
        for i in range(50):
            db.add(AuditEvent(actor_type="user", actor_id=1, action="app.start",
                              target_type="host", target_id=h.id))
        db.commit()

    seen: list[str] = []

    def count(conn, cursor, statement, *rest):
        if statement.lstrip().upper().startswith("SELECT"):
            seen.append(statement)

    engine = client.app.state.engine
    event.listen(engine, "before_cursor_execute", count)
    try:
        rows = client.get("/api/v1/audit",
                          params={"action": "app.start", "per_page": 50}).json()
    finally:
        event.remove(engine, "before_cursor_execute", count)

    assert len(rows) == 50
    assert len(seen) < 15, (f"{len(seen)} selects for one page of 50 rows; "
                            f"labels are being resolved per row")


# --- clearing the log (the row that says who did it) ------------------------

CLEAR_BODY = {"confirm": "clear audit log"}


def test_clearing_the_log_is_itself_audited_and_that_row_survives(client, csrf_header,
                                                                  bootstrap_admin):
    """The whole point: a log that can be silently emptied is not a log. The
    audit.clear row is written AFTER the delete, so it is not inside the range
    it describes."""
    bootstrap_admin(client)
    before_count = len(client.get("/api/v1/audit", params={"per_page": 200}).json())
    assert before_count > 0, "bootstrap wrote rows, so there is something to clear"

    r = client.request("DELETE", "/api/v1/audit", json=CLEAR_BODY,
                       headers=csrf_header(client))
    assert r.status_code == 200, r.text
    assert r.json()["deleted"] == before_count

    rows = client.get("/api/v1/audit", params={"per_page": 200}).json()
    assert len(rows) == 1, "exactly the record of the clear is left"
    assert rows[0]["action"] == "audit.clear"
    assert rows[0]["actor_type"] == "user" and rows[0]["actor_id"] == 1
    assert rows[0]["actor_label"] == "Admin", "who did it, by name"
    assert rows[0]["params"]["deleted"] == before_count
    assert rows[0]["params"]["scope"] == "all"
    assert rows[0]["result"] == "ok"


def test_clearing_older_than_a_date_keeps_the_newer_rows(client, csrf_header,
                                                         bootstrap_admin):
    """Retention is the real use, and it is far less destructive than emptying
    the table. The audit row has to say which of the two was used."""
    bootstrap_admin(client)
    from datetime import datetime

    from proxploy.models import AuditEvent
    with client.app.state.sessionmaker() as db:
        db.add(AuditEvent(actor_type="system", action="old.row",
                          ts=datetime(2020, 1, 1)))
        db.add(AuditEvent(actor_type="system", action="new.row",
                          ts=datetime(2030, 1, 1)))
        db.commit()

    r = client.request("DELETE", "/api/v1/audit",
                       json={**CLEAR_BODY, "before": "2025-01-01T00:00:00"},
                       headers=csrf_header(client))
    assert r.status_code == 200, r.text
    assert r.json()["deleted"] == 1

    actions = [x["action"] for x in
               client.get("/api/v1/audit", params={"per_page": 200}).json()]
    assert "old.row" not in actions
    assert "new.row" in actions
    clear = next(x for x in
                 client.get("/api/v1/audit", params={"action": "audit.clear"}).json())
    assert clear["params"]["scope"] == "before"
    assert clear["params"]["before"].startswith("2025-01-01")


def test_clearing_without_the_typed_phrase_deletes_nothing(client, csrf_header,
                                                           bootstrap_admin):
    """Same typed-confirmation shape as the app uninstall and the in-place
    restore (api/apps.py): a single click must not empty the trail."""
    bootstrap_admin(client)
    before = client.get("/api/v1/audit", params={"per_page": 200}).json()

    r = client.request("DELETE", "/api/v1/audit", json={},
                       headers=csrf_header(client))
    assert r.status_code == 409
    # main.py's problem_handler flattens a dict detail into RFC 9457
    # problem+json, so error/confirm_phrase land at the top level. Same shape
    # every other typed-confirmation guard answers with.
    body = r.json()
    assert body["error"] == "confirm_required"
    assert body["confirm_phrase"] == "clear audit log"

    after = client.get("/api/v1/audit", params={"per_page": 200}).json()
    assert len(after) == len(before) + 1, "nothing deleted, one denial recorded"
    denied = next(x for x in after if x["action"] == "audit.clear")
    assert denied["result"] == "denied"


def test_an_admin_who_is_not_an_owner_cannot_erase_the_trail(client, csrf_header,
                                                             bootstrap_admin):
    """("audit", "clear") sits at owner, beside host.remove and vm.remove. An
    admin can read and export the log; erasing it is a different question."""
    from fastapi.testclient import TestClient

    bootstrap_admin(client)
    client.post("/api/v1/users",
                json={"email": "admin2@example.com", "role": "admin",
                      "password": "Correct-Horse-Battery-9", "display_name": "Admin Two"},
                headers=csrf_header(client))
    c2 = TestClient(client.app)
    c2.post("/api/v1/auth/login",
            json={"email": "admin2@example.com", "password": "Correct-Horse-Battery-9"},
            headers=csrf_header(c2))
    assert c2.get("/api/v1/audit").status_code == 200, "reading is still allowed"
    r = c2.request("DELETE", "/api/v1/audit", json=CLEAR_BODY,
                   headers=csrf_header(c2))
    assert r.status_code == 403
    assert client.get("/api/v1/audit", params={"action": "auth.login"}).json(), \
        "the refused clear removed nothing"
