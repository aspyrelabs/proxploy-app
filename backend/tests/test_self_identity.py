"""selfguard.py has been waiting since Phase 4 for the installer to tell it
which container Proxploy is. This is that wire."""
from fastapi.testclient import TestClient

from proxploy.services.settings import get_setting
from tests.support import make_app


def test_self_ctid_from_settings_is_persisted_on_boot(tmp_path):
    app = make_app(tmp_path, self_ctid=150)
    with TestClient(app):
        db = app.state.sessionmaker()
        assert get_setting(db, "self.ctid") == 150
        db.close()


def test_absent_self_ctid_writes_nothing(tmp_path):
    """A dev checkout or a bare-metal install has no CTID. selfguard is
    documented to block NOTHING when identity is unknown — writing a bogus
    value here would be worse than writing none."""
    app = make_app(tmp_path)
    with TestClient(app):
        db = app.state.sessionmaker()
        assert get_setting(db, "self.ctid") is None
        db.close()


def test_an_operator_edit_is_not_overwritten_on_the_next_boot(tmp_path):
    """Proxploy can be migrated to another CT; the operator corrects the
    setting, and a restart must not stamp the installer's stale value back."""
    app = make_app(tmp_path, self_ctid=150)
    with TestClient(app):
        pass
    db = app.state.sessionmaker()
    from proxploy.services.settings import set_setting
    set_setting(db, "self.ctid", 151)
    db.commit()
    db.close()

    app2 = make_app(tmp_path, self_ctid=150)
    with TestClient(app2):
        db2 = app2.state.sessionmaker()
        assert get_setting(db2, "self.ctid") == 151
        db2.close()
