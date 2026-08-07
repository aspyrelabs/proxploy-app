"""kid-keyed set of valid Ed25519 public keys (docs 07 §4, 09). The app bundles a
SET so key rotation is an overlap window, not a flag day. Private keys never
exist in this repo.

Keys are written as the bare base64 body, without BEGIN/END lines. That is
the same bytes a PEM carries, minus two label lines that say what the bytes
are without contributing any. `load_public_keys` normalises whatever it finds
to canonical PEM, so entitlements/client.py always hands PyJWT a PEM and the
ent_extra_keys_file overlay can use either spelling.
"""
import json
import logging

from proxploy.pubkey import load_public_key, to_pem

logger = logging.getLogger(__name__)

BUNDLED_PUBLIC_KEYS: dict[str, str] = {
    "dev-2026-07": "MCowBQYDK2VwAyEAurBzDvib5NysbwvfTbH03wWhhadmH3xgPQ11TdEE5DQ=",
}


def load_public_keys(settings) -> dict[str, str]:
    keys = dict(BUNDLED_PUBLIC_KEYS)
    if settings.ent_extra_keys_file and settings.ent_extra_keys_file.exists():
        keys.update(json.loads(settings.ent_extra_keys_file.read_text()))
    # A key that does not parse is dropped rather than raising: one bad entry
    # in an operator-supplied overlay must not take out the bundled set with
    # it. A dropped kid then fails closed at verify time as "unknown signing
    # key id", which is the same path an unrecognised kid already takes.
    # Never silently: a dropped key looks exactly like a key that was never
    # added, and that is a bad hour to spend.
    out = {}
    for kid, value in keys.items():
        try:
            out[kid] = to_pem(load_public_key(value))
        except (ValueError, TypeError) as e:
            logger.error("entitlement public key %r is unreadable and was "
                         "dropped; tokens signed with it will be rejected "
                         "as an unknown key id (%s)", kid, type(e).__name__)
    return out
