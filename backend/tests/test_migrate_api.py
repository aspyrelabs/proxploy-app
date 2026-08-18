# backend/tests/test_migrate_api.py
"""`POST /apps/{app_id}/migrate` (Phase 8 Task 15), the route half of
`migrate.app`. services/migrate.py's own preflight/handler tests
(test_migrate_preflight.py, test_migrate_job.py) cover the migration logic
itself; this file is auth/entitlement/404/409/wildcard wiring only, same
split as every other Phase 6/7/8 route test in this suite.

FAKES vs HARDWARE: same FakePVE-only proof as test_migrate_preflight.py and
test_migrate_job.py, no live Proxmox host anywhere in this repo.
"""
import json

from fastapi.testclient import TestClient

from proxploy.models import App, Host, HostCredential, Job

SRC_ADDR = "https://10.0.0.101:8006"
TGT_ADDR = "https://10.0.0.102:8006"
SRC_HOSTNAME = "10.0.0.101"
TGT_HOSTNAME = "10.0.0.102"

SHARED_ROW = {"storage": "pbs-ds", "type": "pbs", "content": "backup"}


def _make_app(tmp_path, fakes: dict):
    from proxploy.api.auth import limiter
    from proxploy.config import Settings
    from proxploy.main import create_app
    from tests.fakes.pve import make_addressed_factory

    limiter.reset()
    s = Settings(db_url=f"sqlite:///{tmp_path}/t.db", data_dir=tmp_path,
                master_key_file=tmp_path / "master.key", poll_enabled=False)
    return create_app(s, proxmox_factory=make_addressed_factory(fakes))


def _seed(app, *, src_node="pve-src", tgt_node="pve-tgt", ctid=150, name="immich"):
    with app.state.sessionmaker() as db:
        src = Host(name="host-src", address=SRC_ADDR, node_name=src_node,
                  status="connected", pve_version="8.4.1")
        tgt = Host(name="host-tgt", address=TGT_ADDR, node_name=tgt_node,
                  status="connected", pve_version="8.4.1")
        db.add(src); db.add(tgt); db.commit()
        # Migration needs monitoring/lifecycle/backup on both hosts
        # (services/migrate.py::_load); FakePVE ignores token identity.
        for h, tag in ((src, "src"), (tgt, "tgt")):
            for cap in ("monitoring", "lifecycle", "backup"):
                blob, ver = app.state.secretstore.encrypt(json.dumps(
                    {"token_id": f"proxploy@pve!{tag}-{cap}",
                     "token_secret": "s3cret"}).encode())
                db.add(HostCredential(host_id=h.id, kind=f"api_token:{cap}",
                                      encrypted_blob=blob, key_version=ver,
                                      public_meta=f"proxploy@pve!{tag}-{cap}"))
        a = App(host_id=src.id, ctid=ctid, name=name, slug=name, web_protocol="http",
               web_path="/")
        db.add(a)
        db.commit()
        return src.id, tgt.id, a.id


def _fake_pair(shared_storage="pbs-ds"):
    from tests.fakes.pve import FakePVE

    a, b = FakePVE(), FakePVE()
    row = {"storage": shared_storage, "type": "pbs", "content": "backup"}
    a.cluster_storage_rows = [dict(row)]
    b.cluster_storage_rows = [dict(row)]
    # A PBS datastore holds the ARCHIVE and cannot hold a rootfs, so the target
    # also needs a pool carrying `rootdir` or preflight blocks: it now names
    # where the restored disk lands rather than checking only the archive's pool
    # (doc 12 check 7).
    for fake, node in ((a, "pve-src"), (b, "pve-tgt")):
        fake.storages_by_node = {node: [
            dict(row, active=1, avail=10 * 1024 ** 4),
            {"storage": "local-lvm", "type": "lvmthin", "content": "rootdir",
             "active": 1, "avail": 10 * 1024 ** 4},
        ]}
    return a, b


def _migrate(client, csrf_header, app_id, target_host_id, confirm=None):
    body = {"target_host_id": target_host_id}
    if confirm is not None:
        body["confirm"] = confirm
    return client.post(f"/api/v1/apps/{app_id}/migrate", json=body,
                       headers=csrf_header(client))


def _mk_user(client, csrf_header, email, role, password="correct-horse-battery"):
    h = csrf_header(client)
    r = client.post("/api/v1/users", json={"email": email, "password": password,
                                           "role": role}, headers=h)
    assert r.status_code == 201, r.text


def _login(client, csrf_header, email, password="correct-horse-battery"):
    r = client.post("/api/v1/auth/login", json={"email": email, "password": password},
                    headers=csrf_header(client))
    assert r.status_code == 200, r.text


# --- happy path: 202 + a real migrate.app job row ------------------------------

def test_migrate_enqueues_a_migrate_app_job_and_returns_preflight(tmp_path, csrf_header,
                                                                   bootstrap_admin):
    fake_src, fake_tgt = _fake_pair()
    app = _make_app(tmp_path, {SRC_HOSTNAME: fake_src, TGT_HOSTNAME: fake_tgt})

    with TestClient(app) as c:
        bootstrap_admin(c)
        src_id, tgt_id, app_id = _seed(app)
        r = _migrate(c, csrf_header, app_id, tgt_id)
        assert r.status_code == 202, r.text
        body = r.json()
        assert body["job"]["kind"] == "migrate.app"
        assert body["job"]["status"] in ("queued", "running")
        assert body["preflight"]["strategy"] == "shared_storage"

        with app.state.sessionmaker() as db:
            job = db.get(Job, body["job"]["id"])
            assert job is not None
            assert job.kind == "migrate.app"
            assert job.params == {"app_id": app_id, "target_host_id": tgt_id}


# --- blockers refuse before a job is ever enqueued -----------------------------

def test_blockers_refuse_with_409_and_no_job_is_enqueued(tmp_path, csrf_header,
                                                          bootstrap_admin):
    from tests.fakes.pve import FakePVE

    # no shared storage, no dir storage anywhere -> transfer strategy, blocked
    fake_src, fake_tgt = FakePVE(), FakePVE()
    app = _make_app(tmp_path, {SRC_HOSTNAME: fake_src, TGT_HOSTNAME: fake_tgt})

    with TestClient(app) as c:
        bootstrap_admin(c)
        src_id, tgt_id, app_id = _seed(app)
        with app.state.sessionmaker() as db:
            before = db.query(Job).count()
        r = _migrate(c, csrf_header, app_id, tgt_id)
        assert r.status_code == 409, r.text
        assert r.json()["error"] == "migration_blocked"
        assert r.json()["blockers"]
        with app.state.sessionmaker() as db:
            assert db.query(Job).count() == before


# --- self-target guard, exact shape from enqueue_lifecycle ---------------------

def test_self_target_without_confirm_is_409_self_target(tmp_path, csrf_header,
                                                         bootstrap_admin):
    from proxploy.services.settings import set_setting

    fake_src, fake_tgt = _fake_pair()
    app = _make_app(tmp_path, {SRC_HOSTNAME: fake_src, TGT_HOSTNAME: fake_tgt})

    with TestClient(app) as c:
        bootstrap_admin(c)
        src_id, tgt_id, app_id = _seed(app, name="Proxploy")
        with app.state.sessionmaker() as db:
            set_setting(db, "self.ctid", 150)
            set_setting(db, "self.host_id", src_id)

        r = _migrate(c, csrf_header, app_id, tgt_id)
        assert r.status_code == 409, r.text
        body = r.json()
        assert body["error"] == "self_target"
        assert body["confirm_phrase"] == "Proxploy"

        with app.state.sessionmaker() as db:
            assert db.query(Job).count() == 0

        r2 = _migrate(c, csrf_header, app_id, tgt_id, confirm="Proxploy")
        assert r2.status_code == 202, r2.text


# --- RBAC: viewer/operator refused, admin allowed -------------------------------

def test_route_rbac_viewer_and_operator_403_admin_202(tmp_path, csrf_header,
                                                       bootstrap_admin):
    fake_src, fake_tgt = _fake_pair()
    app = _make_app(tmp_path, {SRC_HOSTNAME: fake_src, TGT_HOSTNAME: fake_tgt})

    with TestClient(app) as c:
        bootstrap_admin(c)
        src_id, tgt_id, app_id = _seed(app)
        _mk_user(c, csrf_header, "viewer@x.io", "viewer")
        _mk_user(c, csrf_header, "operator@x.io", "operator")
        _mk_user(c, csrf_header, "admin@x.io", "admin")

        c.post("/api/v1/auth/logout", headers=csrf_header(c))
        _login(c, csrf_header, "viewer@x.io")
        assert _migrate(c, csrf_header, app_id, tgt_id).status_code == 403

        c.post("/api/v1/auth/logout", headers=csrf_header(c))
        _login(c, csrf_header, "operator@x.io")
        assert _migrate(c, csrf_header, app_id, tgt_id).status_code == 403

        c.post("/api/v1/auth/logout", headers=csrf_header(c))
        _login(c, csrf_header, "admin@x.io")
        r = _migrate(c, csrf_header, app_id, tgt_id)
        assert r.status_code == 202, r.text


def test_missing_session_is_401_not_403(tmp_path, csrf_header, bootstrap_admin):
    fake_src, fake_tgt = _fake_pair()
    app = _make_app(tmp_path, {SRC_HOSTNAME: fake_src, TGT_HOSTNAME: fake_tgt})

    with TestClient(app) as c:
        _, tgt_id, app_id = _seed(app)
        r = c.post(f"/api/v1/apps/{app_id}/migrate", json={"target_host_id": tgt_id},
                  headers=csrf_header(c))
        assert r.status_code == 401


# --- 404 / 409 target validation, matching /migrate/preflight's own rules -----

def test_unknown_app_is_404(tmp_path, csrf_header, bootstrap_admin):
    fake_src, fake_tgt = _fake_pair()
    app = _make_app(tmp_path, {SRC_HOSTNAME: fake_src, TGT_HOSTNAME: fake_tgt})

    with TestClient(app) as c:
        bootstrap_admin(c)
        _seed(app)
        assert _migrate(c, csrf_header, 999, 1).status_code == 404


def test_unknown_or_unconnected_or_source_target_is_409(tmp_path, csrf_header,
                                                         bootstrap_admin):
    from proxploy.models import Host as HostModel

    fake_src, fake_tgt = _fake_pair()
    app = _make_app(tmp_path, {SRC_HOSTNAME: fake_src, TGT_HOSTNAME: fake_tgt})

    with TestClient(app) as c:
        bootstrap_admin(c)
        src_id, tgt_id, app_id = _seed(app)
        with app.state.sessionmaker() as db:
            db.get(HostModel, tgt_id).status = "unreachable"
            db.commit()
        assert _migrate(c, csrf_header, app_id, 999999).status_code == 409  # unknown
        assert _migrate(c, csrf_header, app_id, src_id).status_code == 409  # == source
        assert _migrate(c, csrf_header, app_id, tgt_id).status_code == 409  # not connected


# --- wildcard-shadowing regression ---------------------------------------------

def test_route_does_not_get_shadowed_by_the_lifecycle_wildcard(tmp_path, csrf_header,
                                                                bootstrap_admin):
    """apps.py's WARNING on the `/{app_id}/{action}` wildcard: it is
    registered last and would swallow a two-segment sibling. `/migrate` is
    two segments, matching that WARNING exactly; a 422 'action must be one
    of start, stop, restart, shutdown' here would mean the wildcard ate this
    route and nobody registered it above the wildcard."""
    fake_src, fake_tgt = _fake_pair()
    app = _make_app(tmp_path, {SRC_HOSTNAME: fake_src, TGT_HOSTNAME: fake_tgt})

    with TestClient(app) as c:
        bootstrap_admin(c)
        src_id, tgt_id, app_id = _seed(app)
        r = _migrate(c, csrf_header, app_id, tgt_id)
        assert r.status_code == 202
        assert "action must be one of" not in r.text
