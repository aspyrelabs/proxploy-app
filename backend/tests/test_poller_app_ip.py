"""ip_cached: the poller is the only thing that writes it.

The column shipped in the very first migration and nothing ever filled it in,
so GET /apps reported every app's address as unknown, forever. /cluster/resources
carries no address on an lxc row (confirmed on PVE 9.2.10, 2026-08-20), so this
costs a per-container call and the tests below are mostly about how rarely it is
allowed to make one, and about never turning a known address into "unknown"
because nobody could be asked.
"""
import json
from datetime import timedelta
from pathlib import Path

FIX = Path(__file__).parent / "fixtures" / "pve"

# What PVE 9.2.10 actually answers on /nodes/{node}/lxc/{vmid}/interfaces,
# trimmed to the keys the code reads. Loopback is first in the real answer too.
INTERFACES = [
    {"name": "lo", "hwaddr": "00:00:00:00:00:00",
     "inet": "127.0.0.1/8", "inet6": "::1/128"},
    {"name": "eth0", "hwaddr": "bc:24:11:57:92:21",
     "inet": "192.168.50.179/24",
     "inet6": "fe80::be24:11ff:fe57:9221/64"},
]


class FakeClient:
    """Counts calls, because "does not ask every cycle" is the whole point."""

    def __init__(self, answer=INTERFACES):
        self.answer = answer
        self.calls = []

    def lxc_interfaces(self, node, vmid):
        self.calls.append((node, vmid))
        return self.answer

    # The VM side of the same cycle. The basic resources fixture carries a
    # qemu row, so ingest_cycle reaches for these two as well. Both answer the
    # way an unhelpful PVE does, which keeps these tests about addresses.
    def agent_fsinfo(self, node, vmid):
        """(False, None) is the ordinary answer for a guest with no agent:
        Proxmox says there is none, so there are no bytes to report."""
        return False, None

    def guest_config(self, kind, node, vmid):
        """No ostype key, so os_type stays NULL and nothing here depends on it."""
        return {}


def _resources(status="running"):
    rows = json.loads((FIX / "cluster_resources_basic.json").read_text())
    return [{**r, "status": status} if r.get("type") == "lxc" else r
            for r in rows]


def _seed(tmp_path, ip=None):
    from proxploy.models import App, utcnow
    from tests.support import make_db, seed_host_row

    db = make_db(tmp_path)
    host = seed_host_row(db)
    db.add(App(host_id=host.id, ctid=150, name="Immich", slug="immich",
               status_cached="running", ip_cached=ip))
    db.commit()
    return db, host, utcnow()


def _cycle(db, host, now, client, checked, status="running"):
    from proxploy.pollers import ingest_cycle

    return ingest_cycle(db, host, _resources(status), {}, now,
                        client=client, ip_checked=checked)


def _app(db, host):
    from proxploy.models import App

    return db.query(App).filter_by(host_id=host.id, ctid=150).one()


def test_a_running_container_gets_its_address_cached(tmp_path):
    db, host, now = _seed(tmp_path)
    client = FakeClient()

    res = _cycle(db, host, now, client, {})

    # Bare address, no prefix length: this is what an operator copies into a
    # browser. Loopback and link-local are dropped, so eth0's v4 wins.
    assert _app(db, host).ip_cached == "192.168.50.179"
    assert client.calls == [("pve1", 150)]
    assert ("resource", {"type": "app", "id": _app(db, host).id,
                         "change": "ip"}) in res.events


def test_a_known_address_is_not_re_read_every_cycle(tmp_path):
    """30 s x every container x every host is exactly the per-guest call the
    poll budget forbids; a known address is re-checked on a slow cadence."""
    db, host, now = _seed(tmp_path)
    client, checked = FakeClient(), {}

    for i in range(5):
        _cycle(db, host, now + timedelta(seconds=30 * i), client, checked)

    assert client.calls == [("pve1", 150)]


def test_a_renumbered_container_converges_on_the_slow_cadence(tmp_path):
    from proxploy.pollers import APP_IP_REFRESH_INTERVAL_S

    db, host, now = _seed(tmp_path)
    client, checked = FakeClient(), {}
    _cycle(db, host, now, client, checked)
    assert _app(db, host).ip_cached == "192.168.50.179"

    client.answer = [{**INTERFACES[0]},
                     {**INTERFACES[1], "inet": "192.168.50.201/24"}]
    later = now + timedelta(seconds=APP_IP_REFRESH_INTERVAL_S + 1)
    res = _cycle(db, host, later, client, checked)

    assert _app(db, host).ip_cached == "192.168.50.201"
    assert len(client.calls) == 2
    assert ("resource", {"type": "app", "id": _app(db, host).id,
                         "change": "ip"}) in res.events


def test_an_unknown_address_is_retried_on_the_very_next_cycle(tmp_path):
    """A freshly adopted app, or a DHCP lease that has not landed yet, must not
    wait a quarter of an hour for its first address."""
    db, host, now = _seed(tmp_path)
    client, checked = FakeClient(answer=[INTERFACES[0]]), {}

    _cycle(db, host, now, client, checked)
    assert _app(db, host).ip_cached is None

    client.answer = INTERFACES
    _cycle(db, host, now + timedelta(seconds=30), client, checked)
    assert _app(db, host).ip_cached == "192.168.50.179"


def test_a_stopped_container_has_no_address(tmp_path):
    """We asked and got a real answer, so this is knowledge, not a gap."""
    db, host, now = _seed(tmp_path, ip="192.168.50.179")
    client, checked = FakeClient(), {}

    _cycle(db, host, now, client, checked, status="stopped")

    assert _app(db, host).ip_cached is None
    assert client.calls == []          # a stopped CT is not worth a call


def test_pve_refusing_to_answer_leaves_the_last_known_address_alone(tmp_path):
    """lxc_interfaces returns None for "cannot tell". Overwriting a real
    address with unknown because one read failed is the failure mode this whole
    column had before it was ever written to."""
    db, host, now = _seed(tmp_path, ip="192.168.50.179")
    client, checked = FakeClient(answer=None), {}

    res = _cycle(db, host, now, client, checked)

    assert _app(db, host).ip_cached == "192.168.50.179"
    # Nothing was learned, so nothing is republished, and the failed read does
    # not count as a check: the next cycle tries again.
    assert not [e for e in res.events if e[1].get("change") == "ip"]
    assert checked == {}


def test_an_unreachable_host_does_not_wipe_a_known_address(tmp_path):
    """_mark_unreachable nulls every live reading on the app row. An address is
    not a live reading: the container almost certainly still holds it, and the
    host being unreachable is precisely when knowing where the app lives is
    worth the most."""
    from fastapi.testclient import TestClient

    from proxploy.models import App
    from tests.support import make_app, seed_host_row

    # app.state.sessionmaker only exists once the lifespan has run.
    app = make_app(tmp_path)
    client = TestClient(app)
    client.__enter__()
    with app.state.sessionmaker() as db:
        host = seed_host_row(db)
        db.add(App(host_id=host.id, ctid=150, name="Immich", slug="immich",
                   status_cached="running", cpu_pct_cached=12.0,
                   ip_cached="192.168.50.179"))
        db.commit()
        host_id = host.id

    app.state.poller._mark_unreachable(host_id, "boom")

    with app.state.sessionmaker() as db:
        row = db.query(App).filter_by(host_id=host_id, ctid=150).one()
        assert row.status_cached == "unknown"
        assert row.cpu_pct_cached is None
        assert row.ip_cached == "192.168.50.179"
    client.__exit__(None, None, None)
