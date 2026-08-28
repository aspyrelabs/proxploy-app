"""Per-user persistence of the bell tray's dismissed job-backed notifications
(see components/BellPopover.tsx).

Self-service surface, same as api_keys/sessions: no team, no role, scoped by
user_id alone. These tests exercise the /notifications/dismissed endpoints
directly rather than through the UI; the frontend contract (optimistic
dismiss, revert-nothing-but-surface-the-error on a failed write) is covered
in frontend/src/components/BellPopover.test.tsx.
"""
from fastapi.testclient import TestClient

from proxploy.models import Job
from tests.support import make_app


def _seed_job(app, **kw):
    with app.state.sessionmaker() as db:
        job = Job(kind=kw.pop("kind", "app.start"), status=kw.pop("status", "succeeded"),
                  target_type="app", target_id=1, **kw)
        db.add(job)
        db.commit()
        return job.id


def _mk_user(client, csrf_header, email, password="Correct-Horse-Battery-9"):
    h = csrf_header(client)
    r = client.post("/api/v1/users", json={"email": email, "password": password},
                    headers=h)
    assert r.status_code == 201, r.text


def _login(client, csrf_header, email, password="Correct-Horse-Battery-9"):
    r = client.post("/api/v1/auth/login", json={"email": email, "password": password},
                    headers=csrf_header(client))
    assert r.status_code == 200, r.text


def test_read_and_write_require_a_session(tmp_path, csrf_header):
    with TestClient(make_app(tmp_path)) as c:
        h = csrf_header(c)   # a CSRF cookie/header alone, no login
        assert c.get("/api/v1/notifications/dismissed").status_code == 401
        assert c.post("/api/v1/notifications/dismissed/clear-all", headers=h).status_code == 401
        assert c.post("/api/v1/notifications/dismissed/1", headers=h).status_code == 401


def test_clear_all_then_refetch_leaves_the_tray_empty_not_repopulated(
        tmp_path, csrf_header, bootstrap_admin):
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        for _ in range(29):
            _seed_job(app)
        r = c.post("/api/v1/notifications/dismissed/clear-all", headers=csrf_header(c))
        assert r.status_code == 200
        state = c.get("/api/v1/notifications/dismissed").json()
        assert state["cleared_through_job_id"] == 29
        assert state["dismissed_job_ids"] == []
        # A second read ("refetch") must see the same cleared state, not the
        # 29 jobs coming back.
        state2 = c.get("/api/v1/notifications/dismissed").json()
        assert state2 == state


def test_dismissing_one_item_leaves_others_alone_and_survives_a_refetch(
        tmp_path, csrf_header, bootstrap_admin):
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        ids = [_seed_job(app) for _ in range(3)]
        r = c.post(f"/api/v1/notifications/dismissed/{ids[1]}", headers=csrf_header(c))
        assert r.status_code == 200
        state = c.get("/api/v1/notifications/dismissed").json()
        assert state["dismissed_job_ids"] == [ids[1]]
        assert state["cleared_through_job_id"] is None
        # Refetching does not reset it, and dismissing the same id again does
        # not duplicate it.
        c.post(f"/api/v1/notifications/dismissed/{ids[1]}", headers=csrf_header(c))
        state2 = c.get("/api/v1/notifications/dismissed").json()
        assert state2["dismissed_job_ids"] == [ids[1]]


def test_a_second_users_tray_is_unaffected_by_the_first_clearing_theirs(
        tmp_path, csrf_header, bootstrap_admin):
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        for _ in range(5):
            _seed_job(app)
        _mk_user(c, csrf_header, "second@x.io")
        r = c.post("/api/v1/notifications/dismissed/clear-all", headers=csrf_header(c))
        assert r.status_code == 200
        first_state = c.get("/api/v1/notifications/dismissed").json()
        assert first_state["cleared_through_job_id"] == 5

        c.post("/api/v1/auth/logout", headers=csrf_header(c))
        _login(c, csrf_header, "second@x.io")
        second_state = c.get("/api/v1/notifications/dismissed").json()
        assert second_state["cleared_through_job_id"] is None
        assert second_state["dismissed_job_ids"] == []


def test_a_job_created_after_clear_all_still_appears(tmp_path, csrf_header, bootstrap_admin):
    """The trap: a naive "hide everything that exists now" also hides
    everything that arrives later. The watermark must not do that, because
    a job created after the clear always gets a HIGHER id."""
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        for _ in range(3):
            _seed_job(app)
        c.post("/api/v1/notifications/dismissed/clear-all", headers=csrf_header(c))
        new_id = _seed_job(app)
        state = c.get("/api/v1/notifications/dismissed").json()
        assert new_id > state["cleared_through_job_id"]
        assert new_id not in state["dismissed_job_ids"]


def test_clear_all_prunes_individually_dismissed_ids_it_now_covers(
        tmp_path, csrf_header, bootstrap_admin):
    """Bounded storage: once the watermark covers an id, that id must not
    also linger in dismissed_job_ids forever."""
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        ids = [_seed_job(app) for _ in range(3)]
        c.post(f"/api/v1/notifications/dismissed/{ids[0]}", headers=csrf_header(c))
        c.post("/api/v1/notifications/dismissed/clear-all", headers=csrf_header(c))
        state = c.get("/api/v1/notifications/dismissed").json()
        assert state["dismissed_job_ids"] == []
        assert state["cleared_through_job_id"] == ids[-1]
