"""Which port an adopted container serves its web UI on, guessed from inside.

An app installed from the store carries its port in the catalog. One adopted by
hand carries nothing, so the row has no `web_port`, so the Apps row shows no
Open button and there is no way to get one short of the operator already
knowing the number.

Proxmox cannot answer this. `pct config` describes the NIC and says nothing
about listening sockets, and no PVE API route exposes them. The only place the
answer exists is inside the container, which `pct exec ss -lntpH` reaches over
the same root-SSH-to-the-node transport services/appstore.py already installs
with.

THIS IS A GUESS, and the API says so rather than presenting a number as fact:
`detect_ports` returns a ranked LIST of candidates for a human to choose from,
and never writes web_port itself. A container can serve two UIs, can be
mid-restart, or can listen on something this ranking has never heard of.
"""
from __future__ import annotations

import re
import shlex

# `ss -lntpH`: listening, tcp, numeric, with process, no header line. The
# column layout of the header changes between iproute2 versions and the -H is
# what stops that mattering.
SS_COMMAND = "ss -lntpH"

# Never a web UI, on any container. Offering one produces an Open button that
# opens something the browser cannot render.
INFRASTRUCTURE_PORTS = frozenset({
    22,     # ssh
    25, 465, 587,   # smtp
    53,     # dns
    111,    # rpcbind
    3306, 5432, 6379, 27017,   # databases
})

# Preferred when several are reachable, in this order, before falling back to
# the lowest remaining port. A container running both a redirect on 80 and the
# real site on 443 should be offered 443.
PREFERRED_PORTS = (443, 80, 8443, 8080)

# A real -H line still carries the state and queue columns first:
#
#   LISTEN 0 4096 *:443 *:* users:(("caddy",pid=8143,fd=3))
#
# so this scans for the local address TOKEN rather than anchoring at the start
# of the line, which is what a fixture written from an awk-sliced copy of the
# output led me to do first: it matched nothing at all against the real thing.
# The peer column cannot be mistaken for it, because a peer is `0.0.0.0:*` or
# `*:*` and never ends in digits.
_ADDR_RE = re.compile(r"(?:^|\s)(?P<addr>\[[^\]]+\]|[^\s:]+):(?P<port>\d+)(?=\s|$)")
_PROC_RE = re.compile(r'users:\(\("(?P<proc>[^"]+)"')


def _reachable(addr: str) -> bool:
    """Whether a browser elsewhere on the network could reach this socket.

    A socket bound to loopback is unreachable from anywhere but the container
    itself, whatever else is true of it. Proxploy's own container is the
    example that matters: uvicorn binds 127.0.0.1:8000 deliberately and Caddy
    is the only thing that answers from outside, so a ranking that offered 8000
    would be offering a button built to fail.
    """
    return addr not in ("127.0.0.1", "::1", "[::1]", "localhost")


def rank_ports(ss_output: str) -> list[dict]:
    """Parse `ss -lntpH` output into ranked candidates, best guess first.

    Unparseable lines are skipped rather than raised on: ss output is not a
    promise, and one odd line must not take the whole detection down.
    """
    seen: dict[int, dict] = {}
    for line in ss_output.splitlines():
        line = line.strip()
        m = _ADDR_RE.search(line)
        if m is None:
            continue
        addr, port = m.group("addr"), int(m.group("port"))
        if not _reachable(addr) or port in INFRASTRUCTURE_PORTS:
            continue
        proc = _PROC_RE.search(line)
        # First binding of a port wins; the same port on v4 and v6 is one
        # answer, not two rows saying the same thing.
        seen.setdefault(port, {"port": port,
                               "process": proc.group("proc") if proc else None,
                               "address": addr})

    def rank(c: dict) -> tuple[int, int]:
        try:
            return (PREFERRED_PORTS.index(c["port"]), 0)
        except ValueError:
            # Everything unlisted sorts after every preference, then by port so
            # the list is the same on every run. A order that reshuffles
            # between detections is one nobody can trust.
            return (len(PREFERRED_PORTS), c["port"])

    return sorted(seen.values(), key=rank)


def detect_command(ctid: int) -> str:
    """The host-side command: run ss INSIDE the container.

    On the host it would report the node's own sockets, which is a different
    machine's answer entirely.
    """
    return f"pct exec {int(ctid)} -- {shlex.quote('sh')} -c {shlex.quote(SS_COMMAND)}"
