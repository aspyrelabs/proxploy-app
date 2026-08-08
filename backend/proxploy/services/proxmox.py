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
from urllib.parse import urlparse

from proxploy.models import utcnow  # noqa: F401  (used by later phases' sync paths)


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
    """
    text = str(exc).lower()
    if "fingerprint" in text:
        return "tls_fingerprint"
    if isinstance(exc, PermissionError) or "401" in text or "authentication" in text:
        return "auth"
    if isinstance(exc, (ConnectionError, TimeoutError)) or "refused" in text \
            or "timed out" in text or "unreachable" in text or "resolve" in text:
        return "unreachable"
    return "unknown"


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
        `InvalidHeader`. Every wrapped message below flows outward, to a 502
        `detail` (api/hosts.py), to the unencrypted `jobs.error` column and its
        SSE stream (jobs/backend.py::_finish), and to `job_events.message`; so
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
        return ProxmoxError(text, kind=_classify(e))

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
                            config: dict) -> str | None:
        """PUT /nodes/{node}/{lxc|qemu}/{vmid}/config -> UPID or None.

        NOT long-running: PVE writes the config file synchronously. A RUNNING
        qemu guest is the one case that returns a UPID, the change lands in
        the guest's pending-config section and PVE spawns a tiny task to record
        it; the guest itself only picks it up at next boot. A stopped guest or
        an lxc guest returns None and the write is already effective. Callers
        surface that difference rather than pretending it is a job.
        """
        try:
            return getattr(self._connect().nodes(node), kind)(vmid).config.put(**config)
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"config update failed for {kind}/{vmid} on {node}", e) from e

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
        """POST /nodes/{node}/qemu/{vmid}/vncproxy (websocket=1) -> {user, ticket, port, cert, upid}."""
        try:
            return self._connect().nodes(node).qemu(vmid).vncproxy.post(websocket=1)
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
