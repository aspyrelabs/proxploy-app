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
    c = ProxmoxClient("https://pve.local:8006", "proxploy@pve!mon", "s3cret",
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

    c = ProxmoxClient("https://pve.local:8006", "a@pve!b", "x",
                      factory=make_fake_factory(FakePVE(fail=True)))
    with pytest.raises(ProxmoxError):
        c.version()
