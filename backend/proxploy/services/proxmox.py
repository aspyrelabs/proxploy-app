"""The ONE Proxmox client layer (docs 02 §4, 11 §7). Every proxmoxer call and every
PVE-8-vs-9 behavioural branch lives here — never in routers, pollers, or jobs.
(No version branches exist yet; when PVE 9 diverges, branch on self.version()["release"]
inside this module only.) Scoped API tokens, never root@pam passwords (doc 00 §8)."""
import hashlib
import socket
import ssl
from urllib.parse import urlparse

from proxploy.models import utcnow  # noqa: F401  (used by later phases' sync paths)


class ProxmoxError(RuntimeError):
    pass


def parse_token_id(token_id: str) -> tuple[str, str]:
    user, sep, name = token_id.partition("!")
    if not sep or "@" not in user or not name:
        raise ProxmoxError(
            f"token id {token_id!r} must look like user@realm!tokenname")
    return user, name


def default_factory(**kwargs):
    from proxmoxer import ProxmoxAPI

    return ProxmoxAPI(**kwargs)


def tls_fingerprint_sha256(host: str, port: int = 8006) -> str:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE  # we are fetching the cert to pin it, not trusting it
    with socket.create_connection((host, port), timeout=10) as sock:
        with ctx.wrap_socket(sock, server_hostname=host) as tls:
            der = tls.getpeercert(binary_form=True)
    digest = hashlib.sha256(der).hexdigest().upper()
    return ":".join(digest[i:i + 2] for i in range(0, len(digest), 2))


class ProxmoxClient:
    def __init__(self, address: str, token_id: str, token_secret: str,
                 verify_tls: bool = True, tls_fingerprint: str | None = None,
                 factory=None):
        self.address = address
        self.token_id = token_id
        self.token_secret = token_secret
        self.verify_tls = verify_tls
        self.tls_fingerprint = tls_fingerprint
        self._factory = factory or default_factory
        self._api = None

    def _connect(self):
        if self._api is not None:
            return self._api
        url = urlparse(self.address)
        host, port = url.hostname, url.port or 8006
        if not self.verify_tls and self.tls_fingerprint:
            seen = tls_fingerprint_sha256(host, port)
            if seen != self.tls_fingerprint.upper():
                raise ProxmoxError(
                    f"TLS fingerprint mismatch: pinned {self.tls_fingerprint}, got {seen}")
        user, token_name = parse_token_id(self.token_id)
        try:
            self._api = self._factory(host=host, port=port, user=user,
                                      token_name=token_name,
                                      token_value=self.token_secret,
                                      verify_ssl=self.verify_tls)
        except Exception as e:
            raise ProxmoxError(f"cannot connect to {self.address}: {e}") from e
        return self._api

    def version(self) -> dict:
        try:
            return self._connect().version.get()
        except ProxmoxError:
            raise
        except Exception as e:
            raise ProxmoxError(f"version check failed: {e}") from e

    def permissions(self) -> dict:
        try:
            return self._connect().access.permissions.get()
        except ProxmoxError:
            raise
        except Exception as e:
            raise ProxmoxError(f"permission read failed: {e}") from e

    def cluster_resources(self) -> list[dict]:
        """One bulk call: every node/CT/VM/storage row for this endpoint.

        The poll loop's only guest-state source — per-guest calls are
        forbidden in the poller (doc 02 §3 O(nodes) budget).
        """
        try:
            return self._connect().cluster.resources.get()
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001 — one wrap point, like version()
            raise ProxmoxError(f"cluster/resources failed: {e}") from e

    def node_rrddata(self, node: str, timeframe: str = "hour") -> list[dict]:
        """History-quality per-node series (netin/netout/cpu/mem), doc 02 §11.1."""
        try:
            return self._connect().nodes(node).rrddata.get(timeframe=timeframe)
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise ProxmoxError(f"rrddata failed for node {node!r}: {e}") from e
