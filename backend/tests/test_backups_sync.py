"""backup.sync: PVE storage content -> the `backups` cache table (doc 04
§backups, a droppable mirror), plus the cached GET /api/v1/backups the page
reads. Nothing wrote this table before this task."""
import asyncio
import json
import time

from proxploy.models import App, Backup, Host, HostCredential, Job, Vm

VOLID_CT = "local:backup/vzdump-lxc-150-2026_07_30-02_00_00.tar.zst"
VOLID_VM = "local:backup/vzdump-qemu-201-2026_07_30-03_00_00.vma.zst"


def _fake_with_backups(items=None):
    from tests.fakes.pve import FakePVE

    fake = FakePVE()
    fake.storages_by_node = {"pve1": [
        {"storage": "local", "type": "dir", "content": "backup,iso,vztmpl"},
        {"storage": "local-lvm", "type": "lvmthin", "content": "images,rootdir"},
    ]}
    fake.content_by_storage = {"local": items if items is not None else [
        {"volid": VOLID_CT, "ctime": 1753840800, "size": 1073741824,
         "format": "tar.zst", "content": "backup",
         "verification": {"state": "ok"}, "notes": "nightly"},
        {"volid": VOLID_VM, "ctime": 1753844400, "size": 5368709120,
         "format": "vma.zst", "content": "backup",
         "verification": {"state": "failed"}, "notes": None},
    ]}
    return fake


def _seed_host(app):
    with app.state.sessionmaker() as db:
        host = Host(name="host-01", address="https://10.0.0.7:8006", node_name="pve1",
                    status="connected", pve_version="8.4.1")
        db.add(host)
        db.commit()
        blob, ver = app.state.secretstore.encrypt(json.dumps(
            {"token_id": "proxploy@pve!bk", "token_secret": "s3cret"}).encode())
        db.add(HostCredential(host_id=host.id, kind="api_token:backup", encrypted_blob=blob,
                              key_version=ver, public_meta="proxploy@pve!bk"))
        db.add(App(host_id=host.id, ctid=150, name="Immich", slug="immich"))
        db.add(Vm(host_id=host.id, vmid=201, name="win11", status="running"))
        db.commit()
        return host.id


def test_parse_volid_reads_guest_type_and_vmid():
    from proxploy.services.backupjobs import parse_volid

    assert parse_volid(VOLID_CT) == ("ct", 150)
    assert parse_volid(VOLID_VM) == ("vm", 201)
    assert parse_volid("pbs-ds:backup/ct/150/2026-07-30T02:00:00Z") == ("ct", 150)
    assert parse_volid("pbs-ds:backup/vm/201/2026-07-30T03:00:00Z") == ("vm", 201)
    assert parse_volid("local:iso/debian-12.iso") == (None, None)


def test_sync_mirrors_backup_storages_only_and_resolves_guest_names(tmp_path):
    from proxploy.services.backupjobs import sync_host_backups
    from tests.support import make_job_app

    async def run():
        fake = _fake_with_backups()
        app = make_job_app(tmp_path, fake=fake)
        hid = _seed_host(app)
        result = sync_host_backups(app, hid)
        assert result["synced"] == 2 and result["dropped"] == 0
        with app.state.sessionmaker() as db:
            rows = {b.volid: b for b in db.query(Backup).all()}
            assert set(rows) == {VOLID_CT, VOLID_VM}  # local-lvm has no `backup` content
            ct = rows[VOLID_CT]
            assert ct.storage == "local" and ct.guest_type == "ct" and ct.guest_vmid == 150
            assert ct.guest_name == "Immich"
            assert ct.size_bytes == 1073741824 and ct.verify_state == "ok"
            assert ct.notes == "nightly" and ct.taken_at is not None
            assert ct.synced_at is not None
            assert rows[VOLID_VM].guest_name == "win11"
            assert rows[VOLID_VM].verify_state == "failed"

    asyncio.run(run())


def test_sync_is_idempotent_and_drops_vanished_volids(tmp_path):
    from proxploy.services.backupjobs import sync_host_backups
    from tests.support import make_job_app

    async def run():
        fake = _fake_with_backups()
        app = make_job_app(tmp_path, fake=fake)
        hid = _seed_host(app)
        sync_host_backups(app, hid)
        assert sync_host_backups(app, hid)["synced"] == 2  # no duplicate rows
        with app.state.sessionmaker() as db:
            assert db.query(Backup).count() == 2
        fake.content_by_storage["local"] = [
            {"volid": VOLID_CT, "ctime": 1753840800, "size": 1073741824,
             "content": "backup", "verification": {"state": "ok"}, "notes": "nightly"}]
        assert sync_host_backups(app, hid)["dropped"] == 1
        with app.state.sessionmaker() as db:
            assert [b.volid for b in db.query(Backup).all()] == [VOLID_CT]

    asyncio.run(run())


def test_backup_sync_job_runs_end_to_end(tmp_path):
    from proxploy.jobs import HANDLERS, JobBackend
    from tests.support import make_job_app

    async def run():
        fake = _fake_with_backups()
        app = make_job_app(tmp_path, fake=fake)
        import proxploy.services.backupjobs  # noqa: F401  (registers backup.sync)

        assert "backup.sync" in HANDLERS
        backend = JobBackend(app)
        _seed_host(app)
        with app.state.sessionmaker() as db:
            jid = backend.enqueue(db, kind="backup.sync", target_type="system",
                                  params={}).id
        await backend.wait(jid, timeout=10)
        with app.state.sessionmaker() as db:
            job = db.get(Job, jid)
            assert job.status == "succeeded", job.error
            assert job.result["synced"] == 2 and job.result["failed"] == []
            assert db.query(Backup).count() == 2

    asyncio.run(run())


def test_a_broken_host_does_not_abort_the_batch(tmp_path):
    from proxploy.jobs import JobBackend
    from tests.support import make_job_app

    async def run():
        fake = _fake_with_backups()
        app = make_job_app(tmp_path, fake=fake)
        import proxploy.services.backupjobs  # noqa: F401

        backend = JobBackend(app)
        _seed_host(app)
        with app.state.sessionmaker() as db:  # second host, no api_token credential
            db.add(Host(name="host-02", address="https://10.0.0.8:8006",
                        node_name="pve2", status="connected"))
            db.commit()
            jid = backend.enqueue(db, kind="backup.sync", target_type="system",
                                  params={}).id
        await backend.wait(jid, timeout=10)
        with app.state.sessionmaker() as db:
            job = db.get(Job, jid)
            assert job.status == "succeeded", job.error
            assert job.result["synced"] == 2 and len(job.result["failed"]) == 1

    asyncio.run(run())


def test_a_failed_storage_read_does_not_drop_the_hosts_existing_backups(tmp_path):
    """A transient failure on ONE storage mid-cycle must not delete this
    host's already-synced rows as "vanished". `sync_host_backups` builds the
    `rows` list (one PVE call per backup-capable storage) BEFORE it queries
    `existing` or touches the DB at all, so a raise partway through that loop
    must propagate out with nothing added, deleted, or committed for this
    host, the whole host's sync is skipped this cycle, not partially
    applied. The job handler records it as a per-host failure and moves on
    (`services/catalog.py::run_ingest`'s rule), exactly like a missing
    credential, but a missing credential fails before any PVE call and
    before the `existing` query, it never exercises this delete-scope
    protection. This test does, by pre-seeding real rows and asserting none
    of them vanish."""
    from proxploy.jobs import JobBackend
    from proxploy.models import utcnow
    from tests.support import make_job_app

    PBS_VOLID = "pbs-ds:backup/vm/201/2026-07-01T00:00:00Z"

    async def run():
        fake = _fake_with_backups()
        # a second backup-capable storage on the same node; its content read
        # fails this cycle while "local" (processed first) succeeds fine.
        fake.storages_by_node["pve1"].append(
            {"storage": "pbs-ds", "type": "pbs", "content": "backup"})
        fake.content_fail_storages = {"pbs-ds"}
        app = make_job_app(tmp_path, fake=fake)
        import proxploy.services.backupjobs  # noqa: F401  (registers backup.sync)

        hid = _seed_host(app)
        with app.state.sessionmaker() as db:  # rows a prior, successful sync left behind
            now = utcnow()
            db.add(Backup(host_id=hid, storage="local", volid=VOLID_CT, guest_type="ct",
                          guest_vmid=150, guest_name="Immich", taken_at=now,
                          size_bytes=1073741824, verify_state="ok", synced_at=now))
            db.add(Backup(host_id=hid, storage="pbs-ds", volid=PBS_VOLID, guest_type="vm",
                          guest_vmid=201, guest_name="win11", taken_at=now,
                          size_bytes=5368709120, verify_state="ok", synced_at=now))
            db.commit()

        backend = JobBackend(app)
        with app.state.sessionmaker() as db:
            jid = backend.enqueue(db, kind="backup.sync", target_type="system",
                                  params={}).id
        await backend.wait(jid, timeout=10)
        with app.state.sessionmaker() as db:
            job = db.get(Job, jid)
            assert job.status == "succeeded", job.error  # batch not aborted
            assert job.result["synced"] == 0  # this host's cycle never committed
            assert len(job.result["failed"]) == 1
            assert job.result["failed"][0]["host_id"] == hid  # recorded, not swallowed
            rows = {b.volid for b in db.query(Backup).filter_by(host_id=hid)}
            assert rows == {VOLID_CT, PBS_VOLID}  # nothing dropped

    asyncio.run(run())


def _seed_two_backups(app):
    from datetime import timedelta

    from proxploy.models import utcnow
    from tests.support import seed_host_row

    with app.state.sessionmaker() as db:
        h = seed_host_row(db)
        now = utcnow()
        db.add(Backup(host_id=h.id, storage="local", volid=VOLID_VM, guest_type="vm",
                      guest_vmid=201, guest_name="win11", taken_at=now - timedelta(hours=1),
                      size_bytes=30, verify_state="failed", synced_at=now))
        db.add(Backup(host_id=h.id, storage="local", volid=VOLID_CT, guest_type="ct",
                      guest_vmid=150, guest_name="Immich", taken_at=now,
                      size_bytes=10, verify_state="ok", synced_at=now))
        db.commit()


def test_backups_list_returns_cached_rows_and_stats(tmp_path, bootstrap_admin):
    from fastapi.testclient import TestClient
    from proxploy.services.backupjobs import SYNCED_AT_KEY
    from proxploy.services.settings import set_setting
    from proxploy.models import utcnow
    from tests.support import make_app

    app = make_app(tmp_path)
    c = TestClient(app)
    with c:
        bootstrap_admin(c)
        _seed_two_backups(app)
        with app.state.sessionmaker() as db:
            set_setting(db, SYNCED_AT_KEY, utcnow().isoformat())
        body = c.get("/api/v1/backups").json()
        assert [b["volid"] for b in body["backups"]] == [VOLID_CT, VOLID_VM]  # newest first
        assert body["backups"][0]["host_name"] == "host-01"
        assert body["backups"][0]["guest_name"] == "Immich"
        st = body["stats"]
        assert st["total"] == 2 and st["total_bytes"] == 40
        assert st["ok_count"] == 1 and st["failed_count"] == 1
        assert st["success_rate_30d"] == 50.0
        assert st["datastores"] == [{"storage": "local", "count": 2, "size_bytes": 40}]
        assert body["stale"] is False and body["synced_at"] is not None


def test_backups_list_is_capped_but_its_totals_are_not(tmp_path, bootstrap_admin):
    """The list is bounded; the summary block still counts the whole table.

    GET /backups used to serialise every row on a page that polls every 60s.
    Capping the rows is only safe if the stats stop being derived from them,
    so this seeds more archives than the cap and checks both halves at once:
    a short list, and totals that still know about every archive.
    """
    from datetime import timedelta

    from fastapi.testclient import TestClient

    from proxploy.api.backups import BACKUPS_MAX
    from proxploy.models import utcnow
    from tests.support import make_app, seed_host_row

    extra = 5
    app = make_app(tmp_path)
    c = TestClient(app)
    with c:
        bootstrap_admin(c)
        with app.state.sessionmaker() as db:
            h = seed_host_row(db)
            now = utcnow()
            for i in range(BACKUPS_MAX + extra):
                db.add(Backup(host_id=h.id, storage="local", volid=f"local:backup/v{i}",
                              guest_type="ct", guest_vmid=150,
                              taken_at=now - timedelta(minutes=i), size_bytes=10,
                              verify_state="ok", synced_at=now))
            db.commit()
        body = c.get("/api/v1/backups").json()

        assert len(body["backups"]) == BACKUPS_MAX
        assert body["backups"][0]["volid"] == "local:backup/v0"  # newest first
        st = body["stats"]
        assert st["total"] == BACKUPS_MAX + extra
        assert st["total_bytes"] == (BACKUPS_MAX + extra) * 10
        assert st["ok_count"] == BACKUPS_MAX + extra
        assert st["datastores"] == [{"storage": "local", "count": BACKUPS_MAX + extra,
                                     "size_bytes": (BACKUPS_MAX + extra) * 10}]
        assert st["success_rate_30d"] == 100.0
        assert body["synced_at"] is not None  # aggregate, not scanned from the page

        # A smaller ask is honoured; an absurd one is clamped, never obeyed.
        assert len(c.get("/api/v1/backups", params={"limit": 3}).json()["backups"]) == 3
        assert len(c.get("/api/v1/backups",
                         params={"limit": 100000}).json()["backups"]) == BACKUPS_MAX


def test_unverified_backups_report_no_success_rate(tmp_path, bootstrap_admin):
    from fastapi.testclient import TestClient
    from proxploy.models import utcnow
    from tests.support import make_app, seed_host_row

    app = make_app(tmp_path)
    c = TestClient(app)
    with c:
        bootstrap_admin(c)
        with app.state.sessionmaker() as db:
            h = seed_host_row(db)
            db.add(Backup(host_id=h.id, storage="local", volid=VOLID_CT,
                          guest_type="ct", guest_vmid=150, taken_at=utcnow(),
                          size_bytes=1, verify_state="none", synced_at=utcnow()))
            db.commit()
        st = c.get("/api/v1/backups").json()["stats"]
        assert st["total"] == 1
        assert st["success_rate_30d"] is None  # never a fake 100%


def test_empty_cache_auto_enqueues_exactly_one_sync(tmp_path, bootstrap_admin):
    from fastapi.testclient import TestClient
    from tests.support import make_app

    app = make_app(tmp_path)
    c = TestClient(app)
    with c:
        bootstrap_admin(c)
        body = c.get("/api/v1/backups").json()
        assert body["backups"] == [] and body["stale"] is True
        for _ in range(100):  # let the auto-enqueued sync finish (no hosts -> instant)
            with app.state.sessionmaker() as db:
                j = db.query(Job).filter_by(kind="backup.sync").one()  # .one() = never twice
                if j.status in ("succeeded", "failed", "canceled", "interrupted"):
                    break
            time.sleep(0.05)
        assert j.status == "succeeded", j.error
        body = c.get("/api/v1/backups").json()
        assert body["stale"] is False  # a completed sync over an empty cluster is fresh
        with app.state.sessionmaker() as db:
            assert db.query(Job).filter_by(kind="backup.sync").count() == 1


def test_backups_list_requires_auth(tmp_path):
    from fastapi.testclient import TestClient
    from tests.support import make_app

    with TestClient(make_app(tmp_path)) as c:
        assert c.get("/api/v1/backups").status_code == 401


def test_concurrent_stale_reads_enqueue_only_one_sync(tmp_path, bootstrap_admin):
    """The anti-stampede guard (api/backups.py's module-level lock, plus
    sync_in_flight's db.rollback()) must hold under REAL concurrency, not just
    sequential calls from one client; the page is polled every 60s and may be
    open in several tabs at once, each hitting GET /backups from a different
    FastAPI threadpool thread at roughly the same time. A bare
    check-then-enqueue (no lock) races: N threads can all see "no sync in
    flight" before any of them commits its Job row, producing N jobs instead
    of one.

    The handler is PINNED for the duration, and that is the whole point rather
    than a convenience. What the guard promises is "no second sync while one
    is in flight", and `sync_in_flight` counts exactly the queued/running
    rows. Nothing here configures a host, so the real handler finishes almost
    immediately, and a thread that looks after it finished is then CORRECT to
    enqueue a second job. Asserting a bare total of 1 without pinning was
    therefore asserting something the guard never promised: it passed on a
    fast machine, and failed on a loaded CI runner, while the code under test
    was behaving exactly as designed.
    """
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from fastapi.testclient import TestClient

    from proxploy.jobs import HANDLERS
    from tests.support import make_app

    WORKERS = 8
    release = threading.Event()
    started = threading.Event()

    async def _pinned(ctx, params):
        started.set()
        # Bounded so a regression fails as an assertion rather than hanging
        # the suite; the finally below normally releases it long before.
        await asyncio.to_thread(release.wait, 30)
        return {}

    # make_app first: "backup.sync" lands in HANDLERS as an import side effect
    # of services/backupjobs, so the key does not exist until something pulls
    # that module in. The backend looks the handler up at enqueue time, so
    # swapping it after the app is built is still in time.
    app = make_app(tmp_path)
    real = HANDLERS["backup.sync"]
    HANDLERS["backup.sync"] = _pinned
    try:
        c = TestClient(app)
        with c:
            bootstrap_admin(c)

            # The barrier is what makes this a race test rather than a
            # coin flip. Without it the threads trickle into the handler as
            # the pool starts them, the window between check and enqueue is
            # tens of microseconds wide, and an unguarded build slips through
            # most runs: removing the lock was caught only once in three
            # tries. Releasing all N at one instant puts them in that window
            # together, which is the situation several open browser tabs
            # actually produce.
            gate = threading.Barrier(WORKERS)

            def hit(_):
                gate.wait(timeout=10)
                return c.get("/api/v1/backups").status_code

            # WORKERS stays under the engine pool ceiling (5 + 10 overflow):
            # every in-flight request holds a session for its whole duration,
            # so a wider burst makes the surplus wait out the 30s checkout
            # timeout and fail as QueuePool TimeoutError. That is bench
            # pressure on the connection pool, not the race under test.
            with ThreadPoolExecutor(max_workers=WORKERS) as pool:
                statuses = list(pool.map(hit, range(WORKERS)))
            assert all(s == 200 for s in statuses)
            assert started.wait(10), "the first sync job never started"

            # Still pinned, so every one of those reads saw a sync in flight.
            # Exactly one row is the guard doing its job.
            with app.state.sessionmaker() as db:
                assert db.query(Job).filter_by(kind="backup.sync").count() == 1

            # Unpin INSIDE the client context: TestClient's exit runs app
            # shutdown, which waits on in-flight jobs, so releasing in the
            # finally below would make every run pay the pin's full timeout.
            release.set()
    finally:
        release.set()
        HANDLERS["backup.sync"] = real


def test_the_newest_backups_are_read_from_an_index_not_a_full_sort(tmp_path):
    """The 200 row cap bounds what the route RETURNS, not the work it does.
    Without an index on taken_at, `ORDER BY taken_at DESC LIMIT 200` sorts the
    whole table on a page that polls every 60s and can be open in several
    tabs, and that cost grows with backup history forever.

    Asserting the query plan rather than a timing: a wall-clock threshold is
    the flakiest possible way to state this, and the plan is the actual claim.
    """
    from datetime import datetime, timedelta

    from proxploy.models import Backup, Host
    from tests.support import make_db

    db = make_db(tmp_path)
    db.add(Host(name="h", address="https://pve:8006", node_name="pve1"))
    db.commit()
    host_id = db.query(Host).one().id
    base = datetime(2025, 1, 1)
    db.bulk_save_objects([
        Backup(host_id=host_id, volid=f"local:backup/v-{i}.tar.zst",
               storage="local", taken_at=base + timedelta(minutes=i))
        for i in range(2000)
    ])
    db.commit()

    cur = db.get_bind().raw_connection().cursor()
    plan = " ".join(
        r[-1] for r in cur.execute(
            "EXPLAIN QUERY PLAN "
            "SELECT * FROM backups ORDER BY taken_at DESC LIMIT 200"))
    assert "ix_backups_taken_at" in plan, plan
    # The tell that the index is doing the ordering, not just being read.
    assert "USE TEMP B-TREE FOR ORDER BY" not in plan, plan
