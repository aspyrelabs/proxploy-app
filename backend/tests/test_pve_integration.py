import os

import pytest

pytestmark = pytest.mark.pve_integration

REQUIRED = ("PROXPLOY_TEST_PVE_URL", "PROXPLOY_TEST_PVE_TOKEN_ID",
            "PROXPLOY_TEST_PVE_TOKEN_SECRET")


@pytest.mark.skipif(not all(os.environ.get(k) for k in REQUIRED),
                    reason="disposable PVE env not configured")
def test_live_version_and_permissions():
    from proxploy.services.proxmox import ProxmoxClient

    c = ProxmoxClient(os.environ["PROXPLOY_TEST_PVE_URL"],
                      os.environ["PROXPLOY_TEST_PVE_TOKEN_ID"],
                      os.environ["PROXPLOY_TEST_PVE_TOKEN_SECRET"],
                      verify_tls=os.environ.get("PROXPLOY_TEST_PVE_VERIFY", "0") == "1")
    v = c.version()
    assert v["release"].split(".")[0] in ("8", "9")  # supported window (doc 11 §7)
    assert isinstance(c.permissions(), dict)
