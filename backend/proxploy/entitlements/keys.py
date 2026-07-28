"""kid-keyed set of valid Ed25519 public keys (docs 07 §4, 09). The app bundles a
SET so key rotation is an overlap window, not a flag day. Private keys never
exist in this repo."""
import json

BUNDLED_PUBLIC_KEYS: dict[str, str] = {
    # "dev-2026-07": pasted in Task 9 from proxploy-api's gen_signing_key.py output
}


def load_public_keys(settings) -> dict[str, str]:
    keys = dict(BUNDLED_PUBLIC_KEYS)
    if settings.ent_extra_keys_file and settings.ent_extra_keys_file.exists():
        keys.update(json.loads(settings.ent_extra_keys_file.read_text()))
    return keys
