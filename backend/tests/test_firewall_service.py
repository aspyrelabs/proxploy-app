"""Scope resolution and the read/write client split (spec: 2026-08-21)."""
import json

import pytest

from proxploy.models import App, Host, HostCredential
from proxploy.services import firewall as fw


def _seed(app):
    with app.state.sessionmaker() as db:
        host = Host(name="host-01", address="https://10.0.0.9:8006",
                    node_name="pve1", status="connected")
        db.add(host)
        db.commit()
        for cap in ("monitoring", "lifecycle"):
            blob, ver = app.state.secretstore.encrypt(json.dumps(
                {"token_id": f"proxploy@pve!fw-{cap}",
                 "token_secret": "s3cret"}).encode())
            db.add(HostCredential(host_id=host.id, kind=f"api_token:{cap}",
                                  encrypted_blob=blob, key_version=ver))
        a = App(host_id=host.id, ctid=150, name="Immich", slug="immich",
                node_name="pve2")
        db.add(a)
        db.commit()
        return host.id, a.id


def test_cluster_and_node_locations():
    assert fw.cluster_loc() == {"kind": "cluster"}
    assert fw.node_loc("pve1") == {"kind": "node", "node": "pve1"}
    assert fw.group_loc("web") == {"kind": "group", "group": "web"}


def test_guest_location_uses_the_node_the_guest_actually_runs_on(client):
    """Not the host's entry node. On a cluster every polled host mirrors every
    guest, so the host's own node reaches the wrong machine for all but one."""
    app = client.app
    host_id, app_id = _seed(app)
    with app.state.sessionmaker() as db:
        host = db.get(Host, host_id)
        row = db.get(App, app_id)
        loc = fw.guest_loc(host, "lxc", row.ctid, row)
    assert loc == {"kind": "guest", "node": "pve2",
                   "guest_kind": "lxc", "vmid": 150}


def test_reads_use_monitoring_and_writes_use_lifecycle(client):
    """Verified against real tokens on 2026-08-21: the lifecycle token writes
    every firewall scope and returns 403 on every read (VM.Audit, Sys.Audit).
    Reading through the write client fails before anything is attempted."""
    app = client.app
    host_id, _ = _seed(app)
    with app.state.sessionmaker() as db:
        host = db.get(Host, host_id)
        assert fw.readers(app, db, host).token_id.endswith("fw-monitoring")
        assert fw.writers(app, db, host).token_id.endswith("fw-lifecycle")


def test_scope_objects_records_what_each_scope_actually_has():
    """Measured on pve-manager 9.2.11. A node has no aliases or IP sets, and
    only the cluster has security groups and macros."""
    assert "aliases" in fw.SCOPE_OBJECTS["cluster"]
    assert "aliases" in fw.SCOPE_OBJECTS["guest"]
    assert "aliases" not in fw.SCOPE_OBJECTS["node"]
    assert "groups" in fw.SCOPE_OBJECTS["cluster"]
    assert "groups" not in fw.SCOPE_OBJECTS["guest"]
    assert "log" in fw.SCOPE_OBJECTS["node"]
    assert "log" in fw.SCOPE_OBJECTS["guest"]
    assert "log" not in fw.SCOPE_OBJECTS["cluster"]
