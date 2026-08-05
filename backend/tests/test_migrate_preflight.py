# backend/tests/test_migrate_preflight.py
"""Migration preflight (Phase 8 Task 14, services/migrate.py + POST
/apps/{id}/migrate/preflight).

FAKES vs HARDWARE — read this before trusting a green run: there is no live
Proxmox host in this repo and never will be. Every assertion here is proven
against `tests/fakes/pve.py`'s `FakePVE` — a hand-maintained mimic of the
proxmoxer attribute surface, fed rows this test writes itself. What that
proves: `services/migrate.py`'s strategy-selection logic, estimate math, and
the route's auth/entitlement/404/409/502 wiring are all correct GIVEN the PVE
API shapes this file encodes (`/cluster/status`, `/storage`, `/cluster/
resources`, `/nodes/{n}/storage`). What it does NOT prove: that a real PVE 8.x
or 9.x server actually returns those exact shapes for a real cluster/PBS/dir
storage setup — that needs a live node and is out of reach here (see doc 11
§7). The `_MigrateLeaf`/`make_addressed_factory` additions in `tests/fakes/
pve.py` exist for Task 15's `migrate.app` handler; this file only exercises
the preflight half.
"""
import json

from fastapi.testclient import TestClient

from proxploy.models import App, Backup, Host, HostCredential, utcnow

SRC_ADDR = "https://10.0.0.101:8006"
TGT_ADDR = "https://10.0.0.102:8006"
SRC_HOSTNAME = "10.0.0.101"
TGT_HOSTNAME = "10.0.0.102"


def _make_app(tmp_path, fakes: dict):
    from proxploy.api.auth import limiter
    from proxploy.config import Settings
    from proxploy.main import create_app
    from tests.fakes.pve import make_addressed_factory

    limiter.reset()
    s = Settings(db_url=f"sqlite:///{tmp_path}/t.db", data_dir=tmp_path,
                master_key_file=tmp_path / "master.key", poll_enabled=False)
    return create_app(s, proxmox_factory=make_addressed_factory(fakes))


def _seed(app, *, src_node="pve-src", tgt_node="pve-tgt", ctid=150,
         src_status="connected", tgt_status="connected"):
    with app.state.sessionmaker() as db:
        src = Host(name="host-src", address=SRC_ADDR, node_name=src_node,
                  status=src_status, pve_version="8.4.1")
        tgt = Host(name="host-tgt", address=TGT_ADDR, node_name=tgt_node,
                  status=tgt_status, pve_version="8.4.1")
        db.add(src); db.add(tgt); db.commit()
        for h, tag in ((src, "src"), (tgt, "tgt")):
            blob, ver = app.state.secretstore.encrypt(json.dumps(
                {"token_id": f"proxploy@pve!{tag}", "token_secret": "s3cret"}).encode())
            db.add(HostCredential(host_id=h.id, kind="api_token", encrypted_blob=blob,
                                  key_version=ver, public_meta=f"proxploy@pve!{tag}"))
        a = App(host_id=src.id, ctid=ctid, name="immich", slug="immich",
               web_protocol="http", web_path="/")
        db.add(a)
        db.commit()
        return src.id, tgt.id, a.id


def _fake_pair(shared_storage=None, dir_storage=None, cluster=None):
    from tests.fakes.pve import FakePVE

    a, b = FakePVE(), FakePVE()
    if cluster:
        rows = [{"type": "cluster", "name": cluster, "nodes": 2, "quorate": 1},
               {"type": "node", "name": "pve-src"}, {"type": "node", "name": "pve-tgt"}]
        a.cluster_status_rows = list(rows)
        b.cluster_status_rows = list(rows)
    if shared_storage:
        row = {"storage": shared_storage, "type": "pbs", "content": "backup"}
        a.cluster_storage_rows = [dict(row)]
        b.cluster_storage_rows = [dict(row)]
    if dir_storage:
        for fake, present in ((a, dir_storage[0]), (b, dir_storage[1])):
            if present:
                fake.cluster_storage_rows.append(
                    {"storage": "local", "type": "dir", "content": "backup,iso"})
    return a, b


def _seed_backup(app, host_id, ctid, size_bytes):
    with app.state.sessionmaker() as db:
        db.add(Backup(host_id=host_id, storage="pbs-ds",
                      volid=f"pbs-ds:backup/ct/{ctid}/2026-08-01T00:00:00Z",
                      guest_type="ct", guest_vmid=ctid, guest_name="immich",
                      taken_at=utcnow(), size_bytes=size_bytes, verify_state="ok",
                      synced_at=utcnow()))
        db.commit()


def _preflight(client, csrf_header, app_id, target_host_id):
    return client.post(f"/api/v1/apps/{app_id}/migrate/preflight",
                       json={"target_host_id": target_host_id},
                       headers=csrf_header(client))


# --- strategy: shared_storage ------------------------------------------------

def test_shared_storage_strategy_estimate_and_ip_warning(tmp_path, csrf_header,
                                                          bootstrap_admin):
    fake_src, fake_tgt = _fake_pair(shared_storage="pbs-ds")
    app = _make_app(tmp_path, {SRC_HOSTNAME: fake_src, TGT_HOSTNAME: fake_tgt})
    size = 10_000_000_000

    with TestClient(app) as c:
        bootstrap_admin(c)
        src_id, tgt_id, app_id = _seed(app)
        _seed_backup(app, src_id, 150, size)
        r = _preflight(c, csrf_header, app_id, tgt_id)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["strategy"] == "shared_storage"
        assert body["shared_storage"] == "pbs-ds"
        assert body["transfer_bytes"] == size
        assert body["estimate_basis"] == "last_backup"
        assert body["est_downtime_s"] == int(2 * size / 80e6) == 250
        assert isinstance(body["est_downtime_s"], int)
        assert any("IP" in w or "MAC" in w for w in body["warnings"])
        assert body["blockers"] == []
        assert body["self_target"] is False
        assert "stop → backup → transfer → restore → start" in body["downtime_statement"]


# --- strategy: cluster --------------------------------------------------------

def test_cluster_strategy_from_live_status_populates_cluster_name(tmp_path, csrf_header,
                                                                   bootstrap_admin):
    fake_src, fake_tgt = _fake_pair(cluster="prod-cluster")
    app = _make_app(tmp_path, {SRC_HOSTNAME: fake_src, TGT_HOSTNAME: fake_tgt})

    with TestClient(app) as c:
        bootstrap_admin(c)
        src_id, tgt_id, app_id = _seed(app)
        # hosts.cluster_name is unpopulated before the live check
        with app.state.sessionmaker() as db:
            assert db.get(Host, src_id).cluster_name is None
            assert db.get(Host, tgt_id).cluster_name is None

        r = _preflight(c, csrf_header, app_id, tgt_id)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["strategy"] == "cluster"
        assert body["target"]["ctid"] == 150  # native migrate keeps the vmid
        assert body["est_downtime_s"] == 30
        assert body["transfer_bytes"] is None
        assert body["warnings"] == []  # no IP note for a cluster-native migrate

        with app.state.sessionmaker() as db:
            assert db.get(Host, src_id).cluster_name == "prod-cluster"
            assert db.get(Host, tgt_id).cluster_name == "prod-cluster"


# --- strategy: transfer -------------------------------------------------------

def test_transfer_strategy_uses_allocated_disk_and_3x_multiplier(tmp_path, csrf_header,
                                                                  bootstrap_admin):
    fake_src, fake_tgt = _fake_pair(dir_storage=(True, True))
    maxdisk = 8_000_000_000
    fake_src.add_ct(150, node="pve-src", maxdisk=maxdisk)
    app = _make_app(tmp_path, {SRC_HOSTNAME: fake_src, TGT_HOSTNAME: fake_tgt})

    with TestClient(app) as c:
        bootstrap_admin(c)
        src_id, tgt_id, app_id = _seed(app)
        r = _preflight(c, csrf_header, app_id, tgt_id)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["strategy"] == "transfer"
        assert body["transfer_bytes"] == maxdisk
        assert body["estimate_basis"] == "allocated_disk"
        assert body["est_downtime_s"] == int(3 * maxdisk / 80e6) == 300
        assert body["blockers"] == []


def test_transfer_strategy_no_dir_storage_on_target_blocks(tmp_path, csrf_header,
                                                            bootstrap_admin):
    fake_src, fake_tgt = _fake_pair(dir_storage=(True, False))
    app = _make_app(tmp_path, {SRC_HOSTNAME: fake_src, TGT_HOSTNAME: fake_tgt})

    with TestClient(app) as c:
        bootstrap_admin(c)
        src_id, tgt_id, app_id = _seed(app)
        r = _preflight(c, csrf_header, app_id, tgt_id)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["strategy"] == "transfer"
        assert body["blockers"] == ["no dir-type backup storage on host-tgt"]


def test_no_size_available_reports_unknown_not_a_guess(tmp_path, csrf_header,
                                                        bootstrap_admin):
    """No Backup row and the guest isn't in /cluster/resources either — the
    honesty requirement: transfer_bytes/est_downtime_s must be None, never a
    fabricated number, and the statement must say why."""
    fake_src, fake_tgt = _fake_pair(dir_storage=(True, True))
    app = _make_app(tmp_path, {SRC_HOSTNAME: fake_src, TGT_HOSTNAME: fake_tgt})

    with TestClient(app) as c:
        bootstrap_admin(c)
        src_id, tgt_id, app_id = _seed(app)
        r = _preflight(c, csrf_header, app_id, tgt_id)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["transfer_bytes"] is None
        assert body["estimate_basis"] is None
        assert body["est_downtime_s"] is None
        assert body["capacity_ok"] is None
        assert "cannot be" in body["downtime_statement"].lower()


# --- capacity ------------------------------------------------------------

def test_capacity_ok_false_when_target_free_space_too_small(tmp_path, csrf_header,
                                                             bootstrap_admin):
    fake_src, fake_tgt = _fake_pair(shared_storage="pbs-ds")
    fake_tgt.storages_by_node = {"pve-tgt": [
        {"storage": "pbs-ds", "type": "pbs", "avail": 1_000_000_000}]}
    app = _make_app(tmp_path, {SRC_HOSTNAME: fake_src, TGT_HOSTNAME: fake_tgt})

    with TestClient(app) as c:
        bootstrap_admin(c)
        src_id, tgt_id, app_id = _seed(app)
        _seed_backup(app, src_id, 150, 10_000_000_000)  # 1.2x needs 12e9 avail
        r = _preflight(c, csrf_header, app_id, tgt_id)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["capacity_ok"] is False
        assert any("insufficient" in w for w in body["warnings"])


def test_capacity_ok_true_when_target_free_space_is_enough(tmp_path, csrf_header,
                                                            bootstrap_admin):
    fake_src, fake_tgt = _fake_pair(shared_storage="pbs-ds")
    fake_tgt.storages_by_node = {"pve-tgt": [
        {"storage": "pbs-ds", "type": "pbs", "avail": 100_000_000_000}]}
    app = _make_app(tmp_path, {SRC_HOSTNAME: fake_src, TGT_HOSTNAME: fake_tgt})

    with TestClient(app) as c:
        bootstrap_admin(c)
        src_id, tgt_id, app_id = _seed(app)
        _seed_backup(app, src_id, 150, 10_000_000_000)
        r = _preflight(c, csrf_header, app_id, tgt_id)
        assert r.status_code == 200, r.text
        assert r.json()["capacity_ok"] is True


# --- route-level: RBAC, 404, 409, wildcard non-shadowing ---------------------

def _mk_user(client, csrf_header, email, role, password="correct-horse-battery"):
    h = csrf_header(client)
    r = client.post("/api/v1/users", json={"email": email, "password": password,
                                           "role": role}, headers=h)
    assert r.status_code == 201, r.text


def _login(client, csrf_header, email, password="correct-horse-battery"):
    r = client.post("/api/v1/auth/login", json={"email": email, "password": password},
                    headers=csrf_header(client))
    assert r.status_code == 200, r.text


def test_route_rbac_viewer_and_operator_403_admin_200(tmp_path, csrf_header,
                                                       bootstrap_admin):
    fake_src, fake_tgt = _fake_pair(shared_storage="pbs-ds")
    app = _make_app(tmp_path, {SRC_HOSTNAME: fake_src, TGT_HOSTNAME: fake_tgt})

    with TestClient(app) as c:
        bootstrap_admin(c)  # owner session
        src_id, tgt_id, app_id = _seed(app)
        _seed_backup(app, src_id, 150, 1_000_000_000)
        _mk_user(c, csrf_header, "viewer@x.io", "viewer")
        _mk_user(c, csrf_header, "operator@x.io", "operator")
        _mk_user(c, csrf_header, "admin@x.io", "admin")

        c.post("/api/v1/auth/logout", headers=csrf_header(c))
        _login(c, csrf_header, "viewer@x.io")
        assert _preflight(c, csrf_header, app_id, tgt_id).status_code == 403

        c.post("/api/v1/auth/logout", headers=csrf_header(c))
        _login(c, csrf_header, "operator@x.io")
        assert _preflight(c, csrf_header, app_id, tgt_id).status_code == 403

        c.post("/api/v1/auth/logout", headers=csrf_header(c))
        _login(c, csrf_header, "admin@x.io")
        r = _preflight(c, csrf_header, app_id, tgt_id)
        assert r.status_code == 200, r.text
        assert r.json()["strategy"] == "shared_storage"


def test_unknown_app_is_404(tmp_path, csrf_header, bootstrap_admin):
    fake_src, fake_tgt = _fake_pair(shared_storage="pbs-ds")
    app = _make_app(tmp_path, {SRC_HOSTNAME: fake_src, TGT_HOSTNAME: fake_tgt})

    with TestClient(app) as c:
        bootstrap_admin(c)
        _seed(app)
        assert _preflight(c, csrf_header, 999, 1).status_code == 404


def test_unknown_or_unconnected_or_self_target_is_409(tmp_path, csrf_header,
                                                       bootstrap_admin):
    fake_src, fake_tgt = _fake_pair(shared_storage="pbs-ds")
    app = _make_app(tmp_path, {SRC_HOSTNAME: fake_src, TGT_HOSTNAME: fake_tgt})

    with TestClient(app) as c:
        bootstrap_admin(c)
        src_id, tgt_id, app_id = _seed(app, tgt_status="unreachable")
        assert _preflight(c, csrf_header, app_id, 999999).status_code == 409  # unknown
        assert _preflight(c, csrf_header, app_id, src_id).status_code == 409  # == source
        assert _preflight(c, csrf_header, app_id, tgt_id).status_code == 409  # not connected


def test_proxmox_error_is_502(tmp_path, csrf_header, bootstrap_admin):
    fake_src, fake_tgt = _fake_pair(shared_storage="pbs-ds")
    fake_tgt.fail = True  # unreachable target
    app = _make_app(tmp_path, {SRC_HOSTNAME: fake_src, TGT_HOSTNAME: fake_tgt})

    with TestClient(app) as c:
        bootstrap_admin(c)
        src_id, tgt_id, app_id = _seed(app)
        assert _preflight(c, csrf_header, app_id, tgt_id).status_code == 502


def test_route_does_not_get_shadowed_by_the_lifecycle_wildcard(tmp_path, csrf_header,
                                                                bootstrap_admin):
    """apps.py:522's WARNING: /{app_id}/{action} is registered last and would
    swallow a two-segment sibling. /migrate/preflight is three segments so it
    cannot structurally collide, but this proves the regression the WARNING
    warns about doesn't happen in practice — a 422 'action must be one of
    start, stop, restart, shutdown' would mean the wildcard ate this route."""
    fake_src, fake_tgt = _fake_pair(shared_storage="pbs-ds")
    app = _make_app(tmp_path, {SRC_HOSTNAME: fake_src, TGT_HOSTNAME: fake_tgt})

    with TestClient(app) as c:
        bootstrap_admin(c)
        src_id, tgt_id, app_id = _seed(app)
        r = _preflight(c, csrf_header, app_id, tgt_id)
        assert r.status_code == 200
        assert "strategy" in r.json()
        assert "action must be one of" not in r.text
