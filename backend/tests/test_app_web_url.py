"""GET /apps/{id}/web-url: the scheme is asked of the app, never assumed.

The bug this file guards: Actual Budget serves https on port 5006 (its
community-scripts install script calls `create_self_signed_cert`), the catalog
we ingest carries a port and no protocol, and every app row said "http"
because install and adopt wrote that string unconditionally. Open sent the
operator to `http://<ip>:5006` and the page failed to load.

`test_probe_*` run against real sockets on loopback, one wrapped in TLS and
one not, because a mocked probe would pass just as happily against code that
hardcoded "http" again.
"""
import datetime
import json
import socket
import ssl
import threading

import pytest
from fastapi.testclient import TestClient

from proxploy.models import App, CatalogEntry, Host, HostCredential
from proxploy.services import webui
from tests.support import make_app, seed_snapshot


# --- the probe itself, against real listening sockets ----------------------

def _self_signed(tmp_path):
    """A certificate exactly as untrustworthy as the ones the apps carry."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder()
            .subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=1))
            .sign(key, hashes.SHA256()))
    cert_path, key_path = tmp_path / "t.crt", tmp_path / "t.key"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption()))
    return str(cert_path), str(key_path)


def _serve(tls_files=None):
    """One-shot listener on loopback. Returns its port; closes on its own."""
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]

    def run():
        try:
            conn, _ = srv.accept()
            if tls_files:
                ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                ctx.load_cert_chain(*tls_files)
                try:
                    with ctx.wrap_socket(conn, server_side=True) as tls:
                        tls.recv(1)
                except OSError:
                    pass
            else:
                # A plain HTTP server's answer to a ClientHello: it is not a
                # request line, so the connection goes away without a
                # handshake ever completing.
                conn.recv(1)
                conn.close()
        except OSError:
            pass
        finally:
            srv.close()

    threading.Thread(target=run, daemon=True).start()
    return port


@pytest.fixture(autouse=True)
def _allow_loopback(monkeypatch):
    # The SSRF guard the probe shares refuses loopback unless an operator opts
    # in, and every listener in this file is on 127.0.0.1.
    monkeypatch.setattr("proxploy.services.proxmox.ALLOW_LOOPBACK_TARGET", True)


def test_probe_says_https_for_a_tls_app_with_a_self_signed_cert(tmp_path):
    port = _serve(_self_signed(tmp_path))
    assert webui.probe_scheme("127.0.0.1", port, timeout=5.0) == "https"


def test_probe_says_http_for_a_plain_app(tmp_path):
    port = _serve()
    assert webui.probe_scheme("127.0.0.1", port, timeout=5.0) == "http"


def test_probe_says_nothing_at_all_when_the_port_does_not_answer():
    # Not "http". A stopped container is not evidence of plain HTTP, and
    # collapsing this into a default is the whole bug.
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    port = srv.getsockname()[1]
    srv.close()
    assert webui.probe_scheme("127.0.0.1", port, timeout=2.0) is None


def test_the_operator_s_own_value_is_never_probed_over(monkeypatch):
    monkeypatch.setattr(webui, "probe_scheme",
                        lambda *a, **k: pytest.fail("probed an app already set"))
    row = App(host_id=1, ctid=1, name="x", slug="x", web_protocol="https")
    assert webui.scheme_for(row, "10.0.0.5", 5006) == ("https", "set on the app")


# --- the endpoint ----------------------------------------------------------

def _fake():
    from tests.fakes.pve import FakePVE

    f = FakePVE()
    f.guest_configs = {("lxc", 109): {
        "hostname": "actualbudget",
        "net0": "name=eth0,bridge=vmbr0,hwaddr=BC:24:11:00:11:22,ip=dhcp,type=veth"}}
    # A container on DHCP: the config says the word "dhcp", the lease is what
    # PVE reports here, and the lease is what a tab must be pointed at.
    f.lxc_interfaces = {109: [{"name": "eth0", "hwaddr": "BC:24:11:00:11:22",
                               "inet": "10.9.9.9/24"}]}
    return f


def _seed(app, *, port=5006, web_port=None, web_protocol=None):
    with app.state.sessionmaker() as db:
        host = Host(name="host-01", address="https://10.0.0.9:8006", node_name="pve1",
                    status="connected", pve_version="8.4.1")
        db.add(host)
        db.commit()
        blob, ver = app.state.secretstore.encrypt(json.dumps(
            {"token_id": "proxploy@pve!mon", "token_secret": "s3cret"}).encode())
        db.add(HostCredential(host_id=host.id, kind="api_token:monitoring",
                              encrypted_blob=blob, key_version=ver))
        db.add(CatalogEntry(slug="actualbudget", name="Actual Budget",
                            entry_type="ct", script_path="ct/actualbudget.sh",
                            port=port))
        a = App(host_id=host.id, ctid=109, name="Actual Budget",
                slug="actual-budget", catalog_slug="actualbudget",
                web_port=web_port, web_protocol=web_protocol, web_path="/")
        db.add(a)
        db.commit()
        return host.id, a.id


def test_an_https_app_opens_at_https_even_though_the_catalog_never_said_so(
        tmp_path, monkeypatch, bootstrap_admin):
    """The reported bug, end to end. Upstream's record for this app is
    `"port": 5006` with no protocol field and empty notes, so nothing short of
    asking the app can know it serves TLS."""
    monkeypatch.setattr(webui, "probe_scheme", lambda addr, port, **k: "https")
    app = make_app(tmp_path, fake=_fake())
    with TestClient(app) as c:
        bootstrap_admin(c)
        host_id, app_id = _seed(app)
        seed_snapshot(app, host_id, nodes=[{"node": "pve1", "status": "online"}])
        r = c.get(f"/api/v1/apps/{app_id}/web-url")
        assert r.status_code == 200
        assert r.json()["url"] == "https://10.9.9.9:5006/"
        assert r.json()["protocol_decided_by"] == "asked the app"


def test_a_plain_app_still_opens_at_http(tmp_path, monkeypatch, bootstrap_admin):
    monkeypatch.setattr(webui, "probe_scheme", lambda addr, port, **k: "http")
    app = make_app(tmp_path, fake=_fake())
    with TestClient(app) as c:
        bootstrap_admin(c)
        host_id, app_id = _seed(app, port=8384)
        seed_snapshot(app, host_id, nodes=[{"node": "pve1", "status": "online"}])
        assert c.get(f"/api/v1/apps/{app_id}/web-url").json()["url"] \
            == "http://10.9.9.9:8384/"


def test_an_app_that_does_not_answer_is_refused_not_defaulted_to_http(
        tmp_path, monkeypatch, bootstrap_admin):
    monkeypatch.setattr(webui, "probe_scheme", lambda addr, port, **k: None)
    app = make_app(tmp_path, fake=_fake())
    with TestClient(app) as c:
        bootstrap_admin(c)
        host_id, app_id = _seed(app)
        seed_snapshot(app, host_id, nodes=[{"node": "pve1", "status": "online"}])
        r = c.get(f"/api/v1/apps/{app_id}/web-url")
        assert r.status_code == 409
        detail = r.json()["detail"]
        assert "http" in detail and "https" in detail
        assert "10.9.9.9:5006" in detail


def test_the_port_the_operator_set_beats_the_catalog_s(tmp_path, monkeypatch,
                                                       bootstrap_admin):
    """web_port is editable in Reconfigure and the browser used to ignore it,
    reading only the catalog's port, so an app moved to another port opened at
    the old one."""
    monkeypatch.setattr(webui, "probe_scheme", lambda addr, port, **k: "http")
    app = make_app(tmp_path, fake=_fake())
    with TestClient(app) as c:
        bootstrap_admin(c)
        host_id, app_id = _seed(app, port=5006, web_port=8080)
        seed_snapshot(app, host_id, nodes=[{"node": "pve1", "status": "online"}])
        assert c.get(f"/api/v1/apps/{app_id}/web-url").json()["url"] \
            == "http://10.9.9.9:8080/"


def test_install_and_adopt_leave_the_protocol_unset(tmp_path, csrf_header,
                                                    bootstrap_admin):
    """Adopt used to write the literal "http", which is why every app looked
    like a deliberate choice. NULL is what makes the app get asked."""
    app = make_app(tmp_path, fake=_fake())
    with TestClient(app) as c:
        bootstrap_admin(c)
        host_id, _ = _seed(app)
        r = c.post("/api/v1/apps/adopt", headers=csrf_header(c), json={
            "items": [{"host_id": host_id, "ctid": 222, "name": "Wastebin",
                       "catalog_slug": "actualbudget"}]})
        assert r.status_code == 200
        with app.state.sessionmaker() as db:
            adopted = db.get(App, r.json()["adopted"][0])
            assert adopted.web_protocol is None


def test_reconfigure_refuses_a_protocol_no_browser_can_open(tmp_path, csrf_header,
                                                            bootstrap_admin):
    app = make_app(tmp_path, fake=_fake())
    with TestClient(app) as c:
        bootstrap_admin(c)
        _, app_id = _seed(app)
        r = c.patch(f"/api/v1/apps/{app_id}", headers=csrf_header(c),
                    json={"web_protocol": "ftp"})
        assert r.status_code == 422
        r = c.patch(f"/api/v1/apps/{app_id}", headers=csrf_header(c),
                    json={"web_protocol": "HTTPS"})
        assert r.status_code == 200
        with app.state.sessionmaker() as db:
            assert db.get(App, app_id).web_protocol == "https"
        # And blank puts it back to being asked rather than told.
        r = c.patch(f"/api/v1/apps/{app_id}", headers=csrf_header(c),
                    json={"web_protocol": ""})
        assert r.status_code == 200
        with app.state.sessionmaker() as db:
            assert db.get(App, app_id).web_protocol is None


# --- what the install script printed about itself --------------------------
#
# Copied byte for byte out of job_events for job 231 in the dev database, the
# real Actual Budget install: ANSI escapes, emoji, leading spaces and all. A
# tidied-up version of these lines would test a parser against input it will
# never see.

REAL_TAIL = [
    '\r\x1b[K  ✔️  \x1b[1;92mCompleted successfully!',
    '\x1b[m',
    '  \U0001f680  \x1b[m\x1b[1;92mActual Budget setup has been successfully initialized!\x1b[m',
    '  \U0001f4a1  \x1b[m\x1b[33mAccess it using the following URL:\x1b[m',
    '  \U0001f310  \x1b[m\x1b[4;92mhttps://192.168.50.194:5006\x1b[m',
    '',
    '',
]


def test_the_real_ansi_and_emoji_line_yields_the_url():
    assert webui.url_from_install_log(REAL_TAIL, expected_port=5006) \
        == "https://192.168.50.194:5006"


def test_the_url_carries_the_port_and_path_not_just_the_scheme():
    # actual-budget and anytype-server both have web_port NULL, and this line
    # is the only place their port was ever stated to Proxploy.
    assert webui.installed_parts("https://192.168.50.194:5006") \
        == ("https", 5006, "/")
    assert webui.installed_parts("http://10.0.0.5:8080/admin") \
        == ("http", 8080, "/admin")
    assert webui.installed_parts(None) == (None, None, None)


def test_a_documentation_link_near_the_end_loses_to_the_real_url():
    tail = REAL_TAIL + [
        '  \U0001f4d6  \x1b[m\x1b[33mDocs: https://github.com/actualbudget/actual\x1b[m']
    assert webui.url_from_install_log(tail, expected_port=5006) \
        == "https://192.168.50.194:5006"


def test_a_documentation_link_alone_is_not_an_app_url():
    # Not a candidate at all: its host is a name, and community-scripts always
    # prints the container's own address. Without this rule a script that
    # printed only a project link would have that recorded as its web
    # interface.
    tail = ['  \U0001f4d6  \x1b[m\x1b[33mSee https://actualbudget.org/ for docs\x1b[m']
    assert webui.url_from_install_log(tail, expected_port=5006) is None


def test_two_conflicting_urls_record_nothing():
    # Both are IP literals and neither is corroborated, so there is no honest
    # way to pick. Recording nothing costs one probe on the next click;
    # recording the wrong one is a stored wrong answer.
    tail = ['  \x1b[4;92mhttp://192.168.1.10:9000\x1b[m',
            '  \x1b[4;92mhttp://192.168.1.11:9100\x1b[m']
    assert webui.url_from_install_log(tail, expected_port=5006) is None
    # And still nothing when BOTH match the thing that was supposed to break
    # the tie: two corroborated candidates are not a tie, they are a log this
    # parser does not understand.
    same = ['  http://192.168.1.10:5006', '  http://192.168.1.11:5006']
    assert webui.url_from_install_log(same, expected_port=5006) is None


def test_a_stale_address_still_parses_because_the_port_corroborates():
    # Dashy's install printed 192.168.50.188 for a container that now holds
    # 192.168.50.191, its DHCP lease having moved since. The address cannot
    # be required.
    tail = ['  \x1b[4;92mhttp://192.168.50.188:4000\x1b[m',
            '  \x1b[33mhttps://dashy.to\x1b[m']
    assert webui.url_from_install_log(tail, expected_port=4000,
                                      guest_address="192.168.50.191") \
        == "http://192.168.50.188:4000"


def test_the_banner_is_ignored_when_it_is_too_far_back():
    # Only the tail is read, so a URL buried in the middle of a long build log
    # is not mistaken for the closing banner.
    tail = REAL_TAIL + ["filler"] * webui.TAIL_LINES
    assert webui.url_from_install_log(tail, expected_port=5006) is None


# --- precedence: operator, then the installer, then the probe --------------

def test_what_the_installer_said_beats_the_probe(monkeypatch):
    monkeypatch.setattr(webui, "probe_scheme",
                        lambda *a, **k: pytest.fail("probed an app the log answered"))
    row = App(host_id=1, ctid=1, name="x", slug="x", web_protocol=None,
              installed_url="https://192.168.50.194:5006")
    assert webui.scheme_for(row, "192.168.50.194", 5006) \
        == ("https", "printed by the install script")


def test_the_operator_beats_what_the_installer_said(monkeypatch):
    monkeypatch.setattr(webui, "probe_scheme",
                        lambda *a, **k: pytest.fail("probed an app already set"))
    row = App(host_id=1, ctid=1, name="x", slug="x", web_protocol="http",
              installed_url="https://192.168.50.194:5006")
    assert webui.scheme_for(row, "192.168.50.194", 5006) == ("http", "set on the app")


def test_the_probe_still_answers_when_there_is_no_log(monkeypatch):
    # The five apps in the dev database with no succeeded install job are
    # exactly this case, which is why the probe stays.
    monkeypatch.setattr(webui, "probe_scheme", lambda *a, **k: "https")
    row = App(host_id=1, ctid=1, name="x", slug="x", web_protocol=None,
              installed_url=None)
    assert webui.scheme_for(row, "192.168.50.194", 5006) == ("https", "asked the app")


def test_the_installers_port_fills_in_where_the_catalog_named_none(
        tmp_path, monkeypatch, bootstrap_admin):
    """actual-budget's row has web_port NULL. The printed URL is the only
    place its port and scheme were ever stated."""
    monkeypatch.setattr(webui, "probe_scheme",
                        lambda *a, **k: pytest.fail("probed an app the log answered"))
    app = make_app(tmp_path, fake=_fake())
    with TestClient(app) as c:
        bootstrap_admin(c)
        host_id, app_id = _seed(app, port=None)
        with app.state.sessionmaker() as db:
            db.get(App, app_id).installed_url = "https://192.168.50.194:5006"
            db.commit()
        seed_snapshot(app, host_id, nodes=[{"node": "pve1", "status": "online"}])
        body = c.get(f"/api/v1/apps/{app_id}/web-url").json()
        assert body["url"] == "https://10.9.9.9:5006/"
        assert body["protocol_decided_by"] == "printed by the install script"


# --- the one-time recovery pass for installs that already ran --------------

def _row(conn, table, **cols):
    from sqlalchemy import text

    stamps = {"created_at": "2026-01-01 00:00:00", "updated_at": "2026-01-01 00:00:00"}
    cols = {**stamps, **cols} if table != "job_events" else cols
    keys = ", ".join(cols)
    binds = ", ".join(f":{k}" for k in cols)
    conn.execute(text(f"INSERT INTO {table} ({keys}) VALUES ({binds})"), cols)


def test_the_backfill_recovers_the_url_from_logs_already_on_disk(tmp_path):
    """Five of the ten apps in the dev database have a succeeded install job
    whose log is still in job_events. Re-installing an app to recover a line
    Proxploy already captured would be absurd, so the migration reads them."""
    import json as _json

    from alembic import command
    from sqlalchemy import create_engine, text

    from tests.test_migrations import _alembic_cfg

    db_url = f"sqlite:///{tmp_path}/existing.db"
    cfg = _alembic_cfg(db_url)
    command.upgrade(cfg, "a2d6f14b8e37")  # everything up to just before this one

    eng = create_engine(db_url)
    with eng.begin() as c:
        _row(c, "hosts", name="h", address="https://x:8006", verify_tls=1,
             status="connected")
        host_id = c.execute(text("SELECT id FROM hosts")).scalar_one()
        _row(c, "catalog_entries", slug="actualbudget", name="Actual Budget",
             entry_type="ct", script_path="ct/actualbudget.sh", port=5006)
        _row(c, "catalog_entries", slug="gotify", name="Gotify",
             entry_type="ct", script_path="ct/gotify.sh", port=80)
        for name, slug, cslug, ctid in (("actual-budget", "ab-1", "actualbudget", 109),
                                        ("gotify", "go-1", "gotify", 103)):
            _row(c, "apps", host_id=host_id, ct_id=ctid, name=name, slug=slug,
                 catalog_slug=cslug, web_path="/", adopted=1)
        # One succeeded install, and one FAILED install for the other app. A
        # failed run can still have printed a URL, for a container that was
        # then rolled back, so its log is never read.
        for job_id, status, name in ((231, "succeeded", "actual-budget"),
                                     (190, "failed", "gotify")):
            _row(c, "jobs", id=job_id, kind="app.install", status=status,
                 params=_json.dumps({"host_id": host_id, "name": name}))
            for seq, line in enumerate(REAL_TAIL):
                _row(c, "job_events", job_id=job_id, seq=seq,
                     ts="2026-01-01 00:00:00", stream="stdout",
                     message=line.replace("192.168.50.194:5006",
                                          "192.168.50.185:80" if status == "failed"
                                          else "192.168.50.194:5006"))
    eng.dispose()

    command.upgrade(cfg, "head")

    eng = create_engine(db_url)
    try:
        got = dict(eng.connect().execute(
            text("SELECT name, installed_url FROM apps")).all())
    finally:
        eng.dispose()
    assert got["actual-budget"] == "https://192.168.50.194:5006"
    # The failed job's log was ignored, so this app keeps falling through to
    # the probe, which is exactly why the probe stays.
    assert got["gotify"] is None
