import json
from pathlib import Path

import pytest

FIX = Path(__file__).parent / "fixtures" / "pve"


def test_parse_token_id():
    from proxploy.services.proxmox import ProxmoxError, parse_token_id

    assert parse_token_id("proxploy@pve!monitoring") == ("proxploy@pve", "monitoring")
    with pytest.raises(ProxmoxError):
        parse_token_id("no-bang-here")


@pytest.mark.parametrize("fixture", ["version_pve8.json", "version_pve9.json"])
def test_version_via_fake(fixture):
    from proxploy.services.proxmox import ProxmoxClient
    from tests.fakes.pve import FakePVE, make_fake_factory

    fake = FakePVE(version=json.loads((FIX / fixture).read_text()),
                   permissions=json.loads((FIX / "permissions_full.json").read_text()))
    c = ProxmoxClient("https://10.0.0.5:8006", "proxploy@pve!mon", "s3cret",
                      factory=make_fake_factory(fake))
    v = c.version()
    assert v["release"] in ("8.4", "9.0")
    assert c.permissions()["/"]["Sys.Audit"] == 1
    assert fake.kwargs["user"] == "proxploy@pve"
    assert fake.kwargs["token_name"] == "mon"
    assert fake.kwargs["token_value"] == "s3cret"


def test_unreachable_raises_proxmox_error():
    from proxploy.services.proxmox import ProxmoxClient, ProxmoxError
    from tests.fakes.pve import FakePVE, make_fake_factory

    c = ProxmoxClient("https://10.0.0.5:8006", "a@pve!b", "x",
                      factory=make_fake_factory(FakePVE(fail=True)))
    with pytest.raises(ProxmoxError):
        c.version()


# --- SSRF: the probe target is operator-supplied (Phase 3 review, finding 1) ---

DENIED = [
    "169.254.169.254",       # the whole reason this guard exists: cloud metadata
    "169.254.1.1",           # rest of the link-local /16
    "fe80::1",               # IPv6 link-local
    "::ffff:169.254.169.254",  # IPv4-mapped form of the metadata address
    "127.0.0.1", "127.9.9.9", "::1",
    "0.0.0.0", "::",
    "224.0.0.1", "ff02::1",  # multicast
    "240.0.0.1",             # reserved
]
ALLOWED = [
    "10.0.0.5", "192.168.1.10", "172.16.5.4",  # RFC1918; the NORMAL case here
    "fd00::1",                                 # IPv6 unique-local
    "203.0.113.7",                             # a routable node over a VPN/WAN
]


@pytest.mark.parametrize("host", DENIED)
def test_probe_target_refuses_the_dangerous_address_classes(host):
    from proxploy.services.proxmox import ProxmoxError, resolve_target

    with pytest.raises(ProxmoxError) as e:
        resolve_target(host, 8006)
    assert "refusing to connect" in str(e.value)


@pytest.mark.parametrize("host", ALLOWED)
def test_probe_target_allows_rfc1918_and_routable_nodes(host):
    """A self-hosted product whose nodes live on 192.168.x.x must not have its
    normal case gated behind a setting. Pinned so nobody "hardens" it away."""
    from proxploy.services.proxmox import resolve_target

    assert resolve_target(host, 8006) == host


def test_a_name_is_judged_by_what_it_resolves_to_not_by_its_spelling(monkeypatch):
    """Validating the string would be theatre: `metadata.example.com` looks
    like an ordinary hostname and resolves to the metadata address. Every
    resolved address must pass, not merely the first; the mixed case below is
    a real DNS answer an attacker controls."""
    import socket

    from proxploy.services.proxmox import ProxmoxError, resolve_target

    def fake_getaddrinfo(host, port, *a, **kw):
        answers = {"metadata.example.com": ["169.254.169.254"],
                   "mixed.example.com": ["10.0.0.5", "169.254.169.254"],
                   "good.example.com": ["10.0.0.5", "10.0.0.6"]}
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))
                for ip in answers[host]]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    for bad in ("metadata.example.com", "mixed.example.com"):
        with pytest.raises(ProxmoxError, match="169.254.169.254"):
            resolve_target(bad, 8006)
    assert resolve_target("good.example.com", 8006) == "10.0.0.5"


def test_the_guard_covers_the_proxmoxer_path_too_not_just_the_fingerprint_fetch():
    """`_connect()` reaches the network twice, the CERT_NONE fingerprint socket
    and proxmoxer's own session. Gating only the first would leave the second a
    working SSRF, so the factory must never even be called."""
    from proxploy.services.proxmox import ProxmoxClient, ProxmoxError

    called = []
    c = ProxmoxClient("https://169.254.169.254:8006", "root@pam!t", "s",
                      verify_tls=True, factory=lambda **kw: called.append(kw))
    with pytest.raises(ProxmoxError, match="refusing to connect"):
        c.version()
    assert not called


# --- the CERT_NONE exception is onboarding-only: everything after pins ---

def _self_signed(tmp_path, cn, serial):
    """Two certs that differ only in serial/key, so the test cannot pass by
    accident of a differing subject."""
    import datetime

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder()
            .subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(serial)
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=1))
            .sign(key, hashes.SHA256()))
    path = tmp_path / f"{serial}.pem"
    path.write_bytes(cert.public_bytes(serialization.Encoding.PEM)
                     + key.private_bytes(serialization.Encoding.PEM,
                                         serialization.PrivateFormat.PKCS8,
                                         serialization.NoEncryption()))
    import ssl
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(path)
    return ctx


def test_a_rotated_certificate_is_refused_by_the_pin(tmp_path, monkeypatch):
    """CERT_NONE is legitimate for exactly one moment, capturing the
    fingerprint at onboarding. Every connection after that must verify against
    the pin. Proven end to end against a real TLS listener whose certificate is
    swapped underneath a live pin, not by stubbing the comparison.

    Tension with the SSRF guard: the only address a test can serve TLS on is
    127.0.0.1, which that guard denies. Resolved by the same opt-in an operator
    running Proxploy ON the PVE node uses (PROXPLOY_ALLOW_LOOPBACK_TARGET=1),
    flipped here as the module attribute, so the test exercises the real
    guard rather than bypassing it.
    """
    import socket
    import threading

    from proxploy.services import proxmox as pmod
    from proxploy.services.proxmox import (ProxmoxClient, ProxmoxError,
                                           tls_fingerprint_sha256)
    from tests.fakes.pve import FakePVE, make_fake_factory

    monkeypatch.setattr(pmod, "ALLOW_LOOPBACK_TARGET", True)
    serving = [_self_signed(tmp_path, "pve.local", 1)]
    lsock = socket.create_server(("127.0.0.1", 0))
    port = lsock.getsockname()[1]
    stop = threading.Event()

    def serve():
        while not stop.is_set():
            try:
                conn, _ = lsock.accept()
            except OSError:
                return
            try:
                serving[0].wrap_socket(conn, server_side=True).close()
            except OSError:
                conn.close()

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    try:
        pinned = tls_fingerprint_sha256("127.0.0.1", port)
        assert len(pinned.split(":")) == 32

        def client():
            return ProxmoxClient(f"https://127.0.0.1:{port}", "root@pam!t", "s",
                                 verify_tls=False, tls_fingerprint=pinned,
                                 factory=make_fake_factory(FakePVE()))

        # unchanged cert: the pinned path is live, not merely failing shut
        assert client().version()["release"] == "8.4"

        serving[0] = _self_signed(tmp_path, "pve.local", 2)  # cert rotated / MITM
        rotated = tls_fingerprint_sha256("127.0.0.1", port)
        assert rotated != pinned
        # a fresh client per request is how the API uses this: the pin is
        # re-checked on every _connect(), only cached within one instance.
        with pytest.raises(ProxmoxError, match="TLS fingerprint mismatch"):
            client().version()
    finally:
        stop.set()
        lsock.close()
        t.join(timeout=5)


def _fake_client(fake):
    from proxploy.services.proxmox import ProxmoxClient
    from tests.fakes.pve import make_fake_factory

    return ProxmoxClient("https://10.0.0.5:8006", "proxploy@pve!mon", "s3cret",
                         factory=make_fake_factory(fake))


def test_node_status_returns_the_node_payload():
    from tests.fakes.pve import FakePVE

    fake = FakePVE()
    fake.node_status_by_node = {"pve1": {"uptime": 25029, "cpuinfo": {"cores": 14}}}
    assert _fake_client(fake).node_status("pve1")["uptime"] == 25029


def test_node_disks_returns_the_inventory():
    from tests.fakes.pve import FakePVE

    fake = FakePVE()
    fake.disks_by_node = {"pve1": [{"devpath": "/dev/nvme0n1", "wearout": 99}]}
    assert _fake_client(fake).node_disks("pve1")[0]["wearout"] == 99


def test_node_status_wraps_errors_as_proxmox_error():
    from proxploy.services.proxmox import ProxmoxError
    from tests.fakes.pve import FakePVE

    with pytest.raises(ProxmoxError):
        _fake_client(FakePVE(fail=True)).node_status("pve1")


# --- node_power: reboot/shutdown the NODE itself, not a guest --------------

def test_node_power_reboot_posts_the_reboot_command():
    from tests.fakes.pve import FakePVE

    fake = FakePVE()
    upid = _fake_client(fake).node_power("pve1", "reboot")
    assert fake.node_power_calls == [("pve1", "reboot")]
    # Not a UPID: PVE::API2::Nodes runs the reboot in the request handler and
    # its schema returns null, so there is no task to hand back. This asserted
    # a UPID because the fake used to mint one, which is how the null went
    # unnoticed until a real power off failed on it.
    assert upid is None


def test_node_power_shutdown_posts_the_shutdown_command():
    from tests.fakes.pve import FakePVE

    fake = FakePVE()
    _fake_client(fake).node_power("pve1", "shutdown")
    assert fake.node_power_calls == [("pve1", "shutdown")]


def test_node_power_rejects_an_unknown_command_without_calling_proxmox():
    from proxploy.services.proxmox import ProxmoxError
    from tests.fakes.pve import FakePVE

    fake = FakePVE()
    with pytest.raises(ProxmoxError):
        _fake_client(fake).node_power("pve1", "stop")
    assert fake.node_power_calls == []


def test_node_power_wraps_connection_failure_as_proxmox_error():
    from proxploy.services.proxmox import ProxmoxError
    from tests.fakes.pve import FakePVE

    with pytest.raises(ProxmoxError):
        _fake_client(FakePVE(fail=True)).node_power("pve1", "reboot")


def test_node_power_names_the_missing_privilege_on_a_403():
    """A bare relay of Proxmox's 403 leaves the operator to work out on their
    own that Sys.PowerMgmt is what is missing, and that our own generated
    script never granted it. Name it, and say how to fix it."""
    from proxploy.services.proxmox import ProxmoxError
    from tests.fakes.pve import FakePVE

    fake = FakePVE()
    fake.power_forbidden_nodes = {"pve1"}
    with pytest.raises(ProxmoxError) as ei:
        _fake_client(fake).node_power("pve1", "shutdown")
    msg = str(ei.value)
    assert "Sys.PowerMgmt" in msg
    assert "docs.proxploy.com" in msg
    assert ei.value.kind == "permission"
    # The original Proxmox text stays in the message too: evidence, not
    # replaced by our own guess.
    assert "403" in msg


def test_node_power_leaves_an_unrelated_failure_generically_classified():
    """Only a 403 gets the Sys.PowerMgmt-specific treatment; an unreachable
    node must not be mis-diagnosed as a permission problem."""
    from proxploy.services.proxmox import ProxmoxError
    from tests.fakes.pve import FakePVE

    fake = FakePVE()
    fake.power_fail_nodes = {"pve1"}
    with pytest.raises(ProxmoxError) as ei:
        _fake_client(fake).node_power("pve1", "shutdown")
    assert "Sys.PowerMgmt" not in str(ei.value)
    assert ei.value.kind != "permission"
