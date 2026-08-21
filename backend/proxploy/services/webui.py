"""Which scheme an app's web interface actually speaks.

UPSTREAM DOES NOT TELL US, AND THIS WAS CHECKED RATHER THAN ASSUMED. The
catalog we ingest is db.community-scripts.org's `script_scripts` collection
(services/catalog_metadata.py). Fetched whole on 2026-08-21: 700 records, and
the union of every key any record carries is 39 fields with no protocol,
scheme, tls or ssl among them. `port` is the only thing said about the web
interface at all. Actual Budget's record is exactly:

    "name": "Actual Budget", "slug": "actualbudget", "port": 5006,
    "notes": [], "website": "https://actualbudget.org/"

`website` is the PROJECT's homepage, not the container's, so it says nothing
about the guest. `notes` is free text and sometimes contains a worked example
URL, but only 36 of the 700 records have one and Actual Budget is not among
them. Meanwhile its install script calls community-scripts' own
`create_self_signed_cert` helper and writes

    "https": { "key": "/etc/ssl/actualbudget/actualbudget.key",
               "cert": "/etc/ssl/actualbudget/actualbudget.crt" }

into its config, so it serves TLS on 5006. Nothing we ingest records that,
and the port is 5006 rather than 443, so no inference from the catalog could
have found it either.

SO WE ASK THE APP. One TCP connect to the port the interface answers on, then
a TLS ClientHello: a TLS server completes the handshake, a plain HTTP server
does not (it either closes the connection or replies with a plaintext 400,
and both fail the handshake). That is a definitive answer from the only party
that actually knows, where every hint the catalog could have offered would
still have been a guess.

The alternative that was NOT taken: defaulting to http, which is what shipped
before this and is what sent the operator to `http://<ip>:5006` for an app
that only speaks https. A wrong scheme is not a degraded answer, it is a
browser error page, so "we could not tell" is raised to the caller instead of
being papered over with a default.
"""
from __future__ import annotations

import ipaddress
import re
import ssl
from urllib.parse import urlsplit

from proxploy.services.proxmox import ProxmoxError, open_validated_tcp_socket

# A click is waiting on this, and it is a connect on the LAN. Long enough for
# a busy container to finish a handshake, short enough that an app that is not
# listening at all says so rather than hanging the button.
PROBE_TIMEOUT_S = 3.0


def probe_scheme(address: str, port: int, timeout: float = PROBE_TIMEOUT_S) -> str | None:
    """"https", "http", or None when the port did not answer at all.

    None is a real third answer and must not be collapsed into "http": a
    stopped container, a wrong port and a firewall all land here, and none of
    them is evidence that the app speaks plain HTTP.
    """
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    # A community-scripts app's certificate is self-signed by design (that is
    # what `create_self_signed_cert` makes), so verifying it would reject
    # precisely the apps this exists to detect. Nothing is sent over this
    # socket and nothing read off it: the handshake completing is the whole
    # result, so there is no secret here for a bad certificate to leak.
    ctx.verify_mode = ssl.CERT_NONE
    try:
        # Shares the SSRF guard the fingerprint check uses rather than calling
        # socket.create_connection directly: the address comes back from PVE,
        # and a guest that reports a link-local address must not turn a click
        # into a connection to cloud instance metadata.
        sock = open_validated_tcp_socket(address, port, timeout=timeout)
    except (OSError, ProxmoxError):
        return None
    with sock:
        try:
            # No server_hostname: the target is an IP literal, which never
            # carries SNI anyway, and check_hostname is off.
            with ctx.wrap_socket(sock):
                return "https"
        except (ssl.SSLError, OSError):
            # Includes the timeout case, where a plain HTTP server sits
            # waiting for a request line that a ClientHello is not.
            return "http"


def scheme_for(app, address: str, port: int) -> tuple[str | None, str]:
    """The scheme to open this app with, and how that was decided.

    Three sources, in the order of how much each one actually knows:

    1. `web_protocol`, which only a person can have written, in Reconfigure.
       It is never probed over and never overwritten. NULL is the normal
       state; it used to be the literal string "http" written by install and
       adopt, which is why every app looked like a deliberate choice and none
       of them was.
    2. `installed_url`, the URL the install script printed about itself.
       Second rather than first because it is a statement about the moment of
       install, and an operator who has since changed the app is correcting
       exactly that.
    3. the probe, which is the only source left for an app Proxploy did not
       install and nobody has edited.

    Never a fourth branch that returns a bare "http". The second return value
    names which of the three answered, so a wrong open stays traceable.
    """
    if app.web_protocol:
        return app.web_protocol, "set on the app"
    installed = installed_parts(getattr(app, "installed_url", None))[0]
    if installed:
        return installed, "printed by the install script"
    return probe_scheme(address, port), "asked the app"


# --- what the installer itself said ----------------------------------------
#
# A community-scripts install script ends by printing the finished URL, and
# that is the app declaring its own scheme, port and path rather than us
# inferring any of them. The tail of a real successful install (job 231 in the
# dev database, Actual Budget) is, byte for byte:
#
#   '  \U0001f680  \x1b[m\x1b[1;92mActual Budget setup has been successfully initialized!\x1b[m'
#   '  \U0001f4a1  \x1b[m\x1b[33mAccess it using the following URL:\x1b[m'
#   '  \U0001f310  \x1b[m\x1b[4;92mhttps://192.168.50.194:5006\x1b[m'
#
# So the escapes come off first, and the emoji is just text in the way.

_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
_URL = re.compile(r"https?://[^\s\"'<>)\]]+")

# The banner is the last thing a script prints, but the exact distance varies
# with how many blank and status lines follow it (5 lines back on one install
# in the dev database, 3 on another). Wide enough to cover that, and the
# disagreement rule below is what actually keeps a stray URL out.
TAIL_LINES = 20


def _candidate(url: str) -> bool:
    """A URL is only a candidate if its host is an IP literal.

    Deliberately strict. Community-scripts prints the container's own address,
    never a name, so anything with a hostname is a link to somewhere else:
    a project homepage, a discussion thread, the docs. Several scripts print
    one of those a line or two from the end, and without this rule a
    single-candidate log could record `https://github.com/...` as the app's
    own web interface.
    """
    try:
        parts = urlsplit(url)
        if parts.hostname is None:
            return False
        ipaddress.ip_address(parts.hostname)
    except ValueError:
        return False
    return True


def _preferred(url: str, expected_port: int | None, guest_address: str | None) -> bool:
    """Whether this candidate is corroborated by something we already know."""
    parts = urlsplit(url)
    port = parts.port or (443 if parts.scheme == "https" else 80)
    return ((expected_port is not None and port == expected_port)
            or (guest_address is not None and parts.hostname == guest_address))


def url_from_install_log(lines, *, expected_port: int | None = None,
                         guest_address: str | None = None) -> str | None:
    """The app's own URL out of an install log tail, or None to stay quiet.

    None on any doubt, which is the point: the probe is still behind this, so
    recording nothing costs one TCP connect on the next click, while recording
    the wrong URL is a stored wrong answer that outlives the log it came from.

    `expected_port` (the catalog's port) and `guest_address` only break ties.
    They cannot be required, because both are routinely absent or stale: two
    of the apps in the dev database have no port on their row at all, and
    Dashy's install printed 192.168.50.188 for a container that now holds
    192.168.50.191, its DHCP lease having moved since.
    """
    seen: list[str] = []
    for raw in list(lines)[-TAIL_LINES:]:
        for match in _URL.finditer(_ANSI.sub("", raw or "")):
            url = match.group(0).rstrip(".,;")
            if url not in seen and _candidate(url):
                seen.append(url)
    if len(seen) == 1:
        return seen[0]
    # Two or more, so something has to break the tie, and exactly one thing
    # may: two corroborated candidates that disagree are not a tie, they are a
    # log this parser does not understand.
    corroborated = [u for u in seen if _preferred(u, expected_port, guest_address)]
    return corroborated[0] if len(corroborated) == 1 else None


def installed_parts(url: str | None) -> tuple[str | None, int | None, str | None]:
    """(scheme, port, path) out of a stored install URL. All None if there is none.

    The HOST in that URL is deliberately not returned and must never be used
    to open the app. It is the address the container held at install time, and
    on DHCP it moves: three of the five URLs recovered from the dev database's
    own install logs already name an address their container no longer has,
    and one of them now belongs to a different app. The live NIC read is the
    only honest source for the address.
    """
    if not url:
        return None, None, None
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        return None, None, None
    return (parts.scheme,
            parts.port or (443 if parts.scheme == "https" else 80),
            parts.path or "/")
