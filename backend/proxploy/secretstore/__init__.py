"""SecretStore seam (brief §5): Fernet/MultiFernet, master key in a root-only file.

OpenBao is the arm's-length swap-in; nothing outside this module may know the backend.
"""
from pathlib import Path

from cryptography.fernet import Fernet, MultiFernet


class MasterKeyMissing(RuntimeError):
    pass


class SecretStore:
    def __init__(self, key_file: Path):
        keys = [Fernet(line) for line in key_file.read_text().split() if line]
        if not keys:
            raise MasterKeyMissing(f"{key_file} contains no keys")
        self._fernet = MultiFernet(keys)
        self.key_version = len(keys)  # newest key is line 1; version = generation count

    @classmethod
    def ensure_key_file(cls, path: Path, db_file_exists: bool) -> None:
        if path.exists():
            return
        if db_file_exists:
            # Doc 11 §9: never silently regenerate a key over an existing DB —
            # that would strand every stored credential as ambiguous ciphertext.
            raise MasterKeyMissing(
                f"master key {path} is missing but a database already exists. "
                "Restore the key file from backup, or delete the database to re-onboard."
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch(mode=0o600)
        path.write_text(Fernet.generate_key().decode() + "\n")
        path.chmod(0o400)

    def encrypt(self, data: bytes) -> tuple[bytes, int]:
        return self._fernet.encrypt(data), self.key_version

    def decrypt(self, blob: bytes) -> bytes:
        return self._fernet.decrypt(blob)

    def reencrypt(self, blob: bytes) -> tuple[bytes, int]:
        return self._fernet.rotate(blob), self.key_version
