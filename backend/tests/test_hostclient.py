# backend/tests/test_hostclient.py
"""services/hostclient.py::client_for_host, extended with a `capability`
argument (step one of the per-capability host token work,
host-token-privileges-step-one-report.md).

Storage is `host_credentials.kind = "api_token:<capability>"`; a missing row
for the capability a caller asked for is a configuration gap Proxploy can
see BEFORE ever touching the network, so it is reported as a typed, named
error rather than left to surface as a raw 403 partway through a job.
"""
import json

import pytest

from proxploy.models import Host, HostCredential
from proxploy.services.hostclient import CapabilityNotConfigured, client_for_host
from proxploy.services.proxmox import ProxmoxError
from tests.support import make_db


def _host(db, name="h1"):
    h = Host(name=name, address="https://10.0.0.9:8006", status="connected")
    db.add(h)
    db.commit()
    return h


class _FakeApp:
    def __init__(self, secretstore):
        from types import SimpleNamespace
        self.state = SimpleNamespace(secretstore=secretstore, proxmox_factory=None)


def _secretstore(tmp_path):
    from proxploy.secretstore import SecretStore

    key_file = tmp_path / "master.key"
    SecretStore.ensure_key_file(key_file, db_file_exists=False)
    return SecretStore(key_file)


def _add_cred(db, ss, host, capability, token_id):
    blob, ver = ss.encrypt(json.dumps(
        {"token_id": token_id, "token_secret": "s3cret"}).encode())
    db.add(HostCredential(host_id=host.id, kind=f"api_token:{capability}",
                          encrypted_blob=blob, key_version=ver,
                          public_meta=token_id))
    db.commit()


def test_default_capability_is_monitoring(tmp_path):
    db = make_db(tmp_path)
    ss = _secretstore(tmp_path)
    app = _FakeApp(ss)
    host = _host(db)
    _add_cred(db, ss, host, "monitoring", "proxploy@pve!monitoring")
    client = client_for_host(app, db, host)
    assert client.token_id == "proxploy@pve!monitoring"


def test_a_capability_specific_token_is_resolved(tmp_path):
    db = make_db(tmp_path)
    ss = _secretstore(tmp_path)
    app = _FakeApp(ss)
    host = _host(db)
    _add_cred(db, ss, host, "monitoring", "proxploy@pve!monitoring")
    _add_cred(db, ss, host, "lifecycle", "proxploy@pve!lifecycle")
    client = client_for_host(app, db, host, capability="lifecycle")
    assert client.token_id == "proxploy@pve!lifecycle"


def test_a_missing_capability_raises_a_typed_named_error_not_a_bare_lookup_failure(tmp_path):
    """The whole point: a capability nobody configured must be caught here,
    before any network call, with a message naming the host and the missing
    capability -- not a `.one()` crash and not a 403 relayed from PVE."""
    db = make_db(tmp_path)
    ss = _secretstore(tmp_path)
    app = _FakeApp(ss)
    host = _host(db, name="prod-node")
    _add_cred(db, ss, host, "monitoring", "proxploy@pve!monitoring")
    with pytest.raises(CapabilityNotConfigured) as ei:
        client_for_host(app, db, host, capability="lifecycle")
    # It is a ProxmoxError (existing except-blocks across the codebase catch
    # this without any changes), but distinguishably typed and kinded.
    assert isinstance(ei.value, ProxmoxError)
    assert ei.value.kind == "capability_missing"
    assert ei.value.capability == "lifecycle"
    msg = str(ei.value)
    assert "prod-node" in msg
    assert "lifecycle" in msg


def test_a_host_with_no_tokens_at_all_still_names_the_capability(tmp_path):
    db = make_db(tmp_path)
    ss = _secretstore(tmp_path)
    app = _FakeApp(ss)
    host = _host(db)
    with pytest.raises(CapabilityNotConfigured) as ei:
        client_for_host(app, db, host, capability="backup")
    assert ei.value.capability == "backup"
