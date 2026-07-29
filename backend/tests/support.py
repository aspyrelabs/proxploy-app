"""Shared Phase 2 test builders."""
from pathlib import Path


def make_db(tmp_path: Path):
    """Migrated bare session for service-level tests."""
    from proxploy.config import Settings
    from proxploy.db import make_engine, make_sessionmaker, run_migrations

    s = Settings(db_url=f"sqlite:///{tmp_path}/t.db", data_dir=tmp_path,
                 master_key_file=tmp_path / "master.key")
    run_migrations(s)
    return make_sessionmaker(make_engine(s))()


def seed_host_row(db, name="host-01", node="pve1", status="connected"):
    from proxploy.models import Host

    h = Host(name=name, address="https://10.0.0.9:8006", node_name=node,
             status=status, pve_version="8.4.1")
    db.add(h)
    db.commit()
    return h


def make_app(tmp_path, fake=None, **overrides):
    """App with poller/metrics loops OFF by default; FakePVE optional."""
    from proxploy.api.auth import limiter
    from proxploy.config import Settings
    from proxploy.main import create_app

    limiter.reset()
    kwargs = {}
    if fake is not None:
        from tests.fakes.pve import make_fake_factory
        kwargs["proxmox_factory"] = make_fake_factory(fake)
    overrides.setdefault("poll_enabled", False)
    s = Settings(db_url=f"sqlite:///{tmp_path}/t.db", data_dir=tmp_path,
                 master_key_file=tmp_path / "master.key", **overrides)
    return create_app(s, **kwargs)


def seed_snapshot(app, host_id, **kw):
    """Endpoint tests stuff a snapshot instead of running poll loops."""
    from proxploy.models import utcnow
    from proxploy.pollers import HostSnapshot

    snap = HostSnapshot(host_id=host_id, ts=kw.pop("ts", utcnow()), **kw)
    app.state.poller.snapshots[host_id] = snap
    return snap


def make_job_app(tmp_path, fake=None):
    """Minimal app-shaped namespace for JobBackend/handler unit tests.

    MUST be called from inside a running event loop — `state.loop` is the
    cross-thread hop `JobBackend.enqueue` uses (main.py:74 precedent).
    """
    import asyncio
    from types import SimpleNamespace

    from proxploy.config import Settings
    from proxploy.db import make_engine, make_sessionmaker, run_migrations
    from proxploy.events import EventBus
    from proxploy.secretstore import SecretStore

    s = Settings(db_url=f"sqlite:///{tmp_path}/t.db", data_dir=tmp_path,
                 master_key_file=tmp_path / "master.key")
    run_migrations(s)
    SecretStore.ensure_key_file(s.master_key_file, db_file_exists=False)
    factory = None
    if fake is not None:
        from tests.fakes.pve import make_fake_factory
        factory = make_fake_factory(fake)
    state = SimpleNamespace(
        settings=s,
        sessionmaker=make_sessionmaker(make_engine(s)),
        bus=EventBus(),
        loop=asyncio.get_running_loop(),
        proxmox_factory=factory,
        secretstore=SecretStore(s.master_key_file),
        jobs=None,
    )
    return SimpleNamespace(state=state)
