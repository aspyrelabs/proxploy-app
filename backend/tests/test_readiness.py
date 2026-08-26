"""A running container is not a reachable app.

Proxmox answers `running` the moment `pct start` returns, while the container's
init is still booting and nothing is bound to the web port. Reported on
hardware: "when proxploy shows a ct as started the ct has not actually started,
so clicking open fails".
"""
from datetime import datetime, timedelta

from proxploy.services.readiness import WEB_READY_CEILING_S, Readiness

NOW = datetime(2026, 1, 1, 12, 0)


def test_a_guest_that_has_not_answered_reads_as_starting():
    r = Readiness()
    r.mark(1, False, NOW)
    assert r.state_for(1, NOW) == "starting"


def test_a_guest_that_answers_reads_as_itself():
    r = Readiness()
    r.mark(1, True, NOW)
    assert r.state_for(1, NOW) is None


def test_a_never_probed_guest_says_nothing():
    """Otherwise every restart of Proxploy itself flashes Starting across the
    whole fleet before the first cycle lands."""
    assert Readiness().state_for(1, NOW) is None


def test_it_gives_up_rather_than_saying_starting_for_ever():
    """An app not listening after the ceiling is not starting, it is broken,
    and that is not the status pill's sentence to say."""
    r = Readiness()
    r.mark(1, False, NOW)
    assert r.state_for(1, NOW + timedelta(seconds=WEB_READY_CEILING_S + 1)) is None


def test_a_settled_guest_is_never_probed_again():
    """The cost of this feature on a fleet where everything is up must be
    zero connects per cycle."""
    r = Readiness()
    assert r.needs_probe(1) is True
    r.mark(1, True, NOW)
    assert r.needs_probe(1) is False


def test_a_stopped_guest_forgets_its_answer():
    """It must re-probe when it comes back: a DHCP container usually returns on
    a different address, so a remembered yes would be about the old one."""
    r = Readiness()
    r.mark(1, True, NOW)
    r.forget(1)
    assert r.needs_probe(1) is True
    assert r.state_for(1, NOW) is None
