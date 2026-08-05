"""TOTP enrollment and verification (doc 08 §5, Phase 8 Task 8).

Recovery-code hashes live in their own table (`TotpRecoveryCode`), NOT packed
as JSON inside `users.totp_secret_enc` as the original plan called for --
see the migration docstring (6cf6a0722d23_0005_totp_recovery_codes.py) and
docs/notes/phase-8-scale.md for why that zero-migration design was rejected
mid-implementation. `totp_secret_enc` holds exactly what its name says: the
Fernet-encrypted base32 TOTP seed, nothing else.

Recovery codes are `secrets.token_hex(2)` x2 joined with "-" (e.g.
"a3f1-9c02", ~32 bits of entropy) -- short enough to copy down by hand, not
brute-force resistant by length alone. That's by design: the login rate
limit (10/minute, api/auth.py) and Task 9's 5-attempt pending-session burn
are what close off guessing, not code length.

Each code's argon2 hash (services/authn.py::hash_password's idiom -- the
same one-way hashing passwords get, so a code is never stored recoverable)
is itself Fernet-encrypted at rest via SecretStore, matching how
totp_secret_enc is handled. Burning a code is a plain
`UPDATE ... WHERE used_at IS NULL` (services/consoletickets.py's
atomic-redeem pattern) -- never a decrypt/mutate/re-encrypt of a shared
blob, so two requests racing to redeem the same code can't both win: only
one UPDATE matches the WHERE clause.
"""
import secrets

import pyotp

from proxploy.models import TotpRecoveryCode, User, utcnow
from proxploy.services.authn import hash_password, verify_password

RECOVERY_CODE_COUNT = 10
ISSUER = "Proxploy"


def _gen_recovery_codes() -> list[str]:
    return ["-".join(secrets.token_hex(2) for _ in range(2))
            for _ in range(RECOVERY_CODE_COUNT)]


def start_enrollment(db, secretstore, user: User) -> dict:
    """Generates a fresh secret + 10 recovery codes, persists them encrypted
    with `totp_enabled` left False -- confirm() below is the only thing that
    flips it, so a secret alone never enables TOTP. Replaces any previous/
    pending secret and codes (re-enrolling before confirm overwrites the
    pending state; the route layer is what refuses to re-enroll while
    already enabled). The raw secret and raw codes are returned here and
    NEVER again -- nothing recoverable is ever persisted."""
    secret = pyotp.random_base32()
    codes = _gen_recovery_codes()

    enc, _key_version = secretstore.encrypt(secret.encode())
    user.totp_secret_enc = enc
    user.totp_enabled = False

    db.query(TotpRecoveryCode).filter_by(user_id=user.id).delete(synchronize_session=False)
    for code in codes:
        hash_enc, _key_version = secretstore.encrypt(hash_password(code).encode())
        db.add(TotpRecoveryCode(user_id=user.id, code_hash_enc=hash_enc))
    db.commit()

    uri = pyotp.TOTP(secret).provisioning_uri(name=user.email, issuer_name=ISSUER)
    return {"secret": secret, "otpauth_uri": uri, "recovery_codes": codes}


def confirm(db, secretstore, user: User, code: str) -> bool:
    """Flips totp_enabled on proof of possession. Enrollment is not complete
    on the strength of generating a secret alone -- a wrong/missing code
    leaves totp_enabled False and nothing is written."""
    if not user.totp_secret_enc:
        return False
    secret = secretstore.decrypt(user.totp_secret_enc).decode()
    if not pyotp.TOTP(secret).verify(code, valid_window=1):
        return False
    user.totp_enabled = True
    db.commit()
    return True


def verify_login(db, secretstore, user: User, code: str) -> bool:
    """Accepts a current TOTP code (valid_window=1, ~±30s) or an unused
    recovery code. A matched recovery code is burned atomically before this
    returns True, so it can never be replayed."""
    if not user.totp_enabled or not user.totp_secret_enc:
        return False
    secret = secretstore.decrypt(user.totp_secret_enc).decode()
    if pyotp.TOTP(secret).verify(code, valid_window=1):
        return True
    for row in (db.query(TotpRecoveryCode)
                .filter_by(user_id=user.id, used_at=None)
                .order_by(TotpRecoveryCode.id)):
        hash_ = secretstore.decrypt(row.code_hash_enc).decode()
        if not verify_password(hash_, code):
            continue
        # Atomicity boundary: two concurrent requests can both reach this
        # point having decrypted+matched the same row, but only one UPDATE
        # can satisfy `used_at IS NULL` -- the loser's rowcount is 0.
        burned = (db.query(TotpRecoveryCode)
                  .filter(TotpRecoveryCode.id == row.id, TotpRecoveryCode.used_at.is_(None))
                  .update({"used_at": utcnow()}))
        db.commit()
        return burned > 0
    return False


def disable(db, user: User) -> None:
    """Clears the secret and disables TOTP, and drops the recovery codes
    with it -- leaving them behind would let a stale code outlive the
    enrollment it was issued for."""
    user.totp_secret_enc = None
    user.totp_enabled = False
    db.query(TotpRecoveryCode).filter_by(user_id=user.id).delete(synchronize_session=False)
    db.commit()
