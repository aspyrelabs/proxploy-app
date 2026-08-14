"""An app whose CT was destroyed outside Proxploy stops being an installed app.

`pct destroy 150` on the node leaves the App row behind: it kept showing on
the apps grid and in the per-host counts on the hosts page, pointing at a
container that no longer exists.

The whole risk of fixing that is the false positive. "Absent from
/cluster/resources" is what a destroyed CT looks like, and also what a
rebooting node, a degraded cycle and a downed cluster member look like, so
most of the tests below are about NOT deleting anything.
"""
import json
from datetime import timedelta
from pathlib import Path

FIX = Path(__file__).parent / "fixtures" / "pve"

REAP_AFTER = timedelta(seconds=901)  # just past pollers.APP_REAP_AFTER_S


def _resources(drop_ctid=None, node_status="online"):
    rows = json.loads((FIX / "cluster_resources_basic.json").read_text())
    out = []
    for r in rows:
        if r.get("type") == "lxc" and r.get("vmid") == drop_ctid:
            continue
        if r.get("type") == "node":
            r = {**r, "status": node_status}
        out.append(r)
    return out


def _seed(tmp_path):
    from proxploy.models import App, utcnow
    from tests.support import make_db, seed_host_row

    db = make_db(tmp_path)
    host = seed_host_row(db)
    db.add(App(host_id=host.id, ctid=150, name="Immich", slug="immich",
               status_cached="running"))
    db.commit()
    return db, host, utcnow()


def _cycle(db, host, now, *, drop_ctid=150, node_status="online", degraded=False):
    from proxploy.pollers import ingest_cycle

    return ingest_cycle(db, host, _resources(drop_ctid, node_status), {}, now,
                        degraded=degraded)


def _app(db, host):
    from proxploy.models import App

    return db.query(App).filter_by(host_id=host.id, ctid=150).one_or_none()


def test_a_ct_that_is_really_gone_is_eventually_reaped(tmp_path):
    db, host, t0 = _seed(tmp_path)

    _cycle(db, host, t0)                       # arms the countdown
    assert _app(db, host) is not None, "one missed cycle must never reap"
    assert _app(db, host).missing_since == t0

    res = _cycle(db, host, t0 + REAP_AFTER)    # absence has now persisted
    assert _app(db, host) is None

    # The UI is told twice on purpose: the app event drops the row from the
    # apps caches, the host event is the only thing that invalidates the
    # per-host app counts behind the hosts page node cards.
    assert ("resource", {"type": "app", "id": 1, "change": "removed"}) in res.events
    assert ("resource", {"type": "host", "id": host.id,
                         "change": "apps"}) in res.events


def test_the_reap_is_audited(tmp_path):
    from proxploy.models import AuditEvent

    db, host, t0 = _seed(tmp_path)
    _cycle(db, host, t0)
    _cycle(db, host, t0 + REAP_AFTER)

    ev = db.query(AuditEvent).filter_by(action="app.reaped").one()
    assert ev.actor_type == "system" and ev.params["ctid"] == 150


def test_a_degraded_cycle_never_reaps(tmp_path):
    """The one that matters. A cycle that lost part of its read is not
    evidence of anything, no matter how long the app has been missing."""
    db, host, t0 = _seed(tmp_path)

    _cycle(db, host, t0)                       # one good cycle arms it
    for i in range(1, 20):
        _cycle(db, host, t0 + REAP_AFTER * i, degraded=True)
        assert _app(db, host) is not None, "a degraded cycle reaped an app"


def test_a_degraded_cycle_does_not_even_arm_the_countdown(tmp_path):
    db, host, t0 = _seed(tmp_path)

    _cycle(db, host, t0, degraded=True)
    assert _app(db, host).missing_since is None


def test_a_downed_cluster_member_never_reaps(tmp_path):
    """A node going offline takes all of its guests out of
    /cluster/resources, on a cycle that is otherwise indistinguishable from a
    healthy one. App rows carry no node, so the whole cycle is distrusted."""
    db, host, t0 = _seed(tmp_path)

    for i in range(20):
        _cycle(db, host, t0 + REAP_AFTER * i, node_status="offline")
        assert _app(db, host) is not None, "a node reboot reaped an app"
    assert _app(db, host).missing_since is None


def test_an_empty_resource_list_never_reaps(tmp_path):
    from proxploy.pollers import ingest_cycle

    db, host, t0 = _seed(tmp_path)
    for i in range(20):
        ingest_cycle(db, host, [], {}, t0 + REAP_AFTER * i)
        assert _app(db, host) is not None, "a truncated read reaped an app"


def test_a_flapping_host_still_reaps_a_genuinely_gone_ct(tmp_path):
    """Degraded cycles in the middle must not RESET the countdown either, or a
    host with a permanently 403ing rrddata read would never reap anything."""
    db, host, t0 = _seed(tmp_path)

    _cycle(db, host, t0)
    _cycle(db, host, t0 + timedelta(seconds=60), degraded=True)
    _cycle(db, host, t0 + timedelta(seconds=120), node_status="offline")
    _cycle(db, host, t0 + REAP_AFTER)
    assert _app(db, host) is None


def test_the_ct_coming_back_clears_the_countdown(tmp_path):
    """A CT that was merely stopped-and-hidden, or a node that came back, must
    reset the app to a normal live app."""
    db, host, t0 = _seed(tmp_path)

    _cycle(db, host, t0)
    assert _app(db, host).missing_since == t0

    _cycle(db, host, t0 + timedelta(seconds=60), drop_ctid=None)
    a = _app(db, host)
    assert a.missing_since is None and a.status_cached == "running"

    # ...and the clock starts over rather than resuming.
    _cycle(db, host, t0 + REAP_AFTER)
    assert _app(db, host) is not None


def test_an_unreachable_host_never_reaps(tmp_path):
    """The end-to-end version: the node stops answering entirely, which is
    what a reboot looks like. _poll_once raises, ingest_cycle never runs, and
    the app is untouched however many cycles go by."""
    from proxploy.models import App, HostCredential
    from tests.support import make_app, seed_host_row

    from fastapi.testclient import TestClient
    from tests.fakes.pve import FakePVE

    fake = FakePVE(resources=_resources())
    app = make_app(tmp_path, fake=fake)
    with TestClient(app):
        with app.state.sessionmaker() as db:
            h = seed_host_row(db)
            blob, ver = app.state.secretstore.encrypt(json.dumps(
                {"token_id": "proxploy@pve!mon", "token_secret": "s"}).encode())
            db.add(HostCredential(host_id=h.id, kind="api_token:monitoring",
                                  encrypted_blob=blob, key_version=ver,
                                  public_meta="proxploy@pve!mon"))
            db.add(App(host_id=h.id, ctid=150, name="Immich", slug="immich"))
            db.commit()
            host_id = h.id

        fake.fail = True
        for _ in range(20):
            try:
                app.state.poller._poll_once(host_id)
            except Exception:  # noqa: BLE001  (what _host_loop does)
                pass
            app.state.poller._mark_unreachable(host_id, "boom")

        with app.state.sessionmaker() as db:
            a = db.query(App).filter_by(host_id=host_id).one()
            assert a.missing_since is None
            assert db.get(type(a), a.id) is not None
