"""A poll cycle that loses only its metrics read is not an unreachable host.

Found on real hardware: a privilege-separated token could read
/cluster/resources but not /nodes/<n>/rrddata, which needs Sys.Audit. The
403 propagated out of _poll_once, _host_loop caught it with a bare
`except Exception`, and a node that was answering perfectly well was
reported to the operator as "unreachable", with nothing logged anywhere
saying why.
"""
import json

from proxploy.models import Host, HostCredential


def _app_with(tmp_path, fake):
    """app.state.sessionmaker only exists once the lifespan has run, so the
    TestClient context is entered and handed back to the caller to close."""
    from fastapi.testclient import TestClient
    from tests.support import make_app, seed_host_row

    app = make_app(tmp_path, fake=fake)
    c = TestClient(app)
    c.__enter__()
    with app.state.sessionmaker() as db:
        h = seed_host_row(db)
        blob, ver = app.state.secretstore.encrypt(json.dumps(
            {"token_id": "proxploy@pve!mon", "token_secret": "s"}).encode())
        db.add(HostCredential(host_id=h.id, kind="api_token:monitoring",
                              encrypted_blob=blob, key_version=ver,
                              public_meta="proxploy@pve!mon"))
        db.commit()
        return app, c, h.id


def _host(app, host_id) -> Host:
    with app.state.sessionmaker() as db:
        return db.get(Host, host_id)


def test_a_metrics_403_does_not_make_the_host_unreachable(tmp_path):
    from tests.fakes.pve import FakePVE

    fake = FakePVE(resources=[{"type": "node", "node": "pve1", "status": "online",
                               "maxcpu": 4, "maxmem": 8589934592}],
                   rrd_fail=True)
    app, c, host_id = _app_with(tmp_path, fake)

    # Must not raise: raising is what _host_loop turns into "unreachable".
    app.state.poller._poll_once(host_id)

    h = _host(app, host_id)
    assert h.status == "connected", h.status
    # The half of the cycle that did work must still land, or the host stays
    # nameless on every page that reads node_name.
    assert h.node_name == "pve1"


def test_the_lost_metrics_read_is_recorded_as_a_reason(tmp_path):
    from tests.fakes.pve import FakePVE

    fake = FakePVE(resources=[{"type": "node", "node": "pve1", "status": "online",
                               "maxcpu": 4, "maxmem": 8589934592}],
                   rrd_fail=True)
    app, c, host_id = _app_with(tmp_path, fake)
    app.state.poller._poll_once(host_id)

    h = _host(app, host_id)
    assert h.last_error, "a degraded cycle must say what it lost"
    assert "rrddata" in h.last_error or "metrics" in h.last_error.lower()


def test_a_clean_cycle_clears_a_previous_reason(tmp_path):
    from tests.fakes.pve import FakePVE

    fake = FakePVE(resources=[{"type": "node", "node": "pve1", "status": "online",
                               "maxcpu": 4, "maxmem": 8589934592}],
                   rrd_fail=True)
    app, c, host_id = _app_with(tmp_path, fake)
    app.state.poller._poll_once(host_id)
    assert _host(app, host_id).last_error

    fake.rrd_fail = False
    app.state.poller._poll_once(host_id)
    assert _host(app, host_id).last_error is None


def test_a_real_connection_failure_still_records_why(tmp_path):
    from tests.fakes.pve import FakePVE

    fake = FakePVE(fail=True)
    app, c, host_id = _app_with(tmp_path, fake)

    app.state.poller._mark_unreachable(host_id, "boom: connection refused")
    h = _host(app, host_id)
    assert h.status == "unreachable"
    # "unreachable" with a blank reason is what made this undiagnosable.
    assert "connection refused" in h.last_error
