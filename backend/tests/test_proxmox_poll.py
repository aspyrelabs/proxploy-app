"""ProxmoxClient bulk-poll reads (doc 02 §3: cluster/resources + per-node rrddata)."""
import json
from pathlib import Path

import pytest

FIX = Path(__file__).parent / "fixtures" / "pve"


def _client(fake):
    from proxploy.services.proxmox import ProxmoxClient
    from tests.fakes.pve import make_fake_factory

    return ProxmoxClient("https://pve1:8006", "proxploy@pve!mon", "s3cret",
                         factory=make_fake_factory(fake))


def test_cluster_resources_returns_rows():
    from tests.fakes.pve import FakePVE

    rows = json.loads((FIX / "cluster_resources_basic.json").read_text())
    fake = FakePVE(resources=rows)
    got = _client(fake).cluster_resources()
    assert got == rows
    assert {r["type"] for r in got} == {"node", "lxc", "qemu", "storage"}


def test_node_rrddata_passes_timeframe():
    from tests.fakes.pve import FakePVE

    rrd = json.loads((FIX / "rrddata_hour.json").read_text())
    fake = FakePVE(rrddata={"pve1": rrd})
    got = _client(fake).node_rrddata("pve1")
    assert got == rrd
    assert _client(fake).node_rrddata("missing-node") == []


def test_poll_reads_wrap_errors_as_proxmox_error():
    from proxploy.services.proxmox import ProxmoxError
    from tests.fakes.pve import FakePVE

    fake = FakePVE()
    fake.cluster.resources._fail = True
    fake.fail = True
    with pytest.raises(ProxmoxError):
        _client(fake).cluster_resources()
    with pytest.raises(ProxmoxError):
        _client(fake).node_rrddata("pve1")
