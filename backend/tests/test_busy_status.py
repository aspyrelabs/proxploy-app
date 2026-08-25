"""A guest with an action in flight reads as working, from the API itself.

The optimistic patch the browser applies on click is not enough on its own:
the DATABASE still holds the old status the whole time (nothing server-side
ever wrote "pending"), so any refetch during the action answered `running` and
put the pill straight back. Reported twice on hardware, once for stopping
anytype-server and once for deleting it, as "it went back to running and then
eventually stopped".

Fixing the poller was not enough and this is why: the poller was not the thing
writing `running`, it was already there.
"""
import json
from datetime import timedelta

from fastapi.testclient import TestClient

from proxploy.models import App, Host, HostCredential, Job, Vm, utcnow
from proxploy.services.lifecycle import LIFECYCLE_HOLD_S
from tests.support import make_app


def _seed(app):
    with app.state.sessionmaker() as db:
        host = Host(name="host-01", address="https://10.0.0.7:8006",
                    node_name="pve1", status="connected")
        db.add(host)
        db.commit()
        blob, ver = app.state.secretstore.encrypt(json.dumps(
            {"token_id": "proxploy@pve!mon", "token_secret": "s"}).encode())
        db.add(HostCredential(host_id=host.id, kind="api_token:monitoring",
                              encrypted_blob=blob, key_version=ver))
        a = App(host_id=host.id, ctid=110, name="anytype-server", slug="anytype",
                status_cached="running")
        v = Vm(host_id=host.id, vmid=201, name="win11", status="running")
        db.add_all([a, v])
        db.commit()
        return a.id, v.id


def _job(app, target_type, target_id, kind, status="running", age_s=0):
    with app.state.sessionmaker() as db:
        j = Job(kind=kind, status=status, target_type=target_type,
                target_id=target_id, params={})
        db.add(j)
        db.commit()
        if age_s:
            j.started_at = utcnow() - timedelta(seconds=age_s)
            db.commit()


def _app_status(c, app_id):
    return next(r["status"] for r in c.get("/api/v1/apps").json() if r["id"] == app_id)


def _vm_status(c, vm_id):
    return next(r["status"] for r in c.get("/api/v1/vms").json() if r["id"] == vm_id)


def test_an_app_being_stopped_reads_as_working_not_running(tmp_path, bootstrap_admin):
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        app_id, _ = _seed(app)
        assert _app_status(c, app_id) == "running"
        _job(app, "app", app_id, "app.stop")
        assert _app_status(c, app_id) == "pending"


def test_an_app_being_deleted_says_removing_not_running(tmp_path, bootstrap_admin):
    """The row stayed in the list looking healthy for the couple of seconds
    between the job finishing and the poller reaping it.

    Its own word, not the shared "pending": a removal is the one action that
    ends with the row gone, and "Working" on a thing that is about to
    disappear tells you less than "Removing" does."""
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        app_id, _ = _seed(app)
        _job(app, "app", app_id, "app.uninstall")
        assert _app_status(c, app_id) == "removing"


def test_a_vm_being_shut_down_reads_as_working(tmp_path, bootstrap_admin):
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        _, vm_id = _seed(app)
        _job(app, "vm", vm_id, "vm.shutdown")
        assert _vm_status(c, vm_id) == "pending"


def test_a_settled_job_gives_the_status_back(tmp_path, bootstrap_admin):
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        app_id, _ = _seed(app)
        _job(app, "app", app_id, "app.stop", status="succeeded")
        assert _app_status(c, app_id) == "running"


def test_a_backup_on_a_guest_does_not_make_it_read_as_working(tmp_path,
                                                              bootstrap_admin):
    """A backup does not change what a guest IS, so it says nothing here."""
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        app_id, _ = _seed(app)
        _job(app, "app", app_id, "backup.run")
        assert _app_status(c, app_id) == "running"


def test_a_job_stuck_past_the_ceiling_gives_the_status_back(tmp_path,
                                                            bootstrap_admin):
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        app_id, _ = _seed(app)
        _job(app, "app", app_id, "app.stop", age_s=LIFECYCLE_HOLD_S + 60)
        assert _app_status(c, app_id) == "running"
