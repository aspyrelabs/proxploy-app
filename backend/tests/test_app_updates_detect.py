"""`apps.update_available` detection (doc 05 GET /apps/{id}, doc 06 badge).

community-scripts publishes no version numbers, so the only honest signal is
"the pinned commit is behind the catalog's current commit".
"""
from proxploy.models import App, AppScript, CatalogEntry, Host
from proxploy.services.appstore import mark_updates_available, pinned_ref
from tests.support import make_db, seed_host_row


def _entry(db, slug="redis", sha="a" * 40):
    db.add(CatalogEntry(slug=slug, name=slug, script_path=f"ct/{slug}.sh",
                        upstream_sha=sha, installable=True,
                        raw={"install_script": "#!/bin/bash\n"}))
    db.commit()


def _app(db, host, slug="redis", ctid=101, ref="a" * 40, version=1):
    a = App(host_id=host.id, ctid=ctid, name=slug, slug=f"{slug}-{host.id}-{ctid}",
            catalog_slug=slug, web_protocol="http", web_path="/", adopted=True)
    db.add(a)
    db.flush()
    if ref is not None:
        db.add(AppScript(app_id=a.id, version=version, content="x",
                         content_sha256="0" * 64, source="upstream",
                         upstream_ref=ref))
    db.commit()
    return a


def test_pinned_ref_reads_the_newest_script_version(tmp_path):
    db = make_db(tmp_path)
    host = seed_host_row(db)
    _entry(db)
    a = _app(db, host, ref="a" * 40)
    db.add(AppScript(app_id=a.id, version=2, content="y", content_sha256="1" * 64,
                     source="edited", upstream_ref="b" * 40))
    db.commit()
    assert pinned_ref(db, a.id) == "b" * 40


def test_marks_an_app_whose_upstream_moved(tmp_path):
    db = make_db(tmp_path)
    host = seed_host_row(db)
    _entry(db, sha="b" * 40)                     # catalog moved on ...
    a = _app(db, host, ref="a" * 40)             # ... app still pinned to the old one

    assert mark_updates_available(db) == {"marked": 1, "cleared": 0}
    db.refresh(a)
    assert a.update_available == "b" * 7         # short sha, doc 06 "Update to vX"


def test_leaves_a_current_app_alone(tmp_path):
    db = make_db(tmp_path)
    host = seed_host_row(db)
    _entry(db, sha="a" * 40)
    a = _app(db, host, ref="a" * 40)

    assert mark_updates_available(db) == {"marked": 0, "cleared": 0}
    db.refresh(a)
    assert a.update_available is None


def test_clears_the_flag_once_the_app_catches_up(tmp_path):
    """The flag is derived state, not a latch; an app that updated (or whose
    catalog entry rolled back) must stop advertising an update."""
    db = make_db(tmp_path)
    host = seed_host_row(db)
    _entry(db, sha="a" * 40)
    a = _app(db, host, ref="a" * 40)
    a.update_available = "b" * 7
    db.commit()

    assert mark_updates_available(db) == {"marked": 0, "cleared": 1}
    db.refresh(a)
    assert a.update_available is None


def test_ignores_an_adopted_app_with_no_catalog_slug(tmp_path):
    """A hand-rolled CT adopted in Phase 4 has no upstream to compare against."""
    db = make_db(tmp_path)
    host = seed_host_row(db)
    a = App(host_id=host.id, ctid=110, name="custom", slug="custom-1-110",
            catalog_slug=None, web_protocol="http", web_path="/", adopted=True)
    db.add(a)
    db.commit()

    assert mark_updates_available(db) == {"marked": 0, "cleared": 0}
    db.refresh(a)
    assert a.update_available is None


def test_ignores_an_app_with_no_pinned_script(tmp_path):
    """Adopted apps have no app_scripts row; there is no "from" commit, so
    there is no honest diff to offer."""
    db = make_db(tmp_path)
    host = seed_host_row(db)
    _entry(db, sha="b" * 40)
    a = _app(db, host, ref=None)

    assert mark_updates_available(db) == {"marked": 0, "cleared": 0}
    db.refresh(a)
    assert a.update_available is None


def test_ignores_a_catalog_entry_with_no_pinned_sha(tmp_path):
    db = make_db(tmp_path)
    host = seed_host_row(db)
    db.add(CatalogEntry(slug="redis", name="redis", script_path="ct/redis.sh",
                        upstream_sha=None, installable=True))
    db.commit()
    a = _app(db, host, ref="a" * 40)

    assert mark_updates_available(db) == {"marked": 0, "cleared": 0}
    db.refresh(a)
    assert a.update_available is None


def test_catalog_refresh_marks_updates_when_it_finishes(tmp_path, monkeypatch):
    """Refresh is the only moment the answer can change, so it is the only
    place this needs to run."""
    import asyncio

    from proxploy.jobs import JobBackend, JobContext
    from proxploy.models import Job
    from proxploy.services import catalog
    from tests.support import make_job_app

    async def go():
        app = make_job_app(tmp_path)
        app.state.jobs = JobBackend(app)
        with app.state.sessionmaker() as db:
            host = seed_host_row(db)
            _entry(db, sha="a" * 40)
            a = _app(db, host, ref="a" * 40)
            app_id = a.id
            job = Job(kind="catalog.refresh", status="running")
            db.add(job)
            db.commit()
            job_id = job.id

        def fake_ingest(db, slugs):
            row = db.query(CatalogEntry).filter_by(slug="redis").one()
            row.upstream_sha = "c" * 40           # upstream moved
            db.commit()
            return {"synced": 1, "failed": [], "upstream_sha": "c" * 40}

        monkeypatch.setattr(catalog, "run_ingest", fake_ingest)
        ctx = JobContext(app.state.jobs, job_id)
        out = await catalog.refresh_catalog(ctx, {"slugs": ["redis"]})
        assert out["updates_marked"] == 1

        with app.state.sessionmaker() as db:
            assert db.get(App, app_id).update_available == "c" * 7

    asyncio.run(go())
