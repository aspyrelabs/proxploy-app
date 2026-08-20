import pytest

from proxploy.services.proxmox import ProxmoxClient, ProxmoxError
from tests.fakes.pve import FakePVE, make_fake_factory


def _client(fake):
    return ProxmoxClient("https://10.0.0.9:8006", "proxploy@pve!console",
                          "sekret", verify_tls=False,
                          factory=make_fake_factory(fake))


def test_termproxy_returns_ticket_port_user():
    fake = FakePVE()
    fake.termproxy_response = {"user": "proxploy@pve!console", "ticket": "PVEVNC:abc123",
                                "port": "5900", "upid": "UPID:pve1:...:termproxy::proxploy@pve:"}
    result = _client(fake).termproxy("lxc", "pve1", 150)
    assert result == fake.termproxy_response
    assert fake.last_termproxy_call == ("lxc", "pve1", 150)


def test_node_termproxy_has_no_guest_segment():
    fake = FakePVE()
    fake.termproxy_response = {"user": "proxploy@pve!console", "ticket": "PVEVNC:xyz",
                                "port": "5901", "upid": "UPID:pve1:...:termproxy::proxploy@pve:"}
    result = _client(fake).node_termproxy("pve1")
    assert result == fake.termproxy_response
    assert fake.last_node_termproxy_call == "pve1"


def test_vncproxy_returns_ticket_port_cert():
    fake = FakePVE()
    fake.vncproxy_response = {"user": "proxploy@pve!console", "ticket": "PVEVNC:def456",
                              "port": "5902", "cert": "-----BEGIN CERTIFICATE-----...",
                              "upid": "UPID:pve1:...:vncproxy::proxploy@pve:"}
    result = _client(fake).vncproxy("pve1", 200)
    assert result == fake.vncproxy_response
    assert fake.last_vncproxy_call == ("pve1", 200)


def test_vncproxy_asks_pve_to_generate_a_console_password():
    """QEMU offers RFB security type 2 (VNC Authentication) and nothing else,
    verified against a live PVE 9.2.10 node: the security-types frame is
    b"\\x01\\x02". A client with no password cannot finish that handshake, and
    the bridge cannot answer it on the client's behalf. `generate-password=1`
    is what makes PVE hand back a password that is separate from the
    vncticket, so the browser can answer the challenge without also being
    handed the credential that authenticates the PVE websocket upgrade."""
    fake = FakePVE()
    fake.vncproxy_response = {"user": "proxploy@pve!console", "ticket": "PVEVNC:def456",
                              "port": "5902", "password": "s3cr3t8x",
                              "cert": "-----BEGIN CERTIFICATE-----...",
                              "upid": "UPID:pve1:...:vncproxy::proxploy@pve:"}
    _client(fake).vncproxy("pve1", 200)
    assert fake.last_vncproxy_kwargs.get("generate-password") == 1
    assert fake.last_vncproxy_kwargs.get("websocket") == 1


def test_termproxy_wraps_and_redacts_secret_on_failure():
    fake = FakePVE(fail=True)
    with pytest.raises(ProxmoxError) as exc:
        _client(fake).termproxy("lxc", "pve1", 150)
    assert "sekret" not in str(exc.value)


def test_open_validated_tcp_socket_refuses_link_local():
    from proxploy.services.proxmox import open_validated_tcp_socket, ProxmoxError
    with pytest.raises(ProxmoxError, match="link-local"):
        open_validated_tcp_socket("169.254.169.254", 8006, timeout=1)
