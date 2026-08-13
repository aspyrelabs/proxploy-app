"""Task 1: _storage_pools resolves the enabled and active pools on a host's
node that carry a given content type, the API-side equivalent of build.func's
`pvesm status -content "$content"` picker that Tasks 3/4 will use to avoid
that picker going interactive on a host with more than one candidate pool.

Task 4 adds the two tests at the bottom of this file: they drive run_install
itself (not just resolve_storage_pools) to prove the command that actually
reaches the wire carries mode=generated and both storage variables."""
import asyncio

import pytest

from proxploy.jobs import JobBackend, JobContext, JobFailed
from proxploy.models import Host
from proxploy.services.appstore import _storage_pools, resolve_storage_pools, run_install
from tests.fakes.pve import FakePVE
from tests.fakes.ssh import FakeSSHConnection, make_fake_connect_factory
from tests.support import make_db, make_job_app, seed_host_row
from tests.test_appstore_install import _seed_installable_host


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


def test_sole_candidate_is_not_a_pick(tmp_path):
    """One candidate is not a choice, so using it answers nothing on the
    operator's behalf."""
    async def scenario():
        pve = FakePVE()
        app = make_job_app(tmp_path, fake=pve)
        with app.state.sessionmaker() as db:
            host_id = _seed_host_with_token(app, db)

        pve.storages_by_node["pve1"] = [
            {"storage": "local", "content": "vztmpl", "enabled": 1, "active": 1},
            {"storage": "local-lvm", "content": "rootdir", "enabled": 1, "active": 1},
        ]

        assert resolve_storage_pools(app, host_id, {}) == ("local-lvm", "local")

    asyncio.run(scenario())


def test_refuses_rather_than_picking_when_ambiguous(tmp_path):
    """THE RULE OF THIS SPEC. Which pool a container lives on is a question,
    and picking one is answering it for the operator. Never auto-pick, not by
    free space, not by name, not by order."""
    async def scenario():
        pve = FakePVE()
        app = make_job_app(tmp_path, fake=pve)
        with app.state.sessionmaker() as db:
            host_id = _seed_host_with_token(app, db)

        pve.storages_by_node["pve1"] = [
            {"storage": "local", "content": "vztmpl", "enabled": 1, "active": 1},
            {"storage": "lvm-a", "content": "rootdir", "enabled": 1, "active": 1},
            {"storage": "lvm-b", "content": "rootdir", "enabled": 1, "active": 1},
        ]

        with pytest.raises(JobFailed) as e:
            resolve_storage_pools(app, host_id, {})
        assert "lvm-a" in str(e.value) and "lvm-b" in str(e.value)

    asyncio.run(scenario())


def test_supplied_beats_remembered(tmp_path):
    """A remembered default is only a fallback; whatever the operator picked
    for this particular install wins over it."""
    async def scenario():
        pve = FakePVE()
        app = make_job_app(tmp_path, fake=pve)
        with app.state.sessionmaker() as db:
            host_id = _seed_host_with_token(app, db)
            host = db.get(Host, host_id)
            host.default_container_storage = "lvm-a"
            db.commit()

        pve.storages_by_node["pve1"] = [
            {"storage": "local", "content": "vztmpl", "enabled": 1, "active": 1},
            {"storage": "lvm-a", "content": "rootdir", "enabled": 1, "active": 1},
            {"storage": "lvm-b", "content": "rootdir", "enabled": 1, "active": 1},
        ]

        got = resolve_storage_pools(app, host_id, {"container_storage": "lvm-b"})
        assert got[0] == "lvm-b"

    asyncio.run(scenario())


def test_stale_remembered_pool_reasks_rather_than_substituting(tmp_path):
    """A remembered pool that no longer carries rootdir must not be silently
    replaced with another one. Sending it anyway hits build.func's
    resolve_storage_preselect 238 path, where it spins in an empty while true."""
    async def scenario():
        pve = FakePVE()
        app = make_job_app(tmp_path, fake=pve)
        with app.state.sessionmaker() as db:
            host_id = _seed_host_with_token(app, db)
            host = db.get(Host, host_id)
            host.default_container_storage = "retired-pool"
            db.commit()

        pve.storages_by_node["pve1"] = [
            {"storage": "local", "content": "vztmpl", "enabled": 1, "active": 1},
            {"storage": "lvm-a", "content": "rootdir", "enabled": 1, "active": 1},
            {"storage": "lvm-b", "content": "rootdir", "enabled": 1, "active": 1},
        ]

        with pytest.raises(JobFailed) as e:
            resolve_storage_pools(app, host_id, {})
        assert "retired-pool" in str(e.value)

    asyncio.run(scenario())


def test_remembered_pool_wins_when_nothing_supplied(tmp_path):
    """Positive coverage for the remembered-wins branch (`if remembered in
    candidates: resolved.append(remembered)`), which until now was only
    exercised by its failure sibling
    (test_stale_remembered_pool_reasks_rather_than_substituting) and by
    test_supplied_beats_remembered, whose `got[0] == "lvm-b"` assertion would
    pass identically even if Host.default_container_storage were never read
    at all, because the operator's own override already forces "lvm-b".

    Nothing in Part A ever WRITES that column (Part B does), so until this
    test existed the only LIVE branch of the remembered-value logic was the
    refusal. This proves the pick-it-back-up branch actually reads the
    column, and that a valid memory does not spuriously trip the never-pick
    refusal even though the node has two rootdir candidates.
    """
    async def scenario():
        pve = FakePVE()
        app = make_job_app(tmp_path, fake=pve)
        with app.state.sessionmaker() as db:
            host_id = _seed_host_with_token(app, db)
            host = db.get(Host, host_id)
            host.default_container_storage = "lvm-a"
            db.commit()

        pve.storages_by_node["pve1"] = [
            {"storage": "local", "content": "vztmpl", "enabled": 1, "active": 1},
            {"storage": "lvm-a", "content": "rootdir", "enabled": 1, "active": 1},
            {"storage": "lvm-b", "content": "rootdir", "enabled": 1, "active": 1},
        ]

        got = resolve_storage_pools(app, host_id, {})
        assert got[0] == "lvm-a"

    asyncio.run(scenario())


def test_supplied_pool_invalid_for_the_node_is_refused(tmp_path):
    async def scenario():
        pve = FakePVE()
        app = make_job_app(tmp_path, fake=pve)
        with app.state.sessionmaker() as db:
            host_id = _seed_host_with_token(app, db)

        pve.storages_by_node["pve1"] = [
            {"storage": "local", "content": "vztmpl", "enabled": 1, "active": 1},
            {"storage": "lvm-a", "content": "rootdir", "enabled": 1, "active": 1},
        ]

        with pytest.raises(JobFailed) as e:
            resolve_storage_pools(app, host_id, {"container_storage": "nope"})
        assert "nope" in str(e.value)

    asyncio.run(scenario())


def test_non_string_override_value_is_coerced_not_a_crash(tmp_path):
    """The API validator (catalog.py) constrains override KEYS to a
    shell-identifier pattern but never checks value types, so
    {"overrides": {"container_storage": 5}} reaches resolve_storage_pools as
    a bare int. Before coercing with str(...) this raised AttributeError from
    `(5).strip()` instead of one of this function's deliberately-written
    JobFailed messages: fails closed either way, but this proves it fails
    closed with the readable message, not an opaque crash.
    """
    async def scenario():
        pve = FakePVE()
        app = make_job_app(tmp_path, fake=pve)
        with app.state.sessionmaker() as db:
            host_id = _seed_host_with_token(app, db)

        pve.storages_by_node["pve1"] = [
            {"storage": "local", "content": "vztmpl", "enabled": 1, "active": 1},
            {"storage": "lvm-a", "content": "rootdir", "enabled": 1, "active": 1},
        ]

        with pytest.raises(JobFailed) as e:
            resolve_storage_pools(app, host_id, {"container_storage": 5})
        assert "5" in str(e.value)

    asyncio.run(scenario())


# --- Task 4: run_install itself must send mode=generated and both pools -----


def _run_a_default_install(tmp_path, pve, *, ctid=150):
    """Drives run_install exactly like test_appstore_install.py's own tests
    do, and hands back the FakeSSHConnection so a test can read
    `.last_command`. `pve.storages_by_node["pve1"]` must already be set by
    the caller before this runs.
    """
    app = make_job_app(tmp_path, fake=pve)
    with app.state.sessionmaker() as db:
        host_id = _seed_installable_host(app, db)

    def _on_create_process(command):
        pve.add_ct(ctid, node="pve1", name="redis", status="running")

    fake = FakeSSHConnection(host_key_fingerprint="SHA256:abc", stdout_lines=[],
                             stderr_lines=[], exit_status=0,
                             on_create_process=_on_create_process)
    app.state.ssh_connect_factory = make_fake_connect_factory(fake)

    ctx = JobContext(JobBackend(app), job_id=1)
    return app, host_id, ctx, fake


def test_default_install_with_no_user_input_sends_both_storage_vars(tmp_path):
    """NAMED REGRESSION TEST. The future change this exists to stop is a
    tidy-up that omits storage when the operator did not touch it. That looks
    like sending less noise, reintroduces build.func's interactive picker, and
    fails ONLY on hosts with two or more candidates, so it passes on any
    single-storage development box.
    """
    async def scenario():
        pve = FakePVE()
        pve.storages_by_node["pve1"] = [
            {"storage": "local", "content": "vztmpl", "enabled": 1, "active": 1},
            {"storage": "local-lvm", "content": "rootdir", "enabled": 1, "active": 1},
        ]
        _, host_id, ctx, fake = _run_a_default_install(tmp_path, pve)

        await run_install(ctx, {"catalog_slug": "redis", "host_id": host_id,
                                "name": "Redis", "ctid": 150, "overrides": {}})

        cmd = fake.last_command
        assert "var_container_storage=local-lvm" in cmd
        assert "var_template_storage=local" in cmd

    asyncio.run(scenario())


def test_mode_is_generated_never_default(tmp_path):
    """mode=default is the ONLY branch that runs
    defaults_target=$(ensure_global_default_vars_file), which is what reaches
    the interactive storage picker at build.func:3533. The generated branch is
    byte-identical apart from METHOD, which only reaches telemetry. Reverting
    this silently reintroduces the silent exit 0.
    """
    async def scenario():
        pve = FakePVE()
        pve.storages_by_node["pve1"] = [
            {"storage": "local", "content": "vztmpl", "enabled": 1, "active": 1},
            {"storage": "local-lvm", "content": "rootdir", "enabled": 1, "active": 1},
        ]
        _, host_id, ctx, fake = _run_a_default_install(tmp_path, pve)

        await run_install(ctx, {"catalog_slug": "redis", "host_id": host_id,
                                "name": "Redis", "ctid": 150, "overrides": {}})

        cmd = fake.last_command
        assert "mode=generated" in cmd
        assert "mode=default" not in cmd

    asyncio.run(scenario())
