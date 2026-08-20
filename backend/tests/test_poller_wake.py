"""Poller.wake(): a create/destroy asks for the next cycle now.

The three properties the wake has to hold, one test each: it shortens the wait,
it does not shorten the failure backoff, and a burst of them costs one cycle.
Exercised directly against _host_loop with a stubbed _poll_once, since none of
this is about what a cycle reads, only about when the loop runs one.
"""
import asyncio
from types import SimpleNamespace

from proxploy.events import EventBus
from proxploy.pollers import Poller


class _StubPoller(Poller):
    """Counts cycles instead of talking to Proxmox. `fail` makes every cycle
    raise, which is what puts _host_loop on its backoff path."""

    def __init__(self, interval_s: float, fail: bool = False) -> None:
        state = SimpleNamespace(
            settings=SimpleNamespace(poll_interval_s=interval_s,
                                     poll_timeout_s=5.0),
            bus=EventBus())
        super().__init__(SimpleNamespace(state=state))
        self.cycles = 0
        self.fail = fail

    def _poll_once(self, host_id):          # runs in a thread, like the real one
        self.cycles += 1
        if self.fail:
            raise RuntimeError("host is not answering")
        return []

    def _mark_unreachable(self, host_id, reason):
        return []


async def _settle(seconds: float = 0.3) -> None:
    await asyncio.sleep(seconds)


def test_wake_polls_now_instead_of_waiting_out_the_interval():
    async def go():
        p = _StubPoller(interval_s=30.0)
        task = asyncio.create_task(p._host_loop(1))
        await _settle()
        assert p.cycles == 1                # the opening cycle, then a 30 s wait

        p.wake(1)
        await _settle()
        assert p.cycles == 2                # not 30 s later

        task.cancel()

    asyncio.run(go())


def test_wake_does_not_shorten_the_failure_backoff():
    """Otherwise a create against a dead host turns its loop into a hot retry
    against the thing that is already not answering."""
    async def go():
        # One failure puts the delay at interval * 2, so a wake that was
        # honoured would show up as a second cycle well inside a second.
        p = _StubPoller(interval_s=1.0, fail=True)
        task = asyncio.create_task(p._host_loop(1))
        await _settle()
        assert p.cycles == 1

        p.wake(1)
        await _settle(0.5)
        assert p.cycles == 1                # still serving the backoff

        task.cancel()

    asyncio.run(go())


def test_a_burst_of_wakes_costs_one_cycle():
    """Creating five VMs in a row must not queue five immediate cycles."""
    async def go():
        p = _StubPoller(interval_s=30.0)
        task = asyncio.create_task(p._host_loop(1))
        await _settle()
        assert p.cycles == 1

        for _ in range(5):
            p.wake(1)
        await _settle()
        assert p.cycles == 2                # one pending wake per host, not five

        task.cancel()

    asyncio.run(go())


def test_wake_before_the_host_has_a_loop_is_honoured_by_the_first_wait():
    """A wake can land while the poller is mid-cycle or before it has started
    one at all; neither may lose it or raise."""
    async def go():
        p = _StubPoller(interval_s=30.0)
        p.wake(1)                           # no _host_loop task exists yet
        task = asyncio.create_task(p._host_loop(1))
        await _settle()
        # Opening cycle, then the wait consumes the pending wake and runs
        # another one rather than sitting out the interval.
        assert p.cycles == 2

        task.cancel()

    asyncio.run(go())
