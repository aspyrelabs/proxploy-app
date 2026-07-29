"""The ONE Proxmox client layer (docs 02 §4, 11 §7). Every proxmoxer call and every
PVE-8-vs-9 behavioural branch lives here — never in routers, pollers, or jobs.
(No version branches exist yet; when PVE 9 diverges, branch on self.version()["release"]
inside this module only.) Scoped API tokens, never root@pam passwords (doc 00 §8)."""
import hashlib
import re
import socket
import ssl
from urllib.parse import urlparse

from proxploy.models import utcnow  # noqa: F401  (used by later phases' sync paths)


class ProxmoxError(RuntimeError):
    pass


# Proxmox's own status verbs. Proxploy's user-facing vocabulary maps onto these
# in services/lifecycle.py — the gap is stated once, there.
LXC_ACTIONS = frozenset({"start", "stop", "shutdown", "reboot", "suspend", "resume"})
QEMU_ACTIONS = frozenset({"start", "stop", "shutdown", "reboot", "suspend",
                          "resume", "reset"})


# Strict allowlist, same discipline as notifier.kind_for: `token_id` is stored
# UNENCRYPTED (host_credentials.public_meta), returned by GET /hosts/{id} to any
# viewer, and written to audit_events.params — so it must be provably free of a
# credential, not merely "looks like a token id". Proxmox's own copy button
# yields `PVEAPIToken=user@realm!name=<uuid-secret>`; pasting that whole string
# into token_id used to pass the old shape check ("@" in user, non-empty name)
# and carried the secret into every one of those plaintext sinks. Banning "="
# and everything else outside this set makes that unrepresentable.
TOKEN_ID_RE = re.compile(r"^[A-Za-z0-9._+-]+@[A-Za-z0-9._-]+![A-Za-z0-9._-]+$")


def parse_token_id(token_id: str) -> tuple[str, str]:
    if not TOKEN_ID_RE.match(token_id):
        # Never echo the input: it is exactly the malformed case that may be a
        # pasted `PVEAPIToken=...=<secret>`, and this message reaches the caller
        # as an HTTP 502 detail (api/hosts.py -> main.py::problem_handler).
        raise ProxmoxError("token id must look like user@realm!tokenname "
                           "(letters, digits, dot, dash, underscore only)")
    user, _, name = token_id.partition("!")
    return user, name


def _header_safe(secret: str) -> bool:
    """A token secret must be encodable as an HTTP header value.

    urllib3 rejects anything else by raising InvalidHeader with the whole
    header value — i.e. `PVEAPIToken=user!name=<secret>` — inline in its
    message, which `_wrap` below would otherwise carry into a 502 body and a
    persisted `jobs.error`. A trailing newline from a copy-paste is enough to
    trigger it, so this is checked before the value ever reaches urllib3.
    """
    try:
        secret.encode("latin-1")
    except UnicodeEncodeError:
        return False
    return not any(c in secret for c in "\r\n\0") and secret == secret.strip()


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

    def _wrap(self, prefix: str, e: Exception) -> ProxmoxError:
        """The ONE place a proxmoxer/requests exception becomes our own.

        `str(e)` is third-party text we do not control, and urllib3 in
        particular interpolates the whole `Authorization` header value into
        `InvalidHeader`. Every wrapped message below flows outward — to a 502
        `detail` (api/hosts.py), to the unencrypted `jobs.error` column and its
        SSE stream (jobs/backend.py::_finish), and to `job_events.message` — so
        the credential is scrubbed here rather than at each of those sinks.
        """
        text = f"{prefix}: {e}"
        for needle in (self.token_secret, self.token_id):
            if not needle:
                continue
            # Both the raw value and the form a bytes/str repr() would render,
            # since urllib3 reports the header as `b'...'`.
            for form in (needle, repr(needle)[1:-1]):
                text = text.replace(form, "***")
        return ProxmoxError(text)

    def _connect(self):
        if self._api is not None:
            return self._api
        if not _header_safe(self.token_secret):
            raise ProxmoxError("token secret contains characters that cannot be "
                               "sent in an HTTP header (whitespace at either end, "
                               "a line break, or a non-Latin-1 character)")
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
            raise self._wrap(f"cannot connect to {self.address}", e) from e
        return self._api

    def version(self) -> dict:
        try:
            return self._connect().version.get()
        except ProxmoxError:
            raise
        except Exception as e:
            raise self._wrap("version check failed", e) from e

    def permissions(self) -> dict:
        try:
            return self._connect().access.permissions.get()
        except ProxmoxError:
            raise
        except Exception as e:
            raise self._wrap("permission read failed", e) from e

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
            raise self._wrap("cluster/resources failed", e) from e

    def node_rrddata(self, node: str, timeframe: str = "hour") -> list[dict]:
        """History-quality per-node series (netin/netout/cpu/mem), doc 02 §11.1."""
        try:
            return self._connect().nodes(node).rrddata.get(timeframe=timeframe)
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"rrddata failed for node {node!r}", e) from e

    # --- per-guest, user-triggered calls -----------------------------------
    # Doc 02 §3 forbids per-guest calls in the POLL LOOP; these are triggered by
    # a human clicking a button and are explicitly outside that budget.

    def guest_action(self, kind: str, node: str, vmid: int, action: str) -> str:
        """POST /nodes/{node}/{lxc|qemu}/{vmid}/status/{action} -> UPID."""
        allowed = LXC_ACTIONS if kind == "lxc" else QEMU_ACTIONS
        if action not in allowed:
            raise ProxmoxError(f"{action!r} is not a {kind} lifecycle action")
        try:
            status = getattr(self._connect().nodes(node), kind)(vmid).status
            return getattr(status, action).post()
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001 — one wrap point, like version()
            raise self._wrap(f"{kind}/{vmid} {action} failed on {node}", e) from e

    def task_status(self, node: str, upid: str) -> dict:
        """GET /nodes/{node}/tasks/{upid}/status — `stopped` + exitstatus == done."""
        try:
            return self._connect().nodes(node).tasks(upid).status.get()
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"task status failed for {upid}", e) from e

    def task_log(self, node: str, upid: str, start: int = 0,
                 limit: int = 500) -> list[dict]:
        """GET /nodes/{node}/tasks/{upid}/log — rows of {"n": seq, "t": line}."""
        try:
            return self._connect().nodes(node).tasks(upid).log.get(
                start=start, limit=limit)
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"task log failed for {upid}", e) from e
