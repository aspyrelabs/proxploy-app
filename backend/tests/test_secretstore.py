import os
import stat

import pytest


def test_roundtrip_and_perms(tmp_path):
    from proxploy.secretstore import SecretStore

    kf = tmp_path / "master.key"
    SecretStore.ensure_key_file(kf, db_file_exists=False)
    assert stat.S_IMODE(os.stat(kf).st_mode) == 0o400
    ss = SecretStore(kf)
    blob, ver = ss.encrypt(b"proxploy@pve!ro=SECRET")
    assert ver == 1 and blob != b"proxploy@pve!ro=SECRET"
    assert ss.decrypt(blob) == b"proxploy@pve!ro=SECRET"


def test_refuses_regenerate_over_existing_db(tmp_path):
    from proxploy.secretstore import MasterKeyMissing, SecretStore

    with pytest.raises(MasterKeyMissing):
        SecretStore.ensure_key_file(tmp_path / "master.key", db_file_exists=True)


def test_rotation_decrypts_old_and_reencrypts(tmp_path):
    from cryptography.fernet import Fernet

    from proxploy.secretstore import SecretStore

    kf = tmp_path / "master.key"
    SecretStore.ensure_key_file(kf, db_file_exists=False)
    old = SecretStore(kf)
    blob, _ = old.encrypt(b"s3cret")
    kf.chmod(0o600)
    kf.write_text(Fernet.generate_key().decode() + "\n" + kf.read_text())
    kf.chmod(0o400)
    new = SecretStore(kf)
    assert new.key_version == 2
    assert new.decrypt(blob) == b"s3cret"
    blob2, ver2 = new.reencrypt(blob)
    assert ver2 == 2 and new.decrypt(blob2) == b"s3cret"
