"""Is the app inside a container actually listening yet.

Proxmox answers `running` the moment `pct start` returns, while the
container's init is still booting and nothing is bound to the web port. That
is a true answer to a different question, and collapsing the two into one word
is what makes "Open" fail on a guest the UI has just called Running.

So `running` splits in two: the container is up (Proxmox's answer) and the app
answers on its port (this). Only guests with a known web port are ever asked;
a container with no web interface is Running the moment Proxmox says so,
because for that guest there is nothing else to mean.

Deliberately a TCP connect and not an HTTP request. The question is "is
anything listening", and a 404, a redirect or a self-signed certificate are
all still yes. api/apps.py::scheme_for does the richer probe, once, when
somebody actually opens the thing.

State lives on the poller in memory, next to `snapshots`, rather than in a
column: it is worth nothing across a restart (the first cycle re-probes) and a
migration for it would be a schema change to hold a cache.
"""
from __future__ import annotations

import socket
from datetime import datetime, timedelta

# How long a running guest may go on reading as "starting" before the pill
# gives up and calls it Running. An app that is not listening after this is not
# starting any more, it is broken, and that is a different thing to say (and
# not one the status pill is the place for). Two minutes covers a cold boot
# plus a slow first-run migration.
WEB_READY_CEILING_S = 120.0

# One connect, and it must not hold the poll cycle up. A container on the LAN
# either answers in single-digit milliseconds or is not listening.
PROBE_TIMEOUT_S = 0.4


def port_is_open(address: str, port: int) -> bool:
    """True if something accepts a TCP connection. Never raises."""
    try:
        with socket.create_connection((address, port), timeout=PROBE_TIMEOUT_S):
            return True
    except OSError:
        return False


class Readiness:
    """Per-app: has the web port been seen open, and since when.

    `mark` is called by the poller with the probe result; `state_for` is called
    by the API to decide what a running guest should read as. Both are cheap
    and neither talks to Proxmox.
    """

    def __init__(self) -> None:
        # app id -> (ready, since). `since` is when the CURRENT answer started,
        # which is what the ceiling below is measured from.
        self._seen: dict[int, tuple[bool, datetime]] = {}

    def mark(self, app_id: int, ready: bool, now: datetime) -> bool:
        """Record a probe result. True if the answer changed."""
        prev = self._seen.get(app_id)
        if prev is not None and prev[0] == ready:
            return False
        self._seen[app_id] = (ready, now)
        return True

    def forget(self, app_id: int) -> None:
        """A guest that is no longer running has no web port to be open, and
        must re-probe from scratch when it comes back: a DHCP container often
        returns on a different address."""
        self._seen.pop(app_id, None)

    def needs_probe(self, app_id: int) -> bool:
        """Only while the answer is still no. Once a guest has answered there
        is nothing this feature needs to re-check, so a settled fleet costs
        zero connects per cycle."""
        seen = self._seen.get(app_id)
        return seen is None or not seen[0]

    def state_for(self, app_id: int, now: datetime) -> str | None:
        """"starting", or None to leave the guest's own status alone."""
        seen = self._seen.get(app_id)
        if seen is None:
            # Running, has a port, never probed: the first cycle has not
            # reached it. Saying "starting" here would flash on every restart
            # of Proxploy itself, so it says nothing.
            return None
        ready, since = seen
        if ready:
            return None
        if (now - since) > timedelta(seconds=WEB_READY_CEILING_S):
            return None
        return "starting"
