def _db(tmp_path):
    from proxploy.config import Settings
    from proxploy.db import make_engine, make_sessionmaker, run_migrations

    s = Settings(db_url=f"sqlite:///{tmp_path}/a.db")
    run_migrations(s)
    return make_sessionmaker(make_engine(s))()


def test_write_audit_redacts_secrets(tmp_path):
    from proxploy.models import AuditEvent
    from proxploy.services.audit import write_audit

    db = _db(tmp_path)
    write_audit(db, actor_type="user", actor_id=1, action="host.create",
                target_type="host", target_id=2,
                params={"name": "pve-01", "token_secret": "abc",
                        "nested": {"password": "x"}})
    row = db.query(AuditEvent).one()
    assert row.action == "host.create" and row.result == "ok"
    assert row.params["name"] == "pve-01"
    assert row.params["token_secret"] == "[redacted]"
    assert row.params["nested"]["password"] == "[redacted]"


def test_no_update_or_delete_helpers():
    import proxploy.services.audit as m
    assert not any(n.startswith(("update", "delete")) for n in dir(m))
