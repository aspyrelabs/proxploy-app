"""The ONE Proxmox client layer (docs 02 §4, 11 §7). Every proxmoxer call and every
PVE-8-vs-9 behavioural branch lives here, never in routers, pollers, or jobs.
(No version branches exist yet; when PVE 9 diverges, branch on self.version()["release"]
inside this module only.) Scoped API tokens, never root@pam passwords (doc 00 §8)."""
import hashlib
import io
import ipaddress
import os
import re
import socket
import ssl
from urllib.parse import quote, urlparse

from proxploy.models import utcnow  # noqa: F401  (used by later phases' sync paths)
# The single source of truth for the privilege name (services/pveum.py's own
# docstring), so the message below and the script that grants it never drift.
from proxploy.services.pveum import NODE_POWER_PRIVILEGE


class ProxmoxError(RuntimeError):
    """A Proxmox interaction that failed, classified so a caller can tell a
    stranger what to actually do about it. `kind` is a stable machine string;
    the message stays human and is always secret-scrubbed by _wrap.
    """

    def __init__(self, message: str, kind: str = "unknown"):
        super().__init__(message)
        self.kind = kind


# Proxmox's own status verbs. Proxploy's user-facing vocabulary maps onto these
# in services/lifecycle.py: the gap is stated once, there.
LXC_ACTIONS = frozenset({"start", "stop", "shutdown", "reboot", "suspend", "resume"})
QEMU_ACTIONS = frozenset({"start", "stop", "shutdown", "reboot", "suspend",
                          "resume", "reset"})

# The NODE's own power verbs (POST /nodes/{node}/status?command=...), never to
# be confused with LXC_ACTIONS/QEMU_ACTIONS above: those act on a guest, these
# act on the physical (or virtual) machine underneath every guest on it.
# Proxmox's node-status endpoint only ever accepts these two.
NODE_POWER_COMMANDS = frozenset({"reboot", "shutdown"})


# The submitted token id is OPAQUE AND SECRET on ingest: Proxmox's own copy
# button yields `PVEAPIToken=user@realm!name=<uuid-secret>`, so any caller
# string may be carrying a credential. Nothing derived from it is stored in the
# clear except what this regex names: user, realm and token name, re-joined by
# token_public_meta() below. A previous fix banned "=": a denylist, and
# denylists in this codebase have failed twice already (notifier.kind_for).
#
# The user class is deliberately WIDE: LDAP/AD logins legitimately carry spaces
# and non-ASCII, and rejecting them broke real onboarding. What keeps the secret
# unrepresentable is structural, not a character blacklist: the three
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
        raise ProxmoxError("token id must look like user@realm!tokenname, the "
                           "realm and token name are letters, digits, dot, dash "
                           "and underscore, and none of the three parts may "
                           "contain '=' (if you pasted the whole "
                           "PVEAPIToken=... line, paste only the part before "
                           "the second '=', and put the secret in token_secret)")
    return f"{m['user']}@{m['realm']}", m["name"]


def token_public_meta(token_id: str) -> str:
    """The ONLY value allowed into the unencrypted `host_credentials.public_meta`.

    Built by pulling the known-safe fields forward, user, realm, token name; 
    and re-joining them; the caller's string never passes through, validated or
    not. Anything unparseable raises rather than falling back to a stripped or
    truncated form of the raw input.
    """
    user, name = parse_token_id(token_id)
    return f"{user}!{name}"


def _header_safe(secret: str) -> bool:
    """A token secret must be encodable as an HTTP header value.

    urllib3 rejects anything else by raising InvalidHeader with the whole
    header value, i.e. `PVEAPIToken=user!name=<secret>`, inline in its
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


# Onboarding hands us an operator-supplied address and we open a socket to it, 
# with CERT_NONE, on the fingerprint path: and the outcome (success, failure,
# latency, the returned fingerprint) comes back to the caller. That is an SSRF
# primitive unless the target class is constrained.
#
# RFC1918 and IPv6 unique-local are DELIBERATELY ALLOWED and always will be:
# this is a self-hosted LAN product and a node on 192.168.x.x / 10.x.x.x is the
# normal case, not the attack. Only classes that are never a Proxmox node and
# are dangerous to reach are refused: chiefly link-local, which is where cloud
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

    EVERY resolved address must pass, not just the first; a name with an A
    record for a real node and a second for 169.254.169.254 is refused outright.
    The returned literal is what the caller must connect to, so the socket goes
    to an address we actually checked.
    """
    if not host:
        raise ProxmoxError("address is missing a hostname")
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as e:
        raise ProxmoxError(f"cannot resolve {host!r}", kind="unreachable") from e
    chosen = None
    for info in infos:
        literal = info[4][0].partition("%")[0]  # drop any IPv6 zone id
        ip = ipaddress.ip_address(literal)
        ip = getattr(ip, "ipv4_mapped", None) or ip  # ::ffff:169.254.169.254
        for label, attr in _DENIED_CLASSES:
            if getattr(ip, attr) and not (attr == "is_loopback" and ALLOW_LOOPBACK_TARGET):
                raise ProxmoxError(
                    f"refusing to connect to {host!r}: it resolves to {ip}, "
                    f"which is {label}", kind="refused")
        chosen = chosen or literal
    return chosen


def open_validated_tcp_socket(host: str, port: int, timeout: float = 10.0) -> socket.socket:
    """resolve_target + connect to the literal we validated (doc 02 §5's SSRF
    guard, shared by the TLS-fingerprint check and the new console websocket
    connections, nothing here reaches Proxmox's own address string again)."""
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


class _NamedUpload(io.BufferedReader):
    """A file object whose `.name` is settable, for `ProxmoxClient.storage_upload`.

    `io.BufferedReader.name` normally proxies the underlying raw stream's name
    (the spooled temp path) and cannot be reassigned. Overriding the property
    here is the only way to hand proxmoxer/requests the ISO's real filename
    without renaming the spool file on disk.
    """

    def __init__(self, raw, name: str):
        super().__init__(raw)
        self._upload_name = name

    @property
    def name(self):
        return self._upload_name


def _classify(exc: BaseException) -> str:
    """Map an underlying transport/auth failure onto a kind the UI can act on.
    Substring matching is deliberate and lives HERE rather than in the
    frontend: proxmoxer and requests do not expose typed failures for these,
    and one fuzzy match in one place beats the same match spread across
    call sites in another language.

    Only reached from `_wrap`, i.e. for exceptions proxmoxer/requests raised
    that we did not construct ourselves. `resolve_target`'s SSRF refusals and
    `_connect`'s TLS-fingerprint mismatch are already `ProxmoxError`s raised
    with an explicit `kind` at the point they are known, self-classifying,
    so they never reach here and this function does not need to recognize
    them.

    A 403 ("permission") used to fall all the way through to "unknown",
    indistinguishable from a dead node or a broken cert; that is the literal
    bug the Sys.PowerMgmt gap surfaced as a bare 502 (see
    node-power-privilege-report.md). It is not special to node power: ANY
    call a token is too narrow for lands here the same way, so the fix is
    generic, not a second node_power-shaped special case.
    """
    text = str(exc).lower()
    if "fingerprint" in text:
        return "tls_fingerprint"
    if isinstance(exc, PermissionError) or "401" in text or "authentication" in text:
        return "auth"
    if "403" in text or "permission check failed" in text or "permission denied" in text:
        return "permission"
    if isinstance(exc, (ConnectionError, TimeoutError)) or "refused" in text \
            or "timed out" in text or "unreachable" in text or "resolve" in text:
        return "unreachable"
    return "unknown"


# Proxmox's own 403 text names exactly what it wanted: "Permission check
# failed (/nodes/node2, Sys.PowerMgmt)", sometimes with more than one
# privilege after the comma. This makes that fact machine-checkable so every
# call site gets the same honesty node_power's own fix pioneered, without
# each one re-deriving it by hand.
_PERMISSION_DETAIL_RE = re.compile(
    r"permission check failed\s*\(([^,]+),\s*([^)]+)\)", re.IGNORECASE)


def _permission_detail(text: str) -> str | None:
    """-> "Priv on /path", or None if `text` doesn't carry PVE's own
    "Permission check failed (/path, Priv)" shape (kind=="permission" can
    also be reached via a bare "403" with no such text, e.g. a differently
    worded proxy error; inventing a privilege name in that case would be
    worse than saying nothing)."""
    m = _PERMISSION_DETAIL_RE.search(text)
    if not m:
        return None
    return f"{m.group(2).strip()} on {m.group(1).strip()}"


def routable_addresses(raw) -> list[str]:
    """The addresses off one ProxmoxClient.lxc_interfaces() row that can
    actually be reached, in CIDR form ("192.168.50.179/24").

    Loopback and IPv6 link-local are dropped: every container has both on
    every interface and neither one opens a web UI. Same rule
    ProxmoxClient.agent_addresses applies to a VM's agent answer.

    Lives here beside lxc_interfaces rather than in api/network.py, where it
    started, because the poller wants the same rule and the poller must not
    import the API layer to get it.
    """
    out: list[str] = []
    for key in ("inet", "inet6"):
        value = str(raw.get(key) or "")
        if not value or value.startswith(("127.", "::1", "fe80:")):
            continue
        out.append(value)
    return out


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

    @property
    def pve_auth_header(self) -> str:
        """`Authorization` value for the two console websocket endpoints, the
        only PVE calls that do not go through proxmoxer (which sets this
        header itself on every REST request).

        PVE authenticates the vncwebsocket UPGRADE, not just the termproxy POST
        that precedes it. Without this header the upgrade is rejected
        `401 No ticket` on every real node, whatever the ticket says. Verified
        working for lxc on PVE 9.2.6 (2026-08-10), which also settles doc 11's
        open question about bugzilla #6079 for the LXC path.
        """
        return f"PVEAPIToken={self.token_id}={self.token_secret}"

    def _wrap(self, prefix: str, e: Exception, *, kind: str | None = None) -> ProxmoxError:
        """The ONE place a proxmoxer/requests exception becomes our own.

        `str(e)` is third-party text we do not control, and urllib3 in
        particular interpolates the whole `Authorization` header value into
        `InvalidHeader`. Every wrapped message below flows outward, to a 502
        `detail` (api/hosts.py), to the unencrypted `jobs.error` column and its
        SSE stream (jobs/backend.py::_finish), and to `job_events.message`; so
        the credential is scrubbed here rather than at each of those sinks.

        `kind` lets a caller that already knows more than `_classify` can
        guess from the raw text (e.g. node_power's own 403 detection below)
        say so directly, instead of `_classify` re-deriving a coarser answer.
        A caller-supplied `kind` also means the caller is handing back its
        own bespoke sentence already, so the generic permission-detail
        sentence below is skipped for it: node_power's message stays exactly
        what it is, the generic path exists for every OTHER call site that
        does not (yet) hand-write one.
        """
        text = f"{prefix}: {e}"
        for needle in (self.token_secret, self.token_id):
            if not needle:
                continue
            # Both the raw value and the form a bytes/str repr() would render,
            # since urllib3 reports the header as `b'...'`.
            for form in (needle, repr(needle)[1:-1]):
                text = text.replace(form, "***")
        resolved_kind = kind or _classify(e)
        if kind is None and resolved_kind == "permission":
            # Generalizes node_power's own fix to every call site: a 403 is
            # never again a bare, unlabelled 502 -- it says which privilege
            # PVE wanted, using PVE's own text as the source of truth rather
            # than a per-call-site guess.
            detail = _permission_detail(str(e))
            if detail:
                text += (f" -- the API token is missing {detail}. This will "
                         f"fail until it is granted; see "
                         f"docs.proxploy.com/getting-started/proxmox-token")
        return ProxmoxError(text, kind=resolved_kind)

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
                    f"TLS fingerprint mismatch: pinned {self.tls_fingerprint}, got {seen}",
                    kind="tls_fingerprint")
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

        The poll loop's only guest-state source, per-guest calls are
        forbidden in the poller (doc 02 §3 O(nodes) budget).
        """
        try:
            return self._connect().cluster.resources.get()
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001  (one wrap point, like version()
            raise self._wrap("cluster/resources failed", e) from e

    def node_rrddata(self, node: str, timeframe: str = "hour") -> list[dict]:
        """History-quality per-node series (netin/netout/cpu/mem), doc 02 §11.1."""
        try:
            return self._connect().nodes(node).rrddata.get(timeframe=timeframe)
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"rrddata failed for node {node!r}", e) from e

    def node_status(self, node: str) -> dict:
        """GET /nodes/{node}/status: the node's own view of itself.

        Carries cpuinfo (model, sockets, cores, cpus), loadavg, wait (the IO
        delay figure), kversion, boot-info and memory/swap/rootfs. Called when
        a human opens the host page, never from the poll loop: doc 02 §3 caps
        a cycle at O(nodes), and almost everything here is static between
        polls. The figures that are not (load, wait, memory) are already
        recorded as metric samples every cycle.
        """
        try:
            return self._connect().nodes(node).status.get()
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"node status failed for node {node!r}", e) from e

    def node_power(self, node: str, command: str) -> str:
        """POST /nodes/{node}/status?command=reboot|shutdown -> UPID.

        The host actions menu's Reboot/Power off. Deliberately separate from
        guest_action: this acts on the NODE, not a guest, so it is gated far
        harder by callers (doc 02 §9, doc 08 §1) -- it can take down every
        guest the node hosts, and if the node is the one Proxploy itself runs
        on, Proxploy along with it.

        A 403 here almost always means one specific thing: the token lacks
        Sys.PowerMgmt, which pveum.py never granted before this privilege
        existed (doc 08 §2/§9). A bare relay of Proxmox's "Permission check
        failed" left the operator to work that out alone; named explicitly
        instead, with where to grant it, while keeping Proxmox's own text too.
        """
        if command not in NODE_POWER_COMMANDS:
            raise ProxmoxError(f"{command!r} is not a node power command")
        try:
            return self._connect().nodes(node).status.post(command=command)
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001  (one wrap point, like version()
            prefix = f"node power ({command}) failed on {node}"
            if "403" in str(e):
                prefix += (f": the API token is missing {NODE_POWER_PRIVILEGE}. "
                          f"Node power will fail until it is granted; see "
                          f"docs.proxploy.com/getting-started/proxmox-token")
                raise self._wrap(prefix, e, kind="permission") from e
            raise self._wrap(prefix, e) from e

    def node_disks(self, node: str) -> list[dict]:
        """GET /nodes/{node}/disks/list: model, serial, size, health, wearout.

        The health and wearout columns are the reason this exists; neither is
        reachable from /cluster/resources, which only knows datastores.
        """
        try:
            return self._connect().nodes(node).disks.list.get()
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"disk list failed for node {node!r}", e) from e

    # --- the rest of the host page's hardware tab ---------------------------
    # All on demand, never from the poll loop (doc 02 §3 caps a cycle at
    # O(nodes)), and every one of them is refusable on its own: a token without
    # Sys.Audit answers some and rejects others, and a PVE without the path
    # 501s. Callers gather them independently so one refusal costs one section.

    def node_pci(self, node: str) -> list[dict]:
        """GET /nodes/{node}/hardware/pci -> the PCI inventory.

        Carries device_name/vendor_name (already resolved against the ids
        database, so no lookup table is needed here) and iommugroup, which is
        the field that decides whether a device can be passed to a guest.
        """
        try:
            return self._connect().nodes(node).hardware.pci.get()
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"pci list failed for node {node!r}", e) from e

    def node_services(self, node: str) -> list[dict]:
        """GET /nodes/{node}/services -> the pve-* and system units systemd
        reports, with `state`, `active-state` and `unit-state`."""
        try:
            return self._connect().nodes(node).services.get()
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"service list failed for node {node!r}", e) from e

    def node_subscription(self, node: str) -> dict:
        """GET /nodes/{node}/subscription -> {status, message, serverid, url}.

        `status: "notfound"` is the ordinary state of an unsubscribed install,
        not a failure, and this layer does not editorialise about it.
        """
        try:
            return self._connect().nodes(node).subscription.get()
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"subscription read failed for node {node!r}", e) from e

    def node_dns(self, node: str) -> dict:
        """GET /nodes/{node}/dns -> {dns1, dns2, dns3, search}. The numbered
        keys are ABSENT rather than null when unset."""
        try:
            return self._connect().nodes(node).dns.get()
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"dns read failed for node {node!r}", e) from e

    def node_time(self, node: str) -> dict:
        """GET /nodes/{node}/time -> {localtime, time, timezone}."""
        try:
            return self._connect().nodes(node).time.get()
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"time read failed for node {node!r}", e) from e

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
        except Exception as e:  # noqa: BLE001  (one wrap point, like version()
            raise self._wrap(f"{kind}/{vmid} {action} failed on {node}", e) from e

    def guest_config_update(self, kind: str, node: str, vmid: int,
                            config: dict) -> None:
        """PUT /nodes/{node}/{lxc|qemu}/{vmid}/config -> nothing.

        NOT long-running, and it never hands back a task id. PVE routes the
        PUT to `update_vm_api($param, 1)`, the synchronous half, whose schema
        declares `returns => { type => 'null' }`; only the POST on the same
        path is the asynchronous half that returns a UPID. Read off the
        node's own PVE/API2/Qemu.pm, pve-manager 9.2.11, 2026-08-20.

        This used to be documented as "UPID for a running qemu guest, None
        otherwise", and callers derived "did this land in the pending section"
        from it. That value is ALWAYS None, so every such caller reported
        "applied immediately" no matter what actually happened. Whether a
        change is waiting for a restart is a question only the guest's
        pending config can answer: call `guest_pending` after the write.

        `delete` is a real PVE parameter here, not a pseudo-key: pass
        `{"delete": "acpi,kvm"}` to REMOVE those settings, which is how a
        setting goes back to the Proxmox default. Writing the default value
        instead pins it, which is a different thing.
        """
        try:
            getattr(self._connect().nodes(node), kind)(vmid).config.put(**config)
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"config update failed for {kind}/{vmid} on {node}", e) from e

    def guest_pending(self, kind: str, node: str, vmid: int) -> dict:
        """GET /nodes/{node}/{lxc|qemu}/{vmid}/pending, reduced to the changes.

        PVE answers with one row per config key, `{key, value}`, where `value`
        is what the guest is running on right now. A row grows a `pending` key
        when a new value is waiting for the guest's next boot, and a `delete`
        key when the waiting change is a removal. Rows with neither are just
        the current config restated, so they are dropped here.

        -> {key: pending value}, with None where the pending change is a
        removal (the setting goes back to its Proxmox default at next boot).
        An empty dict therefore means "nothing is waiting", which is the
        answer for every stopped guest: PVE applies a write to a stopped guest
        straight away and has no pending section to file it under.

        Confirmed against both guest types on pve-manager 9.2.11, 2026-08-20;
        lxc has this endpoint too, so the NIC editor's qemu/lxc split does not
        need two code paths.
        """
        try:
            rows = getattr(self._connect().nodes(node), kind)(vmid).pending.get()
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"pending config read failed for {kind}/{vmid} "
                             f"on {node}", e) from e
        return {r["key"]: (None if r.get("delete") else r.get("pending"))
                for r in rows or [] if r.get("delete") or "pending" in r}

    # --- host network staging (Phase 6 Task 7) -------------------------------
    # PVE writes every one of the three staging calls below into
    # /etc/network/interfaces.new and touches NOTHING live. Only network_apply
    # promotes that file. network_revert deletes it.

    def network_create(self, node: str, config: dict) -> None:
        """POST /nodes/{node}/network, stages a new iface. `config` carries
        `iface` and `type` plus the PVE options (bridge_ports, cidr, ...)."""
        try:
            self._connect().nodes(node).network.post(**config)
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"staging network interface failed on {node}", e) from e

    def network_update(self, node: str, iface: str, config: dict) -> None:
        """PUT /nodes/{node}/network/{iface}, stages an edit."""
        try:
            self._connect().nodes(node).network(iface).put(**config)
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"staging {iface} failed on {node}", e) from e

    def network_delete(self, node: str, iface: str) -> None:
        """DELETE /nodes/{node}/network/{iface}, stages a removal."""
        try:
            self._connect().nodes(node).network(iface).delete()
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"staging removal of {iface} failed on {node}", e) from e

    def network_apply(self, node: str) -> str:
        """PUT /nodes/{node}/network -> UPID.

        This is the one that can cut a node off the network. `ifreload -a` runs
        on the node itself; if the new config is wrong the API connection this
        very call arrived on may be what dies, so the UPID may become
        unpollable. Callers confirm before reaching here.
        """
        try:
            return self._connect().nodes(node).network.put()
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"applying network config failed on {node}", e) from e

    def network_revert(self, node: str) -> None:
        """DELETE /nodes/{node}/network, discards /etc/network/interfaces.new."""
        try:
            self._connect().nodes(node).network.delete()
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"reverting staged network config failed on {node}", e) from e

    # ---- Firewall (spec: docs/superpowers/specs/2026-08-21-firewall-design.md)
    #
    # Four scopes share one rule schema, so they share one set of methods and
    # differ only in which proxmoxer node they hang off. `loc` is built by
    # services/firewall.py, which is also the only place that decides a caller
    # is allowed to name a given scope.
    #
    # Measured on pve-manager 9.2.11, 2026-08-21: aliases and ipset exist at
    # cluster and guest scope only, groups at cluster only, log at node and
    # guest only. This class does not enforce that; a caller asking a scope for
    # an object it does not have gets PVE's own 501, which says so.

    def _firewall_root(self, loc: dict):
        """The proxmoxer node under which this scope's firewall objects live."""
        api = self._connect()
        kind = loc.get("kind")
        if kind == "cluster":
            return api.cluster.firewall
        if kind == "group":
            return api.cluster.firewall.groups(self._segment(loc["group"]))
        if kind == "node":
            return api.nodes(loc["node"]).firewall
        if kind == "guest":
            return getattr(api.nodes(loc["node"]),
                           loc["guest_kind"])(loc["vmid"]).firewall
        raise ProxmoxError(f"unknown firewall scope {kind!r}")

    def _rules_node(self, loc: dict):
        """Where this scope's RULES live, which is not always `.rules`.

        A security group is itself a rule list: PVE documents
        GET /cluster/firewall/groups/{group} as "List rules" and POST to the
        same path as "Create new rule", with the identical rule schema. So the
        group node IS the rule collection, while every other scope hangs its
        rules off a `.rules` child. Getting this wrong is a 501 on every group
        rule call, not a wrong answer, so it is isolated here rather than
        repeated in each method below.
        """
        root = self._firewall_root(loc)
        return root if loc.get("kind") == "group" else root.rules

    @staticmethod
    def _fw_params(params: dict) -> dict:
        """Drop keys whose value is None so they are never sent at all.

        proxmoxer serialises whatever it is given, so `digest=None` reaches PVE
        as the literal string "None" and fails the digest comparison on every
        write. Absent means "no opinion"; None is not a value PVE has.
        """
        return {k: v for k, v in params.items() if v is not None}

    def firewall_rules(self, loc: dict) -> list[dict]:
        try:
            return self._rules_node(loc).get()
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap("firewall rule list failed", e) from e

    def firewall_rule(self, loc: dict, pos: int) -> dict:
        try:
            return self._rules_node(loc)(int(pos)).get()
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"firewall rule {pos} read failed", e) from e

    def firewall_rule_create(self, loc: dict, params: dict) -> None:
        """`params` is unpacked, never named as keywords: `icmp-type` carries a
        hyphen and cannot be a Python keyword argument at all."""
        try:
            self._rules_node(loc).post(**self._fw_params(params))
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap("firewall rule create failed", e) from e

    def firewall_rule_update(self, loc: dict, pos: int, params: dict) -> None:
        try:
            self._rules_node(loc)(int(pos)).put(**self._fw_params(params))
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"firewall rule {pos} update failed", e) from e

    def firewall_rule_move(self, loc: dict, pos: int, moveto: int,
                           digest: str | None = None) -> None:
        """Sends `moveto` alone, plus the digest. PVE's own schema says "Other
        arguments are ignored" for this call, so sending an edit alongside a
        move would look applied and not be."""
        try:
            self._rules_node(loc)(int(pos)).put(
                **self._fw_params({"moveto": int(moveto), "digest": digest}))
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"firewall rule {pos} move failed", e) from e

    def firewall_rule_delete(self, loc: dict, pos: int,
                             digest: str | None = None) -> None:
        try:
            self._rules_node(loc)(int(pos)).delete(
                **self._fw_params({"digest": digest}))
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"firewall rule {pos} delete failed", e) from e

    def firewall_options(self, loc: dict) -> dict:
        try:
            return self._firewall_root(loc).options.get()
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap("firewall options read failed", e) from e

    def firewall_options_update(self, loc: dict, params: dict) -> None:
        try:
            self._firewall_root(loc).options.put(**self._fw_params(params))
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap("firewall options update failed", e) from e

    def firewall_aliases(self, loc: dict) -> list[dict]:
        try:
            return self._firewall_root(loc).aliases.get()
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap("firewall alias list failed", e) from e

    def firewall_alias_create(self, loc: dict, params: dict) -> None:
        try:
            self._firewall_root(loc).aliases.post(**self._fw_params(params))
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap("firewall alias create failed", e) from e

    def firewall_alias_update(self, loc: dict, name: str, params: dict) -> None:
        try:
            self._firewall_root(loc).aliases(self._segment(name)).put(
                **self._fw_params(params))
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"firewall alias {name!r} update failed", e) from e

    def firewall_alias_delete(self, loc: dict, name: str,
                              digest: str | None = None) -> None:
        try:
            self._firewall_root(loc).aliases(self._segment(name)).delete(
                **self._fw_params({"digest": digest}))
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"firewall alias {name!r} delete failed", e) from e

    def firewall_ipsets(self, loc: dict) -> list[dict]:
        try:
            return self._firewall_root(loc).ipset.get()
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap("firewall IP set list failed", e) from e

    def firewall_ipset_create(self, loc: dict, params: dict) -> None:
        try:
            self._firewall_root(loc).ipset.post(**self._fw_params(params))
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap("firewall IP set create failed", e) from e

    def firewall_ipset_delete(self, loc: dict, name: str, force: bool = False,
                              digest: str | None = None) -> None:
        params = {"digest": digest}
        if force:
            params["force"] = 1          # PVE takes 1/0, not true/false
        try:
            self._firewall_root(loc).ipset(self._segment(name)).delete(
                **self._fw_params(params))
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"firewall IP set {name!r} delete failed", e) from e

    def firewall_ipset_members(self, loc: dict, name: str) -> list[dict]:
        try:
            return self._firewall_root(loc).ipset(self._segment(name)).get()
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"firewall IP set {name!r} read failed", e) from e

    def firewall_ipset_member_add(self, loc: dict, name: str, params: dict) -> None:
        try:
            self._firewall_root(loc).ipset(self._segment(name)).post(
                **self._fw_params(params))
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"firewall IP set {name!r} add failed", e) from e

    @staticmethod
    def _segment(value: str) -> str:
        """One URL PATH segment, escaped, because proxmoxer joins segments with
        posixpath.join and quotes none of them.

        Written for a member's CIDR: unescaped, `10.0.0.0/8` splits the path
        and PVE answers 404 on every member read, update and delete. `safe=""`
        because the default leaves `/` alone, which is the whole bug.

        Now also used for every alias, IP set and security group NAME, which
        had exactly the same shape of hole and no escaping at all. Note that
        quoting alone cannot save a name of `..` (a dot is unreserved, so it
        survives quoting and still means "the parent endpoint"), which is why
        api/firewall.py::ObjectName refuses one at the route as well. This is
        the second half of that: one mechanism, both places it is needed.
        """
        return quote(str(value), safe="")

    def firewall_ipset_member_update(self, loc: dict, name: str, cidr: str,
                                     params: dict) -> None:
        try:
            (self._firewall_root(loc).ipset(self._segment(name))(self._segment(cidr))
             .put(**self._fw_params(params)))
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"firewall IP set member {cidr!r} update failed", e) from e

    def firewall_ipset_member_delete(self, loc: dict, name: str, cidr: str,
                                     digest: str | None = None) -> None:
        try:
            (self._firewall_root(loc).ipset(self._segment(name))(self._segment(cidr))
             .delete(**self._fw_params({"digest": digest})))
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"firewall IP set member {cidr!r} delete failed", e) from e

    def firewall_groups(self) -> list[dict]:
        """Security groups are cluster-wide, so this takes no scope."""
        try:
            return self._connect().cluster.firewall.groups.get()
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap("firewall security group list failed", e) from e

    def firewall_group_create(self, params: dict) -> None:
        try:
            self._connect().cluster.firewall.groups.post(**self._fw_params(params))
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap("firewall security group create failed", e) from e

    def firewall_group_delete(self, group: str, digest: str | None = None) -> None:
        try:
            self._connect().cluster.firewall.groups(self._segment(group)).delete(
                **self._fw_params({"digest": digest}))
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"firewall security group {group!r} delete failed",
                             e) from e

    def firewall_refs(self, loc: dict, ref_type: str | None = None) -> list[dict]:
        """Alias and IP set names this scope may reference in source and dest."""
        try:
            return self._firewall_root(loc).refs.get(
                **self._fw_params({"type": ref_type}))
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap("firewall reference list failed", e) from e

    def firewall_macros(self) -> list[dict]:
        """Read only, cluster wide. PVE gives a name and a description; it does
        NOT say which ports a macro expands to, so nothing downstream can."""
        try:
            return self._connect().cluster.firewall.macros.get()
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap("firewall macro list failed", e) from e

    def firewall_log(self, loc: dict, start: int = 0, limit: int = 500,
                     since: int | None = None,
                     until: int | None = None) -> list[dict]:
        """Line cursor plus optional epoch bounds, returning {n, t} rows: the
        same shape task_log reads, so JobLog can render it unchanged."""
        try:
            return self._firewall_root(loc).log.get(**self._fw_params(
                {"start": int(start), "limit": int(limit),
                 "since": since, "until": until}))
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap("firewall log read failed", e) from e

    def task_status(self, node: str, upid: str) -> dict:
        """GET /nodes/{node}/tasks/{upid}/status, `stopped` + exitstatus == done."""
        try:
            return self._connect().nodes(node).tasks(upid).status.get()
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"task status failed for {upid}", e) from e

    def node_tasks(self, node: str, limit: int = 50) -> list[dict]:
        """GET /nodes/{node}/tasks, newest first.

        Every other task call here is scoped to a UPID Proxploy already knows
        because it started the task. This one lists what the NODE has been
        doing, including work started from the Proxmox UI or a cron job, which
        is the point: an operator debugging "why did my container restart"
        needs the tasks Proxploy did not cause.
        """
        try:
            return self._connect().nodes(node).tasks.get(limit=limit)
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"task list failed for node {node}", e) from e

    def task_log(self, node: str, upid: str, start: int = 0,
                 limit: int = 500) -> list[dict]:
        """GET /nodes/{node}/tasks/{upid}/log, rows of {"n": seq, "t": line}."""
        try:
            return self._connect().nodes(node).tasks(upid).log.get(
                start=start, limit=limit)
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"task log failed for {upid}", e) from e

    # --- backups (Phase 6 Task 9) --------------------------------------------

    def vzdump(self, node: str, params: dict) -> str:
        """POST /nodes/{node}/vzdump -> UPID. `params` carries `vmid` (a comma
        string) or `all=1`, plus storage/mode/compress."""
        try:
            return self._connect().nodes(node).vzdump.post(**params)
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"vzdump failed on {node}", e) from e

    def restore_guest(self, kind: str, node: str, vmid: int, params: dict) -> str:
        """Restore is a create-with-archive, not its own endpoint.

        A CT restore POSTs /nodes/{node}/lxc with `ostemplate=<volid>` +
        `restore=1`; a VM restore POSTs /nodes/{node}/qemu with
        `archive=<volid>`. `vmid` is the TARGET id: the guest's own for an
        in-place restore (which also needs `force=1` and a stopped guest), a
        fresh `cluster_nextid()` for a restore-as-new. Building that decision
        is the caller's; this method only posts it.
        """
        if kind not in ("lxc", "qemu"):
            raise ProxmoxError(f"{kind!r} is not a restorable guest kind")
        try:
            return getattr(self._connect().nodes(node), kind).post(vmid=int(vmid),
                                                                    **params)
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"restore of {kind}/{vmid} failed on {node}", e) from e

    def prune_preview(self, node: str, storage: str, params: dict) -> list[dict]:
        """GET /nodes/{node}/storage/{storage}/prunebackups, a DRY RUN.

        Marks each volume keep|remove|protected and deletes nothing. The real
        deletion is the DELETE verb in prune_backups() below; the two must stay
        separate methods so no caller can reach the destructive one by accident.
        `params` is a dict because `prune-backups` is hyphenated and cannot be a
        Python kwarg.
        """
        try:
            return self._connect().nodes(node).storage(storage).prunebackups.get(**params)
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"prune preview failed for {storage} on {node}", e) from e

    def prune_backups(self, node: str, storage: str, params: dict) -> str:
        """DELETE /nodes/{node}/storage/{storage}/prunebackups -> UPID. This one
        really deletes; run prune_preview() with the same `params` first."""
        try:
            return self._connect().nodes(node).storage(storage).prunebackups.delete(**params)
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"prune failed for {storage} on {node}", e) from e

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
        """POST /nodes/{node}/qemu/{vmid}/vncproxy (websocket=1, generate-password=1)
        -> {user, ticket, port, cert, upid, password}.

        `generate-password=1` is not optional decoration. QEMU's VNC server
        offers exactly one RFB security type on this cluster, type 2 (VNC
        Authentication), so an RFB client that presents no password cannot
        finish the handshake at all. Decoded off a live PVE 9.2.10 node:

            greeting            b"RFB 003.008\\n"
            security types      b"\\x01\\x02"   (count 1, type 2)

        Unlike the termproxy path, nothing in the bridge can supply that
        password on the browser's behalf: services/consoleproxy.py is a byte
        relay by design and the RFB challenge/response is end to end between
        QEMU and the browser. So the password has to reach the browser, and
        this parameter is what decides HOW MUCH reaches it.

        Without it, PVE's answer carries the vncticket only, and the VNC
        password is that ticket (RFB truncates a password to 8 bytes, and
        PVE builds the ticket so its first 8 bytes are the password). Handing
        the browser the whole ticket would hand it the credential that
        authenticates the /vncwebsocket upgrade to PVE directly, which is a
        real widening: the browser could then talk to Proxmox without going
        through Proxploy at all.

        With it, PVE returns a separate 8 character `password` field, and the
        rest of the ticket stays server side. The browser gets a secret that
        is only good for answering one VNC challenge on one already-bridged
        socket. Same thing Proxmox's own UI ends up holding, minus the part
        that talks to the API.
        """
        try:
            return self._connect().nodes(node).qemu(vmid).vncproxy.post(
                websocket=1, **{"generate-password": 1})
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"vncproxy failed for qemu/{vmid} on {node}", e) from e

    # --- infra reads (Phase 6) ----------------------------------------------
    # All read-only, all on-demand: nothing here is called from the poll loop,
    # so doc 02 §3's O(nodes) budget is untouched.

    def storages(self, node: str) -> list[dict]:
        """GET /nodes/{node}/storage -> [{storage, type, content, active,
        enabled, shared, used, avail, total}]."""
        try:
            return self._connect().nodes(node).storage.get()
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"storage list failed on {node}", e) from e

    def storage_status(self, node: str, storage: str) -> dict:
        """GET /nodes/{node}/storage/{storage}/status -> per-datastore detail."""
        try:
            return self._connect().nodes(node).storage(storage).status.get()
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"storage status failed for {storage!r} on {node}", e) from e

    def storage_content(self, node: str, storage: str,
                        content: str | None = None) -> list[dict]:
        """GET /nodes/{node}/storage/{storage}/content -> volume listing.

        `content=` is a FILTER, so it is omitted rather than sent as None; 
        PVE would otherwise filter on the literal string and return nothing.
        """
        try:
            leaf = self._connect().nodes(node).storage(storage).content
            return leaf.get(content=content) if content else leaf.get()
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"storage content failed for {storage!r} on {node}", e) from e

    def cluster_storage(self) -> list[dict]:
        """GET /storage, the cluster-level storage.cfg, not a node's view."""
        try:
            return self._connect().storage.get()
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap("cluster storage config read failed", e) from e

    def agent_addresses(self, node: str, vmid: int) -> list[str] | None:
        """The addresses a VM's guest agent says it actually has, or None.

        None means "cannot tell", and the two reasons are not worth telling
        apart to a caller: the agent is not installed, or it is installed and not
        running. Either way Proxploy has no truthful answer, and None is what the
        UI renders as unknown rather than as "no address".

        This is the only honest read of a VM's address. PVE keeps a container's
        address on its netN string, so that one is a config read, but a VM's
        address lives inside the guest: `ipconfigN` is a cloud-init datasource,
        which a Windows guest ignores entirely unless Cloudbase-Init is installed
        (see api/network.py::ADDRESS_KEYS). Asking the guest is the difference
        between reporting what is and reporting what was requested.

        Loopback is dropped: every guest has 127.0.0.1 and it answers nothing.
        """
        try:
            raw = (self._connect().nodes(node).qemu(vmid)
                   .agent("network-get-interfaces").get())
        except Exception:  # noqa: BLE001  (no agent is the common case, not an error)
            return None
        out: list[str] = []
        for iface in (raw or {}).get("result", raw) or []:
            if not isinstance(iface, dict):
                continue
            for addr in iface.get("ip-addresses") or []:
                value = str(addr.get("ip-address") or "")
                if value and not value.startswith(("127.", "::1")):
                    out.append(value)
        return out

    # Filesystem types qemu-ga reports that are not the guest's storage.
    # get-fsinfo enumerates whatever is mounted with a block device behind it,
    # and on a modern Linux guest that includes every snap package as its own
    # read-only squashfs loop mount. Those report used == total, so counting
    # them adds a gigabyte or two of nothing to a figure an operator reads as
    # "how full is this VM".
    AGENT_FS_SKIP = {"squashfs", "iso9660", "tmpfs", "devtmpfs", "ramfs",
                     "overlay", "efivarfs", "autofs"}

    def agent_fsinfo(self, node: str, vmid: int) -> tuple[bool | None, int | None]:
        """One get-fsinfo call, two facts: (agent answered?, bytes used).

        Was agent_disk_used() and returned the bytes alone. It is widened
        rather than paired with a sibling call because the two facts come out
        of the SAME request and always agreed anyway: whether a guest agent is
        installed and answering is exactly what "we could not read the
        filesystems" already knew and threw away. A second endpoint (ping, or
        the config's `agent:` line) would be a second per-VM call every cycle
        for an answer we are holding in our hand. Per-cycle cost is therefore
        unchanged: still one call, still on the caller's cadence.

        Why the bytes are needed at all: the hypervisor can only see a block
        device, not the filesystem inside it. /cluster/resources' `disk` field
        is meaningful for a container and is routinely a flat 0 for a QEMU
        guest (measured on the lab cluster, PVE 9.2.10, 2026-08-20: VM 108
        running, 32 GiB allocated, `disk: 0`). Only the guest can answer.

        The first element is deliberately THREE-valued, and keeping the three
        apart is the whole point of returning it:

          * True: the agent answered. Whatever came back is a real answer,
            even if nothing in it was usable.
          * False: Proxmox told us this guest has no working agent. The lab VM
            answers `500 Internal Server Error: No QEMU guest agent
            configured`, and a guest whose config declares an agent that is
            not running inside it answers `QEMU guest agent is not running`.
            Both are Proxmox reporting on the agent, which is a real finding
            an operator can act on, not a fault of ours.
          * None: we could not ask. Any other failure (the node refused the
            connection, the token lost its permission, a timeout) says nothing
            about the guest, and reporting "no agent" off the back of a
            network error would be a lie that sticks.

        The split is made on the error text because that is the only thing PVE
        gives us: every one of these arrives as a 500 with a message, so the
        status code cannot separate them. Matching on "guest agent" is loose
        on purpose, since it catches both of PVE's wordings above and anything
        else it says specifically about the agent, and a message that never
        mentions the agent is by definition not PVE answering about it.

        Summing: one entry per mounted filesystem, deduped on the guest's own
        device name (`name`, e.g. "sda1"), because a bind mount and every
        subvolume of one btrfs pool report the SAME filesystem more than once
        and adding those up counts the same bytes twice. Falls back to the
        mountpoint when an agent omits the name, which at worst double-counts
        the case the dedupe was meant to catch and never invents storage that
        is not there. An entry with no `used-bytes` is skipped rather than
        counted as zero (some filesystems make qemu-ga omit it).

        An agent that answers with nothing usable returns (True, None), not
        (True, 0): a VM whose every filesystem was skipped has not been
        measured, and 0 would draw an empty disk bar under a full one. That
        pair is also the case the old single return could not express, since
        it collapsed "no agent" and "no usable answer" into the same None.
        """
        try:
            raw = (self._connect().nodes(node).qemu(vmid)
                   .agent("get-fsinfo").get())
        except Exception as e:  # noqa: BLE001  (no agent is the common case, not an error)
            return (False if "guest agent" in str(e).lower() else None), None
        by_device: dict[str, int] = {}
        for fs in (raw or {}).get("result", raw) or []:
            if not isinstance(fs, dict):
                continue
            if str(fs.get("type") or "").lower() in self.AGENT_FS_SKIP:
                continue
            used = fs.get("used-bytes")
            if used is None:
                continue
            key = str(fs.get("name") or fs.get("mountpoint") or "")
            if not key:
                continue
            by_device[key] = int(used)
        return True, (sum(by_device.values()) if by_device else None)

    def lxc_interfaces(self, node: str, vmid: int) -> list[dict] | None:
        """What a RUNNING container's interfaces actually are, or None.

        The counterpart to agent_addresses() for VMs, and the answer to the
        same question: a config read reports what was REQUESTED, and for a
        container on DHCP that is the literal word `dhcp`. PVE does know the
        lease, and this is where it keeps it. No guest agent involved: the
        container shares the host kernel, so the node can read its namespace
        directly. Measured on PVE 9.2.10, 2026-08-20: a CT whose config says
        `ip=dhcp` answers here with `eth0 ... inet 192.168.50.179/24`, and the
        hwaddr matches the config's own.

        None means cannot tell, which is the ordinary case for a STOPPED
        container: there are no interfaces to report and PVE errors rather
        than answering empty. Swallowed for the same reason agent_addresses
        swallows its own: not being able to ask is not an outage.
        """
        try:
            return self._connect().nodes(node).lxc(vmid).interfaces.get() or []
        except Exception:  # noqa: BLE001  (a stopped CT is not an error)
            return None

    def node_networks(self, node: str, iface_type: str | None = None) -> list[dict]:
        """GET /nodes/{node}/network -> [{iface, type, method, cidr, gateway,
        bridge_ports, active, autostart, ...}]. `iface_type` is PVE's `type`
        filter (bridge/bond/eth/vlan), omitted when None for the same reason
        storage_content omits `content`."""
        try:
            net = self._connect().nodes(node).network
            return net.get(type=iface_type) if iface_type else net.get()
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"network list failed on {node}", e) from e

    def guest_config(self, kind: str, node: str, vmid: int) -> dict:
        """GET /nodes/{node}/{lxc|qemu}/{vmid}/config, the full config dict,
        including every netN= line the network page round-trips."""
        try:
            return getattr(self._connect().nodes(node), kind)(vmid).config.get()
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"config read failed for {kind}/{vmid} on {node}", e) from e

    def snapshots(self, kind: str, node: str, vmid: int) -> list[dict]:
        """GET /nodes/{node}/{lxc|qemu}/{vmid}/snapshot -> [{name, description,
        snaptime, vmstate, parent}]. Includes PVE's synthetic `current` row, 
        callers decide whether to show it, this layer does not filter."""
        try:
            return getattr(self._connect().nodes(node), kind)(vmid).snapshot.get()
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"snapshot list failed for {kind}/{vmid} on {node}", e) from e

    # --- snapshots (Phase 6, Task 10) ---------------------------------------

    def snapshot_create(self, kind: str, node: str, vmid: int, name: str,
                        description: str | None = None,
                        vmstate: bool = False) -> str:
        """POST /nodes/{node}/{kind}/{vmid}/snapshot -> UPID.

        `vmstate` is doc 01 §4's "with-RAM option": PVE dumps the guest's memory
        into the snapshot so a rollback resumes mid-execution. It exists only on
        the qemu endpoint, PVE's lxc snapshot API has no such parameter, so a
        container request for it is refused here rather than silently dropped,
        which would produce a snapshot the caller believes has RAM in it.
        """
        if vmstate and kind != "qemu":
            raise ProxmoxError("vmstate (snapshot with RAM) is a VM-only feature; "
                               f"{kind} snapshots cannot include memory")
        call: dict = {"snapname": name}
        if description:
            call["description"] = description
        if vmstate:
            call["vmstate"] = 1
        try:
            guest = getattr(self._connect().nodes(node), kind)(vmid)
            return guest.snapshot.post(**call)
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001  (one wrap point, like version()
            raise self._wrap(f"snapshot {name!r} of {kind}/{vmid} failed on {node}",
                             e) from e

    def snapshot_rollback(self, kind: str, node: str, vmid: int, name: str) -> str:
        """POST /nodes/{node}/{kind}/{vmid}/snapshot/{name}/rollback -> UPID.

        Destructive: everything written since the snapshot is discarded. The
        typed-name confirmation lives in the route (api/vms.py), not here.
        """
        try:
            guest = getattr(self._connect().nodes(node), kind)(vmid)
            return guest.snapshot(name).rollback.post()
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"rollback of {kind}/{vmid} to {name!r} failed on "
                             f"{node}", e) from e

    def snapshot_delete(self, kind: str, node: str, vmid: int, name: str) -> str:
        """DELETE /nodes/{node}/{kind}/{vmid}/snapshot/{name} -> UPID."""
        try:
            guest = getattr(self._connect().nodes(node), kind)(vmid)
            return guest.snapshot(name).delete()
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"deleting snapshot {name!r} of {kind}/{vmid} failed "
                             f"on {node}", e) from e

    def cluster_nextid(self) -> int:
        """GET /cluster/nextid, PVE answers with a JSON string; cast once here
        so no caller has to remember to."""
        try:
            return int(self._connect().cluster.nextid.get())
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap("cluster nextid read failed", e) from e

    # --- migration (Phase 8 Task 14/15) --------------------------------------

    def cluster_status(self) -> list[dict]:
        """GET /cluster/status, cluster membership + node list.

        A standalone node returns rows with no `{"type": "cluster"}` entry.
        This is the ONLY honest source of cluster membership: `hosts.cluster_name`
        is never written anywhere else in the codebase (doc 11 §2 / Task 14),
        so migration preflight calls this live on both hosts rather than
        trusting that column.
        """
        try:
            return self._connect().cluster.status.get()
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap("cluster status read failed", e) from e

    def cluster_join_info(self) -> dict:
        """GET /cluster/config/join -> {nodelist: [{name, ring0_addr, pve_addr,
        pve_fp, ...}], totem: {...}}.

        `ring0_addr` is corosync's address and `pve_addr` is the one PVE
        designates for its API. They are separate fields and can differ, which
        is exactly why peer discovery prefers `pve_addr`: `/cluster/status`
        reports only the corosync-side address, so on a cluster with a
        dedicated corosync link it would offer peers at an address the API does
        not answer on (doc 12 check 13).

        Readable by a PVEAuditor-class token, verified on PVE 9.2.10, so the
        monitoring credential peer discovery already runs on is enough.
        """
        try:
            return self._connect().cluster.config.join.get()
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap("cluster join info read failed", e) from e

    def migrate_guest(self, kind: str, node: str, vmid: int, params: dict) -> str:
        """POST /nodes/{node}/{lxc|qemu}/{vmid}/migrate -> UPID.

        Only meaningful when source and target share a PVE cluster (the
        `cluster` strategy in services/migrate.py), `params` carries `target`
        (the destination node name) plus optional migrate options.
        """
        if kind not in ("lxc", "qemu"):
            raise ProxmoxError(f"{kind!r} is not a migratable guest kind")
        try:
            return getattr(self._connect().nodes(node), kind)(vmid).migrate.post(**params)
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"migrate of {kind}/{vmid} failed on {node}", e) from e

    # --- guest create / clone / destroy (Phase 6) ---------------------------

    def vm_create(self, node: str, params: dict) -> str:
        """POST /nodes/{node}/qemu -> UPID.

        The same endpoint restore_guest() posts an `archive` to; here it carries
        a full spec (vmid, name, cores, memory, scsi0, net0, …). Building that
        spec is the caller's job, this method only posts it, so every PVE
        parameter name lives in exactly one place (services/guestjobs.py).
        """
        try:
            return self._connect().nodes(node).qemu.post(**params)
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001  (one wrap point, like version()
            raise self._wrap(f"vm create failed on {node}", e) from e

    def vm_clone(self, node: str, vmid: int, params: dict) -> str:
        """POST /nodes/{node}/qemu/{vmid}/clone -> UPID.

        `params` carries newid/name/full/target/storage. `full=0` (a linked
        clone) is only legal when the source is a template; PVE enforces that
        and its refusal is what the caller reports.
        """
        try:
            return self._connect().nodes(node).qemu(vmid).clone.post(**params)
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"clone of qemu/{vmid} failed on {node}", e) from e

    def guest_delete(self, kind: str, node: str, vmid: int) -> str:
        """DELETE /nodes/{node}/{lxc|qemu}/{vmid} -> UPID. Destroys the guest
        and its disks; PVE refuses while it is running."""
        if kind not in ("lxc", "qemu"):
            raise ProxmoxError(f"{kind!r} is not a destroyable guest kind")
        try:
            return getattr(self._connect().nodes(node), kind)(vmid).delete()
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"destroying {kind}/{vmid} failed on {node}", e) from e

    # --- storage content mutations (Phase 6) --------------------------------

    def storage_upload(self, node: str, storage: str, content: str,
                       filename: str, path: str) -> str:
        """POST /nodes/{node}/storage/{storage}/upload -> UPID.

        `path` is a spooled temp file on the Proxploy host, opened here and
        streamed by proxmoxer as the multipart part, the bytes are never held
        in memory by us (see api/storage.py's upload route for the other half).

        proxmoxer/requests derive the multipart part's filename from the file
        object's `.name` (`requests.utils.guess_filename`), but a plain
        `open()` result exposes `.name` read-only as the spool path's own
        basename, assigning to it raises `AttributeError`. `_NamedUpload`
        wraps the raw stream so `.name` reports the ISO's real filename
        instead, while still passing `isinstance(_, io.IOBase)` so proxmoxer's
        streaming-multipart path (large-file handling) still kicks in.
        """
        try:
            with open(path, "rb", buffering=0) as raw, _NamedUpload(raw, filename) as fh:
                return self._connect().nodes(node).storage(storage).upload.post(
                    content=content, filename=fh)
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"upload of {filename!r} to {storage} on {node} failed",
                             e) from e

    def storage_delete_volume(self, node: str, storage: str, volid: str) -> str | None:
        """DELETE /nodes/{node}/storage/{storage}/content/{volid}.

        Returns a UPID for the plugins that delete asynchronously (PBS, ZFS) and
        None for the ones that do it inline (dir), the caller must handle both.
        """
        try:
            return self._connect().nodes(node).storage(storage).content(volid).delete()
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"deleting {volid!r} from {storage} on {node} failed",
                             e) from e

    # --- storage definition management (Phase 6) ----------------------------
    # These three hit the CLUSTER-level /storage endpoints, not /nodes/{n}/…:
    # a storage definition lives in /etc/pve/storage.cfg and is cluster-wide.
    # They are SYNCHRONOUS: Proxmox returns no UPID, so there is nothing to
    # poll and these are plain route calls rather than jobs.
    #
    # `config` may carry a live credential (PBS `password`, CIFS `username`/
    # `password`). It is forwarded and forgotten: nothing here logs, stores or
    # returns it, and _wrap below scrubs only OUR token: the caller's secret
    # never enters an exception message because it is a request body, not a
    # header, and proxmoxer does not echo request bodies in its errors.

    def storage_create(self, config: dict) -> None:
        """POST /storage, `config` must include `storage` and `type`."""
        try:
            self._connect().storage.post(**config)
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"attaching storage {config.get('storage')!r} failed",
                             e) from e

    def storage_update(self, storage: str, config: dict) -> None:
        """PUT /storage/{storage}, only the keys given are changed."""
        try:
            self._connect().storage(storage).put(**config)
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"updating storage {storage!r} failed", e) from e

    def storage_remove(self, storage: str) -> None:
        """DELETE /storage/{storage}, drops the definition; upstream data stays."""
        try:
            self._connect().storage(storage).delete()
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"detaching storage {storage!r} failed", e) from e
