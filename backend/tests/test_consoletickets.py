from datetime import timedelta

from proxploy.models import User, utcnow
from proxploy.services.consoletickets import mint_ticket, redeem_ticket
from tests.support import make_db


def _mint(db, user_id=1, **overrides):
    # console_tickets.user_id is FK -> users.id (ondelete=CASCADE); seed the
    # row so the insert doesn't trip sqlite's PRAGMA foreign_keys=ON.
    if db.get(User, user_id) is None:
        db.add(User(id=user_id, email=f"u{user_id}@example.test"))
        db.commit()
    kwargs = dict(user_id=user_id, kind="app_console", target_id=42, node="pve1",
                  guest_kind="lxc", vmid=150, upstream_user="proxploy@pve!console",
                  upstream_ticket="PVEVNC:abc", upstream_port="5900", ttl_s=30.0)
    kwargs.update(overrides)
    return mint_ticket(db, **kwargs)


def test_redeem_returns_the_row_with_upstream_fields(tmp_path):
    db = make_db(tmp_path)
    raw, expires_at = _mint(db)
    assert expires_at > utcnow()
    row = redeem_ticket(db, raw)
    assert row is not None
    assert row.kind == "app_console" and row.target_id == 42
    assert row.node == "pve1" and row.guest_kind == "lxc" and row.vmid == 150
    assert row.upstream_ticket == "PVEVNC:abc" and row.upstream_port == "5900"
    assert row.redeemed_at is not None


def test_redeem_is_single_use(tmp_path):
    db = make_db(tmp_path)
    raw, _ = _mint(db)
    assert redeem_ticket(db, raw) is not None
    assert redeem_ticket(db, raw) is None  # second redemption fails


def test_redeem_rejects_unknown_ticket(tmp_path):
    db = make_db(tmp_path)
    assert redeem_ticket(db, "not-a-real-ticket") is None


def test_redeem_rejects_expired_ticket(tmp_path):
    db = make_db(tmp_path)
    raw, _ = _mint(db, ttl_s=-1.0)  # already expired
    assert redeem_ticket(db, raw) is None


def test_raw_ticket_value_is_not_persisted(tmp_path):
    from proxploy.models import ConsoleTicket

    db = make_db(tmp_path)
    raw, _ = _mint(db)
    row = db.query(ConsoleTicket).one()
    assert raw not in row.token_hash
    assert row.upstream_ticket == "PVEVNC:abc"  # only the UPSTREAM ticket is
    # stored in the clear: that one never reaches the browser (doc 02 §5);
    # OUR ticket (`raw`, the browser-facing one) is what gets hashed.
