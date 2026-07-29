"""Merged activity feed (doc 05 /cluster/activity, doc 06 ActivityFeed)."""
from fastapi.testclient import TestClient

from proxploy.models import AuditEvent, Job, utcnow


def test_activity_requires_a_session(tmp_path):
    from tests.support import make_app

    with TestClient(make_app(tmp_path)) as c:
        assert c.get("/api/v1/cluster/activity").status_code == 401


def test_feed_merges_jobs_and_audit_newest_first(tmp_path, csrf_header, bootstrap_admin):
    from tests.support import make_app

    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        with app.state.sessionmaker() as db:
            db.add(Job(kind="app.start", status="succeeded", target_type="app",
                       target_id=1))
            db.commit()
            db.add(AuditEvent(actor_type="user", actor_id=1, action="host.create",
                              target_type="host", target_id=1, ts=utcnow()))
            db.commit()
        rows = c.get("/api/v1/cluster/activity").json()
        assert {r["kind"] for r in rows} == {"job", "audit"}
        assert [r["title"] for r in rows][0] in ("host.create", "app.start")
        ats = [r["at"] for r in rows]
        assert ats == sorted(ats, reverse=True)


def test_audit_rows_that_spawned_a_job_are_not_duplicated(tmp_path, csrf_header,
                                                          bootstrap_admin):
    from tests.support import make_app

    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        with app.state.sessionmaker() as db:
            job = Job(kind="app.stop", status="running", target_type="app", target_id=3)
            db.add(job)
            db.commit()
            db.add(AuditEvent(actor_type="user", actor_id=1, action="app.stop",
                              target_type="app", target_id=3, job_id=job.id,
                              ts=utcnow()))
            db.commit()
        rows = c.get("/api/v1/cluster/activity").json()
        # bootstrap_admin itself writes user.create/auth.login audit rows (no
        # job_id), so the feed legitimately has more than this one entry --
        # the invariant under test is that app.stop appears exactly once (as
        # the job), not that the feed is empty otherwise.
        job_rows = [r for r in rows if r["kind"] == "job"]
        assert len(job_rows) == 1 and job_rows[0]["status"] == "running"
        assert not any(r["kind"] == "audit" and r["title"] == "app.stop" for r in rows)


def test_limit_is_honoured_and_capped(tmp_path, csrf_header, bootstrap_admin):
    from tests.support import make_app

    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        with app.state.sessionmaker() as db:
            for i in range(30):
                db.add(Job(kind="app.start", status="succeeded", target_type="app",
                           target_id=i))
            db.commit()
        assert len(c.get("/api/v1/cluster/activity?limit=5").json()) == 5
        assert len(c.get("/api/v1/cluster/activity?limit=999").json()) <= 100


def test_actor_email_is_resolved_for_jobs(tmp_path, csrf_header, bootstrap_admin):
    from proxploy.models import User
    from tests.support import make_app

    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        with app.state.sessionmaker() as db:
            uid = db.query(User).one().id
            db.add(Job(kind="app.start", status="succeeded", target_type="app",
                       target_id=1, requested_by=uid))
            db.commit()
        assert c.get("/api/v1/cluster/activity").json()[0]["actor"] == "admin@example.com"
