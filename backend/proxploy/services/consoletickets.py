"""Single-use, short-TTL console websocket tickets (doc 05 §Streaming "Auth
model for streams"). Same hash-at-rest shape as services/authn.py's
create_session/resolve_session, a new table because these bind to a Proxmox
target + upstream ticket, which sessions don't carry."""
import hashlib
import secrets
from datetime import datetime, timedelta

from proxploy.models import ConsoleTicket, utcnow


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def mint_ticket(db, *, user_id: int, kind: str, target_id: int, node: str,
                guest_kind: str | None, vmid: int | None, upstream_user: str,
                upstream_ticket: str, upstream_port: str,
                ttl_s: float) -> tuple[str, datetime]:
    raw = secrets.token_urlsafe(32)
    expires_at = utcnow() + timedelta(seconds=ttl_s)
    db.add(ConsoleTicket(
        user_id=user_id, kind=kind, target_id=target_id, node=node,
        guest_kind=guest_kind, vmid=vmid, upstream_user=upstream_user,
        upstream_ticket=upstream_ticket, upstream_port=upstream_port,
        token_hash=_hash(raw), expires_at=expires_at,
    ))
    db.commit()
    return raw, expires_at


def redeem_ticket(db, raw: str) -> ConsoleTicket | None:
    """Redeems exactly once. The UPDATE...WHERE redeemed_at IS NULL below is
    the atomicity boundary: two concurrent redemptions of the same raw value
    can both SELECT the row, but only one UPDATE can match `redeemed_at IS
    NULL`, so the loser's rowcount is 0 and it gets None, same as if the
    ticket had never existed."""
    row = db.query(ConsoleTicket).filter_by(token_hash=_hash(raw)).one_or_none()
    if row is None or row.expires_at < utcnow():
        return None
    updated = (db.query(ConsoleTicket)
               .filter(ConsoleTicket.id == row.id, ConsoleTicket.redeemed_at.is_(None))
               .update({"redeemed_at": utcnow()}))
    db.commit()
    if updated == 0:
        return None
    db.refresh(row)
    return row
