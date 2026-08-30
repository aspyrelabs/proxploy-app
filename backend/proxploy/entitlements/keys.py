"""kid-keyed set of trusted ROOT Ed25519 public keys (docs 07 §4, 09). The app
bundles a SET so root rotation is an overlap window, not a flag day. Private
keys never exist in this repo; the real root is generated offline by a human,
in a later phase, and is not something this file (or any agent) may fabricate.

Keys are written as the bare base64 body, without BEGIN/END lines. That is
the same bytes a PEM carries, minus two label lines that say what the bytes
are without contributing any. `load_root_keys` normalises whatever it finds
to canonical PEM, so entitlements/client.py always hands PyJWT a PEM and the
ent_extra_roots_file overlay can use either spelling.

A root's only job is signing certificates (entitlements/client.py::verify_cert);
this map never holds a leaf key. That is what makes the token -> leaf ->
cert -> root chain depth-1 by construction rather than by a flag: a leaf's
kid is never a key in BUNDLED_ROOT_KEYS, so a leaf can never stand in as a
cert's signer. There is no CA:TRUE-equivalent bit to get wrong, because there
is no code path that would ever look a leaf up here.
"""
import json
import logging

from proxploy.pubkey import load_public_key, to_pem

logger = logging.getLogger(__name__)

BUNDLED_ROOT_KEYS: dict[str, str] = {
    "dev-root-2026-08": "MCowBQYDK2VwAyEA3NOMW8kyo7nHgNnqglZiqEjDI68uy/ZTMdbOQhiC9U0=",
}


def load_root_keys(settings) -> dict[str, str]:
    keys = dict(BUNDLED_ROOT_KEYS)
    if settings.ent_extra_roots_file and settings.ent_extra_roots_file.exists():
        keys.update(json.loads(settings.ent_extra_roots_file.read_text()))
    # A key that does not parse is dropped rather than raising: one bad entry
    # in an operator-supplied overlay must not take out the bundled set with
    # it. A dropped kid then fails closed at verify time as "unknown root
    # key id", which is the same path an unrecognised kid already takes.
    # Never silently: a dropped key looks exactly like a key that was never
    # added, and that is a bad hour to spend.
    out = {}
    for kid, value in keys.items():
        try:
            out[kid] = to_pem(load_public_key(value))
        except (ValueError, TypeError) as e:
            logger.error("entitlement root key %r is unreadable and was "
                         "dropped; certs signed with it will be rejected "
                         "as an unknown root key id (%s)", kid, type(e).__name__)
    return out
