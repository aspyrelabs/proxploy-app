"""Self-management guardrail (doc 02 §9, doc 08 §1 and §9 row 14).

Detection can miss — an unset identity must NEVER block an action, because the
typed-confirmation prompt is the backstop, not the only guard."""
from proxploy.models import App
from proxploy.services.selfguard import DESTRUCTIVE, is_self
from proxploy.services.settings import set_setting
from tests.support import make_db, seed_host_row


def _app(db, host, ctid=150):
    a = App(host_id=host.id, ctid=ctid, name="Proxploy", slug=f"proxploy-{ctid}")
    db.add(a)
    db.commit()
    return a


def test_destructive_set_matches_doc_08():
    assert DESTRUCTIVE == frozenset({"stop", "shutdown", "restart", "pause"})


def test_unset_identity_never_blocks(tmp_path):
    db = make_db(tmp_path)
    a = _app(db, seed_host_row(db))
    assert is_self(db, "app", a.id) is False


def test_matching_ctid_and_host_is_self(tmp_path):
    db = make_db(tmp_path)
    host = seed_host_row(db)
    a = _app(db, host, ctid=150)
    set_setting(db, "self.ctid", 150)
    set_setting(db, "self.host_id", host.id)
    assert is_self(db, "app", a.id) is True


def test_matching_ctid_on_a_different_host_is_not_self(tmp_path):
    db = make_db(tmp_path)
    host_a = seed_host_row(db, name="host-01", node="pve1")
    host_b = seed_host_row(db, name="host-02", node="pve2")
    a = _app(db, host_b, ctid=150)
    set_setting(db, "self.ctid", 150)
    set_setting(db, "self.host_id", host_a.id)
    assert is_self(db, "app", a.id) is False


def test_vms_are_never_self(tmp_path):
    db = make_db(tmp_path)
    set_setting(db, "self.ctid", 150)
    assert is_self(db, "vm", 1) is False


# --- Fix round 1 (code review) --------------------------------------------


def test_malformed_ctid_setting_fails_open_instead_of_raising(tmp_path):
    """A non-numeric self.ctid (e.g. hand-edited or corrupted) must return
    False, same as an unset one — not throw ValueError up into the route."""
    db = make_db(tmp_path)
    a = _app(db, seed_host_row(db))
    set_setting(db, "self.ctid", "ct-150")
    assert is_self(db, "app", a.id) is False


def test_malformed_host_id_setting_fails_open_instead_of_raising(tmp_path):
    db = make_db(tmp_path)
    host = seed_host_row(db)
    a = _app(db, host, ctid=150)
    set_setting(db, "self.ctid", 150)
    set_setting(db, "self.host_id", "")
    assert is_self(db, "app", a.id) is False
