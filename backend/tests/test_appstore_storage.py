"""Task 1: _storage_pools resolves the enabled and active pools on a host's
node that carry a given content type, the API-side equivalent of build.func's
`pvesm status -content "$content"` picker that Tasks 3/4 will use to avoid
that picker going interactive on a host with more than one candidate pool."""
import asyncio

import pytest

from proxploy.jobs import JobFailed
from proxploy.services.appstore import _storage_pools
from tests.fakes.pve import FakePVE
from tests.support import make_db, make_job_app, seed_host_row


def _seed_host_with_token(app, db, **host_kwargs):
    """Host + the api_token:monitoring credential client_for_host needs,
    same shape as test_appstore_install.py's _seed_api_token."""
    from proxploy.models import HostCredential

    host = seed_host_row(db, **host_kwargs)
    blob, ver = app.state.secretstore.encrypt(
        b'{"token_id": "root@pam!t", "token_secret": "s"}')
    db.add(HostCredential(host_id=host.id, kind="api_token:monitoring",
                          encrypted_blob=blob, key_version=ver))
    db.commit()
    return host.id


def test_storage_pools_filters_by_content_type(tmp_path):
    """rootdir and vztmpl are different questions. A pool that can hold a
    template cannot necessarily hold a rootfs, and offering one for the other
    fails at pct create with a raw Proxmox error."""
    async def scenario():
        pve = FakePVE()
        app = make_job_app(tmp_path, fake=pve)
        with app.state.sessionmaker() as db:
            host_id = _seed_host_with_token(app, db)

        pve.storages_by_node["pve1"] = [
            {"storage": "local", "content": "vztmpl,iso", "enabled": 1, "active": 1},
            {"storage": "local-lvm", "content": "rootdir,images", "enabled": 1, "active": 1},
            {"storage": "tank", "content": "rootdir,vztmpl", "enabled": 1, "active": 1},
        ]

        assert _storage_pools(app, host_id, "rootdir") == ["local-lvm", "tank"]
        assert _storage_pools(app, host_id, "vztmpl") == ["local", "tank"]

    asyncio.run(scenario())


def test_storage_pools_excludes_disabled_and_inactive(tmp_path):
    async def scenario():
        pve = FakePVE()
        app = make_job_app(tmp_path, fake=pve)
        with app.state.sessionmaker() as db:
            host_id = _seed_host_with_token(app, db)

        pve.storages_by_node["pve1"] = [
            {"storage": "good", "content": "rootdir", "enabled": 1, "active": 1},
            {"storage": "off", "content": "rootdir", "enabled": 0, "active": 1},
            {"storage": "down", "content": "rootdir", "enabled": 1, "active": 0},
        ]

        assert _storage_pools(app, host_id, "rootdir") == ["good"]

    asyncio.run(scenario())


def test_storage_pools_raises_when_host_missing(tmp_path):
    async def scenario():
        app = make_job_app(tmp_path, fake=FakePVE())
        with pytest.raises(JobFailed, match="not found"):
            _storage_pools(app, 999, "rootdir")

    asyncio.run(scenario())


def test_storage_pools_raises_when_host_has_no_node_name(tmp_path):
    """A host enrolled but never polled has no node_name recorded yet
    (models/__init__.py:128 is nullable); refuse with a clear reason rather
    than calling client.storages(None)."""
    async def scenario():
        app = make_job_app(tmp_path, fake=FakePVE())
        with app.state.sessionmaker() as db:
            host_id = _seed_host_with_token(app, db, node=None)

        with pytest.raises(JobFailed, match="no node name recorded"):
            _storage_pools(app, host_id, "rootdir")

    asyncio.run(scenario())


def test_host_storage_defaults_start_null(tmp_path):
    """Null means the operator has not chosen. It must stay distinguishable
    from a real pool name, so the resolution order can tell "not asked yet"
    from "asked, and they picked local-lvm"."""
    db = make_db(tmp_path)
    host = seed_host_row(db)

    assert host.default_container_storage is None
    assert host.default_template_storage is None
