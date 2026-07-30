"""The ONE Proxmox client layer (docs 02 §4, 11 §7). Every proxmoxer call and every
PVE-8-vs-9 behavioural branch lives here — never in routers, pollers, or jobs.
(No version branches exist yet; when PVE 9 diverges, branch on self.version()["release"]
inside this module only.) Scoped API tokens, never root@pam passwords (doc 00 §8)."""
import hashlib
import ipaddress
import os
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


# The submitted token id is OPAQUE AND SECRET on ingest — Proxmox's own copy
# button yields `PVEAPIToken=user@realm!name=<uuid-secret>`, so any caller
# string may be carrying a credential. Nothing derived from it is stored in the
# clear except what this regex names: user, realm and token name, re-joined by
# token_public_meta() below. A previous fix banned "=" — a denylist, and
# denylists in this codebase have failed twice already (notifier.kind_for).
#
# The user class is deliberately WIDE: LDAP/AD logins legitimately carry spaces
# and non-ASCII, and rejecting them broke real onboarding. What keeps the secret
# unrepresentable is structural, not a character blacklist — the three
# separators "=", "@" and "!" cannot appear inside any component, so a string
# rebuilt as `user@realm!name` can never carry the `=<secret>` half no matter
# how wide the user class gets. Control characters (\x00-\x1f, \x7f) stay out
# because they are header-injection shaped, not because they hide a secret.
_COMPONENT = r"[^=@!\x00-\x1f\x7f]+"
TOKEN_ID_RE = re.compile(rf"^(?P<user>{_COMPONENT})@(?P<realm>[A-Za-z0-9._-]+)"
                         rf"!(?P<name>[A-Za-z0-9._-]+)$")


def parse_token_id(token_id: str) -> tuple[str, str]:
    """-> ("user@realm", "tokenname"), both rebuilt from the parsed components."""
    m = TOKEN_ID_RE.match(token_id)
    if not m:
        # Never echo the input: it is exactly the malformed case that may be a
        # pasted `PVEAPIToken=...=<secret>`, and this message reaches the caller
        # as an HTTP 422/502 detail (api/hosts.py -> main.py::problem_handler).
        raise ProxmoxError("token id must look like user@realm!tokenname — the "
                           "realm and token name are letters, digits, dot, dash "
                           "and underscore, and none of the three parts may "
                           "contain '=' (if you pasted the whole "
                           "PVEAPIToken=... line, paste only the part before "
                           "the second '=', and put the secret in token_secret)")
    return f"{m['user']}@{m['realm']}", m["name"]


def token_public_meta(token_id: str) -> str:
    """The ONLY value allowed into the unencrypted `host_credentials.public_meta`.

    Built by pulling the known-safe fields forward — user, realm, token name —
    and re-joining them; the caller's string never passes through, validated or
    not. Anything unparseable raises rather than falling back to a stripped or
    truncated form of the raw input.
    """
    user, name = parse_token_id(token_id)
    return f"{user}!{name}"


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


# Onboarding hands us an operator-supplied address and we open a socket to it —
# with CERT_NONE, on the fingerprint path — and the outcome (success, failure,
# latency, the returned fingerprint) comes back to the caller. That is an SSRF
# primitive unless the target class is constrained.
#
# RFC1918 and IPv6 unique-local are DELIBERATELY ALLOWED and always will be:
# this is a self-hosted LAN product and a node on 192.168.x.x / 10.x.x.x is the
# normal case, not the attack. Only classes that are never a Proxmox node and
# are dangerous to reach are refused — chiefly link-local, which is where cloud
# instance metadata lives (169.254.169.254).
#
# Loopback is refused by default but is a legitimate target when Proxploy runs
# on the PVE node itself, so it has an opt-in escape hatch. Read at import so a
# test can flip the module attribute; an operator sets the env var.
ALLOW_LOOPBACK_TARGET = os.environ.get("PROXPLOY_ALLOW_LOOPBACK_TARGET") == "1"

_DENIED_CLASSES = (
    ("a link-local address", "is_link_local"),  # 169.254.169.254 lives here
    ("a loopback address", "is_loopback"),
    ("the unspecified address", "is_unspecified"),
    ("a multicast address", "is_multicast"),
    ("a reserved address", "is_reserved"),
)


def resolve_target(host: str, port: int) -> str:
    """Resolve `host`, refuse the dangerous address classes, return one literal IP.

    EVERY resolved address must pass, not just the first — a name with an A
    record for a real node and a second for 169.254.169.254 is refused outright.
    The returned literal is what the caller must connect to, so the socket goes
    to an address we actually checked.
    """
    if not host:
        raise ProxmoxError("address is missing a hostname")
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as e:
        raise ProxmoxError(f"cannot resolve {host!r}") from e
    chosen = None
    for info in infos:
        literal = info[4][0].partition("%")[0]  # drop any IPv6 zone id
        ip = ipaddress.ip_address(literal)
        ip = getattr(ip, "ipv4_mapped", None) or ip  # ::ffff:169.254.169.254
        for label, attr in _DENIED_CLASSES:
            if getattr(ip, attr) and not (attr == "is_loopback" and ALLOW_LOOPBACK_TARGET):
                raise ProxmoxError(
                    f"refusing to connect to {host!r}: it resolves to {ip}, "
                    f"which is {label}")
        chosen = chosen or literal
    return chosen


def open_validated_tcp_socket(host: str, port: int, timeout: float = 10.0) -> socket.socket:
    """resolve_target + connect to the literal we validated (doc 02 §5's SSRF
    guard, shared by the TLS-fingerprint check and the new console websocket
    connections — nothing here reaches Proxmox's own address string again)."""
    ip = resolve_target(host, port)
    return socket.create_connection((ip, port), timeout=timeout)


def tls_fingerprint_sha256(host: str, port: int = 8006) -> str:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE  # we are fetching the cert to pin it, not trusting it
    with open_validated_tcp_socket(host, port) as sock:
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
        # Gate every outbound path, not just the CERT_NONE one below: proxmoxer
        # opens its own connection and would otherwise reach 169.254.169.254 all
        # the same, with the outcome still visible to the caller.
        resolve_target(host, port)
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

    # --- console/terminal calls (Phase 5) -----------------------------------

    def termproxy(self, kind: str, node: str, vmid: int) -> dict:
        """POST /nodes/{node}/{lxc|qemu}/{vmid}/termproxy -> {user, ticket, port, upid}."""
        try:
            return getattr(self._connect().nodes(node), kind)(vmid).termproxy.post()
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"termproxy failed for {kind}/{vmid} on {node}", e) from e

    def node_termproxy(self, node: str) -> dict:
        """POST /nodes/{node}/termproxy -> {user, ticket, port, upid} (node shell)."""
        try:
            return self._connect().nodes(node).termproxy.post()
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"node termproxy failed on {node}", e) from e

    def vncproxy(self, node: str, vmid: int) -> dict:
        """POST /nodes/{node}/qemu/{vmid}/vncproxy (websocket=1) -> {user, ticket, port, cert, upid}."""
        try:
            return self._connect().nodes(node).qemu(vmid).vncproxy.post(websocket=1)
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"vncproxy failed for qemu/{vmid} on {node}", e) from e
