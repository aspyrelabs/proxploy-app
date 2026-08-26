"""The poller does not answer for a guest something else is acting on.

Reported on hardware 2026-08-25: stopping anytype-server showed Working, then
Running again, then Stopped. PVE reports the OLD status for as long as a stop
is actually running, so a poll landing inside the action wrote `running` back
over the pending state and the pill flapped.

Always possible; easy at a 5s cycle, where a poll almost always lands inside
the action rather than after it.

The fix went through the guest's status column first, and that was wrong twice
over. Writing "pending" INTO the column put a display word in the readings, and
having the poller decline to write while a guest was held deadlocked it against
busy_guests, which releases the hold by reading that very column: a container
stopped on the node sat on "Working" for ever. So both halves are pinned here
now. The column keeps taking Proxmox's answer whatever else is happening, and
the hold lives in the overlay the API puts over it.
"""
import json
from datetime import timedelta

from fastapi.testclient import TestClient

from proxploy.models import App, Host, HostCredential, Job, Vm, utcnow
from proxploy.services.lifecycle import LIFECYCLE_HOLD_S, busy_guests
from tests.fakes.pve import FakePVE
from tests.support import make_app


def _fake():
    """PVE still saying `running`, which is what it says all through a stop."""
    return FakePVE(resources=[
        {"type": "node", "node": "pve1", "status": "online", "maxcpu": 4,
         "maxmem": 8589934592},
        {"type": "lxc", "vmid": 150, "name": "anytype-server", "node": "pve1",
         "status": "running", "maxmem": 1073741824, "maxcpu": 1},
        {"type": "qemu", "vmid": 201, "name": "win11", "node": "pve1",
         "status": "running", "maxmem": 2147483648, "maxcpu": 2},
    ])


def _boot(tmp_path, ct_status="running", vm_status="running"):
    """app.state.sessionmaker only exists once the lifespan has run, so the
    TestClient context is entered and handed back to the caller to close."""
    fake = _fake()
    app = make_app(tmp_path, fake=fake)
    app.state.test_fake = fake   # so a test can change what PVE reports
    client = TestClient(app)
    client.__enter__()
    with app.state.sessionmaker() as db:
        host = Host(name="host-01", address="https://10.0.0.7:8006",
                    node_name="pve1", status="connected")
        db.add(host)
        db.commit()
        blob, ver = app.state.secretstore.encrypt(json.dumps(
            {"token_id": "proxploy@pve!mon", "token_secret": "s"}).encode())
        db.add(HostCredential(host_id=host.id, kind="api_token:monitoring",
                              encrypted_blob=blob, key_version=ver))
        a = App(host_id=host.id, ctid=150, name="anytype-server", slug="anytype",
                status_cached=ct_status)
        v = Vm(host_id=host.id, vmid=201, name="win11", status=vm_status)
        db.add_all([a, v])
        db.commit()
        return app, client, host.id, a.id, v.id


def _job(app, target_type, target_id, kind, status="running", age_s=0):
    with app.state.sessionmaker() as db:
        j = Job(kind=kind, status=status, target_type=target_type,
                target_id=target_id, params={})
        db.add(j)
        db.commit()
        if age_s:
            # started_at is what the staleness guard reads.
            j.started_at = utcnow() - timedelta(seconds=age_s)
            db.commit()


def test_a_poll_inside_a_stop_holds_the_app_without_freezing_the_reading(tmp_path):
    app, c, hid, app_id, _ = _boot(tmp_path)
    _job(app, "app", app_id, "app.stop")

    app.state.poller._poll_once(hid)

    with app.state.sessionmaker() as db:
        # Recorded: PVE says `running` all through a stop, and this column is
        # the observation. Refusing the write here is what deadlocked it.
        assert db.get(App, app_id).status_cached == "running"
        # Served: the operator sees the action, not the stale reading.
        assert busy_guests(db, utcnow())[("app", app_id)] == "pending"
    c.__exit__(None, None, None)


def test_the_same_for_a_vm(tmp_path):
    app, c, hid, _, vm_id = _boot(tmp_path)
    _job(app, "vm", vm_id, "vm.shutdown")

    app.state.poller._poll_once(hid)

    with app.state.sessionmaker() as db:
        assert db.get(Vm, vm_id).status == "running"
        assert busy_guests(db, utcnow())[("vm", vm_id)] == "pending"
    c.__exit__(None, None, None)


def test_a_stale_bulk_read_cannot_undo_a_targeted_one(tmp_path):
    """The 5 second gap, pinned.

    Measured on the lab cluster stopping adguard: the per-guest read recorded
    `stopped` at 51.7s and the hold lifted, then the wake'd cycle read
    /cluster/resources, which still said `running`, wrote that over the top
    and put the pill back to Working until the next cycle at 56.9s.

    Both are observations. The targeted one is simply NEWER, and the newer
    answer wins, which is why this is not the belief-in-the-readings-column
    mistake that `_settle_status` was.
    """
    app, c, hid, app_id, _ = _boot(tmp_path)
    # An action that finished and was confirmed by the targeted read.
    _job(app, "app", app_id, "app.stop", status="succeeded")
    with app.state.sessionmaker() as db:
        row = db.get(App, app_id)
        row.status_cached = "stopped"
        db.commit()
        job = db.query(Job).filter_by(target_id=app_id).one()
        job.finished_at = utcnow()
        db.commit()

    # The fake still reports `running`, exactly as /cluster/resources does for
    # seconds after a finished stop.
    app.state.poller._poll_once(hid)

    with app.state.sessionmaker() as db:
        assert db.get(App, app_id).status_cached == "stopped"
        assert ("app", app_id) not in busy_guests(db, utcnow())
    c.__exit__(None, None, None)


def test_a_stale_bulk_read_wins_again_once_it_is_no_longer_stale(tmp_path):
    """The override is a short window, not a permanent veto: a guest someone
    starts by hand on the node must still be picked up."""
    from datetime import timedelta

    from proxploy.services.lifecycle import FRESH_OBSERVATION_S

    app, c, hid, app_id, _ = _boot(tmp_path)
    _job(app, "app", app_id, "app.stop", status="succeeded")
    with app.state.sessionmaker() as db:
        db.get(App, app_id).status_cached = "stopped"
        job = db.query(Job).filter_by(target_id=app_id).one()
        job.finished_at = utcnow() - timedelta(seconds=FRESH_OBSERVATION_S + 5)
        db.commit()

    app.state.poller._poll_once(hid)

    with app.state.sessionmaker() as db:
        assert db.get(App, app_id).status_cached == "running"
    c.__exit__(None, None, None)


def test_the_hold_lifts_once_the_poller_sees_the_guest_stopped(tmp_path):
    """The deadlock, pinned. A guest that has actually stopped on the node must
    come out of "Working" on the next cycle, with no further job activity."""
    app, c, hid, app_id, _ = _boot(tmp_path)
    _job(app, "app", app_id, "app.stop", status="succeeded")
    with app.state.sessionmaker() as db:
        assert busy_guests(db, utcnow())[("app", app_id)] == "pending"

    # PVE now agrees the container is down.
    # Mutated in place, not rebound: FakePVE hands the same list object to its
    # cluster namespace, so a fresh list would never be seen (fakes/pve.py:887).
    for r in app.state.test_fake.resources:
        if r.get("vmid") == 150:
            r["status"] = "stopped"
    app.state.poller._poll_once(hid)

    with app.state.sessionmaker() as db:
        assert db.get(App, app_id).status_cached == "stopped"
        assert ("app", app_id) not in busy_guests(db, utcnow())
    c.__exit__(None, None, None)


def test_a_guest_with_nothing_in_flight_is_still_the_pollers_to_answer_for(tmp_path):
    """The guard is narrow on purpose: this is the normal path, and PVE is the
    truth for it."""
    app, c, hid, app_id, vm_id = _boot(tmp_path, ct_status="stopped",
                                       vm_status="stopped")

    app.state.poller._poll_once(hid)

    with app.state.sessionmaker() as db:
        assert db.get(App, app_id).status_cached == "running"
        assert db.get(Vm, vm_id).status == "running"
    c.__exit__(None, None, None)


def test_a_finished_job_releases_the_guest_again(tmp_path):
    """Only queued/running hold it."""
    app, c, hid, app_id, _ = _boot(tmp_path, ct_status="stopped")
    _job(app, "app", app_id, "app.stop", status="succeeded")

    app.state.poller._poll_once(hid)

    with app.state.sessionmaker() as db:
        assert db.get(App, app_id).status_cached == "running"
    c.__exit__(None, None, None)


def test_a_backup_running_on_a_guest_does_not_freeze_its_status(tmp_path):
    """Only the lifecycle verbs hold a guest. A backup does not change what a
    guest IS, so the poller stays the authority through one."""
    app, c, hid, app_id, _ = _boot(tmp_path, ct_status="stopped")
    _job(app, "app", app_id, "backup.run")

    app.state.poller._poll_once(hid)

    with app.state.sessionmaker() as db:
        assert db.get(App, app_id).status_cached == "running"
    c.__exit__(None, None, None)


def test_a_job_stuck_past_the_ceiling_stops_holding_the_status(tmp_path):
    """A hold that outlives its job would freeze a guest's status for ever.

    Five minutes is the ceiling: past it the poller takes the guest back and
    reports what Proxmox says, whatever the job row still claims.
    """
    app, c, hid, app_id, _ = _boot(tmp_path, ct_status="pending")
    _job(app, "app", app_id, "app.stop", age_s=LIFECYCLE_HOLD_S + 60)

    app.state.poller._poll_once(hid)

    with app.state.sessionmaker() as db:
        assert db.get(App, app_id).status_cached == "running"
    c.__exit__(None, None, None)

