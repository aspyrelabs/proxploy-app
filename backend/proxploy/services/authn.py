import hashlib
import secrets
from datetime import timedelta

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from proxploy.models import SessionRow, User, utcnow

_ph = PasswordHasher()  # argon2id, library defaults (doc 08 §5)


def hash_password(pw: str) -> str:
    return _ph.hash(pw)


def verify_password(hash_: str, pw: str) -> bool:
    try:
        return _ph.verify(hash_, pw)
    except VerifyMismatchError:
        return False


# A real argon2id hash of a value nobody can supply, hashed once at import
# rather than per request. Login verifies against this when the email is
# unknown or the account has no password (OIDC-only), so the reply costs the
# same KDF either way instead of returning early and telling a stranger, by
# the clock alone, which addresses have password accounts.
DUMMY_HASH = _ph.hash(secrets.token_urlsafe(32))


def _th(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def create_session(db, user: User, ip: str | None, user_agent: str | None,
                   ttl_hours: int) -> str:
    raw = secrets.token_urlsafe(32)
    db.add(SessionRow(user_id=user.id, token_hash=_th(raw), ip=ip,
                      user_agent=user_agent, last_seen_at=utcnow(),
                      expires_at=utcnow() + timedelta(hours=ttl_hours)))
    user.last_login_at = utcnow()
    db.commit()
    return raw


def resolve_session(db, raw: str) -> User | None:
    row = db.query(SessionRow).filter_by(token_hash=_th(raw)).one_or_none()
    if not row or row.revoked_at or row.expires_at < utcnow():
        return None
    user = db.get(User, row.user_id)
    return user if user and user.is_active else None


def revoke_session(db, raw: str) -> None:
    row = db.query(SessionRow).filter_by(token_hash=_th(raw)).one_or_none()
    if row and not row.revoked_at:
        row.revoked_at = utcnow()
        db.commit()
