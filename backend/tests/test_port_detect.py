"""Guessing which port an adopted container serves its UI on.

An app installed from the store carries its port in the catalog. One adopted
by hand carries nothing, so the row has no web_port, so there is no Open
button and no way to get one short of the operator knowing the number.

Proxmox itself is no help: `pct config` describes the NIC and nothing about
listening sockets. The only place the answer exists is inside the container,
which `pct exec ss -lntpH` can reach over the transport the installer already
uses.

It is a GUESS and the tests say so: what it does is rank candidates, and the
operator picks. The ranking is the part worth pinning, because the obvious
heuristics get the common case wrong.
"""
from proxploy.services.portdetect import rank_ports


# VERBATIM `ss -lntpH` from the Proxploy-Test container on node1, 2026-08-26,
# trailing whitespace and all. It was hand-written address-first at first, from
# an awk-sliced copy of the output, and the parser built against that fixture
# matched exactly nothing when pointed at the real thing: -H drops the header
# row but keeps the state and queue columns.
PROXPLOY_TEST = """\
LISTEN 0      2048   127.0.0.1:8000 0.0.0.0:* users:(("uvicorn",pid=7319,fd=18))
LISTEN 0      100    127.0.0.1:25   0.0.0.0:* users:(("master",pid=351,fd=13))
LISTEN 0      4096   127.0.0.1:2019 0.0.0.0:* users:(("caddy",pid=8143,fd=8))
LISTEN 0      100        [::1]:25      [::]:* users:(("master",pid=351,fd=14))
LISTEN 0      4096           *:443        *:* users:(("caddy",pid=8143,fd=3))
LISTEN 0      4096           *:80         *:* users:(("caddy",pid=8143,fd=10))
LISTEN 0      4096           *:22         *:* users:(("sshd",pid=200,fd=3),("systemd",pid=1,fd=38))
"""


def test_the_first_candidate_is_the_one_a_browser_can_reach():
    """443, not 8000. This is the whole point of ranking rather than picking.

    A naive "highest port" or "the app-looking process" lands on uvicorn's
    8000, which binds 127.0.0.1 by design and can never answer a browser: the
    Open button would be built to fail. Caddy on 443 is the only thing
    externally reachable on this container.
    """
    ranked = rank_ports(PROXPLOY_TEST)
    assert ranked[0]["port"] == 443
    assert [c["port"] for c in ranked] == [443, 80]


def test_loopback_only_sockets_are_left_out_entirely():
    """Not ranked last: absent. A port bound to 127.0.0.1 is unreachable from
    the browser whatever else is true of it, so offering it is offering a
    broken answer."""
    ports = [c["port"] for c in rank_ports(PROXPLOY_TEST)]
    for unreachable in (8000, 2019, 25):
        assert unreachable not in ports


def test_the_infrastructure_ports_are_left_out():
    """ssh and smtp listen on plenty of containers and are never a web UI."""
    assert 22 not in [c["port"] for c in rank_ports(PROXPLOY_TEST)]


def test_a_plain_app_port_is_offered():
    """The ordinary case: one process, one port, bound wide."""
    ranked = rank_ports('LISTEN 0 4096 *:8096 *:* users:(("jellyfin",pid=700,fd=3))\n')
    assert [c["port"] for c in ranked] == [8096]
    assert ranked[0]["process"] == "jellyfin"


def test_https_outranks_http_which_outranks_the_rest():
    out = '*:8080 users:(("x",pid=1,fd=1))\n*:80 users:(("y",pid=2,fd=2))\n' \
          '*:443 users:(("z",pid=3,fd=3))\n'
    assert [c["port"] for c in rank_ports(out)] == [443, 80, 8080]


def test_two_app_ports_stay_in_a_fixed_order():
    """A container serving two UIs has no single right answer, so it offers
    both. Lowest first, and the same order every time: a list that reshuffles
    between runs is one the operator cannot trust."""
    out = ('LISTEN 0 1 *:9000 *:* users:(("b",pid=2,fd=2))\n'
           'LISTEN 0 1 *:8123 *:* users:(("a",pid=1,fd=1))\n')
    assert [c["port"] for c in rank_ports(out)] == [8123, 9000]


def test_ipv6_wildcards_count_as_reachable():
    """`[::]:8096` is every interface, the same as `*:8096`."""
    assert [c["port"] for c in rank_ports('LISTEN 0 1 [::]:8096 [::]:* users:(("j",pid=1,fd=1))\n')] \
        == [8096]


def test_a_specific_lan_address_counts_as_reachable():
    """Bound to the container's own LAN address rather than a wildcard: still
    something a browser on the network reaches."""
    assert [c["port"] for c in rank_ports('LISTEN 0 1 192.168.1.5:8096 0.0.0.0:* users:(("j",pid=1,fd=1))\n')] \
        == [8096]


def test_nothing_listening_is_an_empty_list_not_an_error():
    assert rank_ports("") == []


def test_junk_lines_are_skipped_rather_than_crashing():
    """ss output is not a promise. A line this cannot parse must not take the
    whole detection down with it."""
    out = 'garbage\nLISTEN 0 1 *:8096 *:* users:(("j",pid=1,fd=1))\nmore junk\n'
    assert [c["port"] for c in rank_ports(out)] == [8096]


def test_the_route_says_it_is_not_accurate(tmp_path, bootstrap_admin):
    """The caveat travels in the payload, so a client cannot present a guess as
    a fact by forgetting to."""
    import json

    from fastapi.testclient import TestClient

    from proxploy.models import App, Host, HostCredential
    from tests.fakes.ssh import FakeSSHConnection, make_fake_connect_factory
    from tests.support import make_app

    ssh = FakeSSHConnection(host_key_fingerprint="SHA256:abc",
                            stdout_lines=PROXPLOY_TEST.splitlines(),
                            stderr_lines=[], exit_status=0)
    app = make_app(tmp_path, ssh_factory=make_fake_connect_factory(ssh))
    with TestClient(app) as c:
        bootstrap_admin(c)
        with app.state.sessionmaker() as db:
            host = Host(name="host-01", address="https://10.0.0.7:8006",
                        node_name="pve1", status="connected",
                        ssh_host_key_fingerprint="SHA256:abc")
            db.add(host)
            db.commit()
            blob, ver = app.state.secretstore.encrypt(b"key")
            db.add(HostCredential(host_id=host.id, kind="ssh_key",
                                  encrypted_blob=blob, key_version=ver))
            row = App(host_id=host.id, ctid=950, name="Proxploy-Test",
                      slug="adopted-1-950")
            db.add(row)
            db.commit()
            app_id = row.id

        r = c.get(f"/api/v1/apps/{app_id}/ports")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["accurate"] is False
        assert [p["port"] for p in body["ports"]] == [443, 80]
