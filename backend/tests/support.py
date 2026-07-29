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

    h = Host(name=name, address=f"https://{name}:8006", node_name=node,
             status=status, pve_version="8.4.1")
    db.add(h)
    db.commit()
    return h
