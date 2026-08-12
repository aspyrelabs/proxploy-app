"""App uninstall and reconfigure (PXP-17).

Never assigned to any phase, so no phase closed without them and nothing
flagged their absence: you could install an app onto a container and then
never remove or resize it. The authz matrix already carried ("app", "remove")
and ("app", "configure"), so only the routes were missing.
"""
import json

from proxploy.models import App, Host, HostCredential, Job


def _seeded(tmp_path, fake=None):
    from fastapi.testclient import TestClient
    from tests.support import make_app, seed_host_row

    app = make_app(tmp_path, fake=fake)
    c = TestClient(app)

    def seed():
        with app.state.sessionmaker() as db:
            h = seed_host_row(db)
            if fake is not None:
                blob, ver = app.state.secretstore.encrypt(json.dumps(
                    {"token_id": "proxploy@pve!t", "token_secret": "s"}).encode())
                db.add(HostCredential(host_id=h.id, kind="api_token:lifecycle",
                                      encrypted_blob=blob, key_version=ver,
                                      public_meta="proxploy@pve!t"))
            row = App(host_id=h.id, ctid=150, name="Immich", slug="immich",
                      status_cached="running")
            db.add(row)
            db.commit()
            return row.id
    return app, c, seed


# --- uninstall ------------------------------------------------------------

def test_uninstall_without_the_typed_name_is_refused(tmp_path, csrf_header,
                                                     bootstrap_admin):
    """Destroy is irreversible, so the guard is on the operation, not just on
    Proxploy's own container the way the lifecycle verbs do it."""
    app, c, seed = _seeded(tmp_path)
    with c:
        bootstrap_admin(c)
        app_id = seed()
        r = c.request("DELETE", f"/api/v1/apps/{app_id}", json={},
                      headers=csrf_header(c))
        assert r.status_code == 409
        assert r.json()["error"] == "confirm_required"
        assert r.json()["confirm_phrase"] == "Immich"
        with app.state.sessionmaker() as db:
            assert db.get(App, app_id) is not None, "refused call must not delete"


def test_uninstall_with_the_wrong_name_is_refused(tmp_path, csrf_header,
                                                  bootstrap_admin):
    app, c, seed = _seeded(tmp_path)
    with c:
        bootstrap_admin(c)
        app_id = seed()
        r = c.request("DELETE", f"/api/v1/apps/{app_id}",
                      json={"confirm": "immich"}, headers=csrf_header(c))
        assert r.status_code == 409, "confirmation must be exact, not case-folded"


def test_uninstall_with_the_name_enqueues_a_job(tmp_path, csrf_header,
                                                bootstrap_admin):
    app, c, seed = _seeded(tmp_path)
    with c:
        bootstrap_admin(c)
        app_id = seed()
        r = c.request("DELETE", f"/api/v1/apps/{app_id}",
                      json={"confirm": "Immich"}, headers=csrf_header(c))
        assert r.status_code == 200
        with app.state.sessionmaker() as db:
            job = db.get(Job, r.json()["job"]["id"])
            assert job.kind == "app.uninstall"
            # The row survives until the job proves PVE destroyed the CT.
            assert db.get(App, app_id) is not None


def test_keep_ct_forgets_the_app_without_touching_pve(tmp_path, csrf_header,
                                                      bootstrap_admin):
    """The inverse of adopt: the container keeps running, Proxploy stops
    tracking it. No confirmation, because nothing is destroyed."""
    app, c, seed = _seeded(tmp_path)
    with c:
        bootstrap_admin(c)
        app_id = seed()
        r = c.request("DELETE", f"/api/v1/apps/{app_id}", json={"keep_ct": True},
                      headers=csrf_header(c))
        assert r.status_code == 200 and r.json() == {"removed": True, "ct_kept": True}
        with app.state.sessionmaker() as db:
            assert db.get(App, app_id) is None
        audit = c.get("/api/v1/audit", params={"action": "app.forget"}).json()
        assert audit and audit[0]["params"]["ctid"] == 150


def test_uninstall_of_a_missing_app_is_404(tmp_path, csrf_header, bootstrap_admin):
    app, c, seed = _seeded(tmp_path)
    with c:
        bootstrap_admin(c)
        seed()
        r = c.request("DELETE", "/api/v1/apps/9999", json={"confirm": "x"},
                      headers=csrf_header(c))
        assert r.status_code == 404


# --- the job itself -------------------------------------------------------

def test_uninstall_job_stops_before_destroying_and_then_forgets_the_row(tmp_path):
    """Ordering is the whole point.

    PVE refuses to destroy a running container, so stop must come first; and
    the row must outlive the destroy, because a row deleted before a failed
    destroy leaves an orphaned CT with no route back through the UI.
    """
    import asyncio

    from proxploy.jobs import JobBackend
    from tests.fakes.pve import FakePVE
    from tests.support import make_job_app

    async def run():
        fake = FakePVE()
        app = make_job_app(tmp_path, fake=fake)
        import proxploy.services.lifecycle  # noqa: F401  (registers handlers)
        backend = JobBackend(app)
        with app.state.sessionmaker() as db:
            host = Host(name="host-01", address="https://10.0.0.7:8006",
                        node_name="pve1", status="connected")
            db.add(host); db.commit()
            blob, ver = app.state.secretstore.encrypt(json.dumps(
                {"token_id": "proxploy@pve!t", "token_secret": "s"}).encode())
            db.add(HostCredential(host_id=host.id, kind="api_token:lifecycle",
                                  encrypted_blob=blob, key_version=ver,
                                  public_meta="proxploy@pve!t"))
            row = App(host_id=host.id, ctid=150, name="Immich", slug="immich")
            db.add(row); db.commit()
            app_id, host_id = row.id, host.id
            job_id = backend.enqueue(db, kind="app.uninstall", target_type="app",
                                     target_id=app_id,
                                     params={"target_id": app_id}).id
        await backend.wait(job_id, timeout=10)

        assert fake.actions == [("lxc", 150, "stop"), ("lxc", 150, "destroy")]
        assert fake.guest_deletes == [("lxc", "pve1", 150)]
        with app.state.sessionmaker() as db:
            assert db.get(Job, job_id).status == "succeeded"
            assert db.get(App, app_id) is None, "row must be gone once PVE confirms"
            assert db.get(Host, host_id) is not None, "the host is not the target"

    asyncio.run(run())


# --- reconfigure ----------------------------------------------------------

def test_reconfigure_sends_resources_to_pve_and_records_the_change(tmp_path,
                                                                   csrf_header,
                                                                   bootstrap_admin):
    from tests.fakes.pve import FakePVE

    fake = FakePVE()
    app, c, seed = _seeded(tmp_path, fake=fake)
    with c:
        bootstrap_admin(c)
        app_id = seed()
        r = c.patch(f"/api/v1/apps/{app_id}", json={"cores": 4, "memory_mb": 2048},
                    headers=csrf_header(c))
        assert r.status_code == 200
        assert r.json()["changed"] == {"cores": 4, "memory": 2048}
        assert fake.config_updates, "the resize must actually reach PVE"
        audit = c.get("/api/v1/audit", params={"action": "app.reconfigure"}).json()
        assert audit and audit[0]["params"]["changed"] == ["cores", "memory"]


def test_reconfigure_metadata_only_never_calls_pve(tmp_path, csrf_header,
                                                   bootstrap_admin):
    """Renaming an app or fixing its web port is Proxploy's own bookkeeping;
    reaching for the node to do it would be a needless failure mode."""
    from tests.fakes.pve import FakePVE

    fake = FakePVE()
    app, c, seed = _seeded(tmp_path, fake=fake)
    with c:
        bootstrap_admin(c)
        app_id = seed()
        r = c.patch(f"/api/v1/apps/{app_id}",
                    json={"name": "Photos", "web_port": 2283},
                    headers=csrf_header(c))
        assert r.status_code == 200
        assert not fake.config_updates
        with app.state.sessionmaker() as db:
            row = db.get(App, app_id)
            assert row.name == "Photos" and row.web_port == 2283


def test_reconfigure_rejects_nonsense_resources(tmp_path, csrf_header,
                                                bootstrap_admin):
    app, c, seed = _seeded(tmp_path)
    with c:
        bootstrap_admin(c)
        app_id = seed()
        for payload in ({"cores": 0}, {"memory_mb": 8}, {"swap_mb": -1}):
            r = c.patch(f"/api/v1/apps/{app_id}", json=payload,
                        headers=csrf_header(c))
            assert r.status_code == 422, payload


def test_reconfigure_with_an_empty_body_is_422_not_a_silent_noop(tmp_path,
                                                                 csrf_header,
                                                                 bootstrap_admin):
    app, c, seed = _seeded(tmp_path)
    with c:
        bootstrap_admin(c)
        app_id = seed()
        r = c.patch(f"/api/v1/apps/{app_id}", json={}, headers=csrf_header(c))
        assert r.status_code == 422
