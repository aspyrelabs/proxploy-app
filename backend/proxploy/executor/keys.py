"""The one place allowed to pull the SSH private key out of SecretStore
(doc 08 §4). scripts/check_executor_isolation.py fails the build if
`get_ssh_private_key` is referenced anywhere outside `executor/`."""
from proxploy.models import HostCredential


def get_ssh_private_key(db, secretstore, host_id: int) -> bytes:
    cred = (db.query(HostCredential)
            .filter_by(host_id=host_id, kind="ssh_key").one_or_none())
    if cred is None:
        raise LookupError(f"host {host_id} has no ssh_key credential")
    return secretstore.decrypt(cred.encrypted_blob)
