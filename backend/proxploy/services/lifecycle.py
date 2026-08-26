"""Lifecycle job handlers (doc 10 Phase 3, doc 01 §2/§4, doc 05 Apps/VMs rows).

Proxploy's verbs are not Proxmox's verbs, `restart` is Proxmox's `reboot`,
`pause` is `suspend`. The mapping is stated once, here, and nowhere else.
`stop` is the hard kill; `shutdown` is the graceful ACPI/init one, matching
Proxmox's own distinction.

Every action is: one status POST (which returns a UPID), then poll the node's
task status and stream its task log into `job_events` until the task stops.
These are per-guest calls, deliberately outside the poller's O(nodes) budget
(doc 02 §3); they are triggered by a human, not by a clock.
"""
from __future__ import annotations

import asyncio

from proxploy.jobs import HANDLERS, JobContext, JobFailed
from proxploy.models import App, Host, Vm
from proxploy.services.hostclient import client_for_host, guest_node
from proxploy.services.proxmox import ProxmoxError
from proxploy.services.pvetask import TASK_POLL_S, TASK_TIMEOUT_S, await_task

APP_ACTIONS = ("start", "stop", "restart", "shutdown")
VM_ACTIONS = ("start", "stop", "restart", "shutdown", "pause", "resume")

# Everything that makes a guest's status untrustworthy while it runs, as job
# kinds ("app.stop", "vm.restart", "app.uninstall"). Proxmox reports the OLD
# status for as long as one of these is actually running, so both the poller
# and the list routes have to know to stop answering for that guest.
LIFECYCLE_KINDS = frozenset(
    [f"app.{v}" for v in APP_ACTIONS] + [f"vm.{v}" for v in VM_ACTIONS]
    # Removal belongs here for the same reason: the container is still there,
    # and still reads `running`, right up until it is not there at all.
    + ["app.uninstall"])

# How long one of those may hold its guest before the truth is Proxmox's
# again. A hold that outlives its job would freeze a guest for ever on a
# worker that died mid-action, so this is a ceiling, not a promise.
LIFECYCLE_HOLD_S = 300


def busy_guests(db, now):
    """{(target_type, target_id): status} for guests whose status is not theirs
    to report yet.

    The value is what the guest should READ as, not the job kind: "removing"
    for an uninstall, "pending" for everything else. A removal deserves its own
    word because it is the one that ends with the row gone, and "Working" on a
    thing that is about to disappear tells you less than "Removing" does.

    TWO holds, and the second is the one that matters. A job finishing is not
    the action finishing: app.stop takes 1.2s on the dev cluster, while
    /cluster/resources goes on reporting `running` for seconds after. Holding
    only for the job's lifetime released the guest onto that stale reading, and
    the pill went Working, running, stopping: the flicker reported four times,
    which survived three fixes that each tightened the JOB window.

    So the hold runs until the guest is OBSERVED in the state asked for, with
    `LIFECYCLE_HOLD_S` as the ceiling. Past it the guest reads "error": we
    asked, PVE said the task succeeded, the guest is not there. Only the
    NEWEST job per target counts, or an old succeeded `start` fights a fresh
    `stop`. The error tier clears itself once the guest arrives, and in any
    case at twice the ceiling: a guest wrong for ten minutes is no longer news
    about an action, it is just its status.
    """
    from datetime import timedelta

    from sqlalchemy import or_ as sa_or

    from proxploy.models import Job

    stale_before = now - timedelta(seconds=LIFECYCLE_HOLD_S)
    holds: dict[tuple[str, int], str] = {}

    # 1. In flight. `started_at` is NULL while a job is still queued, which is
    #    the moment it most deserves the hold, so a missing stamp counts as
    #    fresh. A hold that outlived its job would freeze a guest for ever on a
    #    worker that died mid-action, hence the ceiling here too.
    for t, i, k in (db.query(Job.target_type, Job.target_id, Job.kind)
                    .filter(Job.kind.in_(LIFECYCLE_KINDS),
                            Job.status.in_(("queued", "running")),
                            Job.target_id.isnot(None),
                            sa_or(Job.started_at.is_(None),
                                  Job.started_at >= stale_before)).all()):
        holds[(t, i)] = "removing" if k == "app.uninstall" else "pending"

    # 2. Succeeded, but the guest has not been seen in the asked-for state yet.
    #    app.uninstall is excluded on purpose: its finish line is the row being
    #    gone, so there is no status left to compare against.
    # Two tiers, and the window has to span both or the error branch below is
    # unreachable: inside the ceiling the guest reads `pending`, past it
    # `error`, and past twice it the query stops carrying the job at all and
    # Proxmox's own answer stands again. That last tier is what keeps this
    # bounded, both in rows scanned and in how long a guest can be labelled by
    # an action nobody remembers asking for.
    forget_before = now - timedelta(seconds=LIFECYCLE_HOLD_S * 2)
    settled = (db.query(Job.target_type, Job.target_id, Job.kind, Job.created_at)
               .filter(Job.kind.in_(LIFECYCLE_KINDS),
                       Job.kind != "app.uninstall",
                       Job.status == "succeeded",
                       Job.target_id.isnot(None),
                       Job.created_at >= forget_before)
               .order_by(Job.id.desc()).all())
    seen: set[tuple[str, int]] = set()
    for t, i, k, created in settled:
        key = (t, i)
        # Newest first, so the first row for a target is the one that counts
        # and anything older is a settled question.
        if key in seen or key in holds:
            continue
        seen.add(key)
        want = RESULT_STATUS.get(k.split(".", 1)[1])
        if want is None:
            continue
        observed = _observed_status(db, t, i)
        if observed is None or observed == want:
            continue
        holds[key] = "pending" if created >= stale_before else "error"

    return holds


# How long a targeted per-guest reading outranks the bulk /cluster/resources
# one. The bulk read lags a finished task by seconds; the targeted read is
# taken after it. Both are observations, so this is not belief beating truth,
# it is the NEWER answer beating the older one.
FRESH_OBSERVATION_S = 15.0


def freshly_confirmed(db, now) -> set[tuple[str, int]]:
    """Guests whose current status was just confirmed by a targeted read.

    The poller must not write `status` for these: its /cluster/resources
    answer was taken before the read that settled them and would put the guest
    back to its pre-action state. Its other readings (cpu, memory, uptime) are
    unaffected and still written.

    Keyed on the row ALREADY matching what the newest recent action asked for,
    so it only ever protects a guest that has arrived, never one still in
    flight (which busy_guests is holding anyway).
    """
    from datetime import timedelta

    from proxploy.models import Job

    since = now - timedelta(seconds=FRESH_OBSERVATION_S)
    out: set[tuple[str, int]] = set()
    seen: set[tuple[str, int]] = set()
    rows = (db.query(Job.target_type, Job.target_id, Job.kind)
            .filter(Job.kind.in_(LIFECYCLE_KINDS),
                    Job.kind != "app.uninstall",
                    Job.status == "succeeded",
                    Job.target_id.isnot(None),
                    Job.finished_at.isnot(None),
                    Job.finished_at >= since)
            .order_by(Job.id.desc()).all())
    for t, i, k in rows:
        key = (t, i)
        if key in seen:
            continue
        seen.add(key)
        want = RESULT_STATUS.get(k.split(".", 1)[1])
        if want is not None and _observed_status(db, t, i) == want:
            out.add(key)
    return out


def _observed_status(db, target_type: str, target_id: int) -> str | None:
    """What the poller last wrote for this guest, or None if the row is gone.

    This column is written by the poller and by nobody else, which is what
    makes it usable as the release condition. run_lifecycle deliberately does
    not stamp the expected outcome here after a successful task: that would be
    our belief sitting in the readings column, and the hold would end on our
    own say-so instead of on Proxmox agreeing.
    """
    model = App if target_type == "app" else Vm
    row = db.get(model, target_id)
    if row is None:
        return None
    return row.status_cached if target_type == "app" else row.status

PVE_VERB = {
    "start": "start",
    "stop": "stop",          # hard kill
    "shutdown": "shutdown",  # graceful
    "restart": "reboot",
    "pause": "suspend",
    "resume": "resume",
}

# The status a successful action settles the row to, matching the strings the
# poller itself writes from PVE's /cluster/resources "status" field. This is
# not a guess at the poller's next reading, it is what PVE just told us the
# task did; see the comment at the call site below.
RESULT_STATUS = {
    "start": "running",
    "stop": "stopped",
    "shutdown": "stopped",
    "restart": "running",
    "pause": "paused",
    "resume": "running",
}




def _record_observed(app, target_type: str, target_id: int,
                     kind: str, node: str, vmid: int) -> tuple[str | None, str | None]:
    """Ask Proxmox what the guest is NOW, and store that. Blocking.

    Not `_settle_status` returning. That wrote RESULT_STATUS, our BELIEF about
    what the action did, into the poller's readings column, where the next poll
    overwrote it: the flicker. This writes what Proxmox answers when asked, one
    call for one guest, so it is an observation like any other and the hold may
    release on it. If PVE has not caught up it answers with the pre-action
    state, that is recorded faithfully, and the hold stays: wrong only in the
    safe direction.
    """
    with app.state.sessionmaker() as db:
        model = App if target_type == "app" else Vm
        row = db.get(model, target_id)
        if row is None:
            return None, None
        host = db.get(Host, row.host_id)
        if host is None:
            return None, None
        try:
            # MONITORING, not the lifecycle client this action ran on: reading
            # a guest needs VM.Audit, which the lifecycle token does not hold.
            reader = client_for_host(app, db, host, capability="monitoring")
            observed = reader.guest_status(kind, node, vmid)
        except Exception as e:  # noqa: BLE001  (an optimisation, never fatal)
            return None, str(e)
        if observed is None:
            return None, "no status field in the reply"
        if target_type == "app":
            row.status_cached = observed
        else:
            row.status = observed
        db.commit()
    return observed, None


# How long to keep asking Proxmox whether the action landed, and how often.
# Deliberately small: this is covering the gap between a task reporting done
# and /cluster/resources agreeing, which is tens to hundreds of milliseconds,
# not an operation of its own. Anything slower than this is the poller's job.
OBSERVE_BUDGET_S = 3.0
OBSERVE_EVERY_S = 0.25


async def _observe_until(app, target_type: str, target_id: int, kind: str,
                         node: str, vmid: int, want: str | None):
    """Record what Proxmox says, re-asking until it says `want`.

    Returns as soon as the asked-for state is seen, so the common case is a
    single read. Gives up quietly at OBSERVE_BUDGET_S and leaves the last
    reading recorded: the hold stays, and the wake'd poll cycle settles it.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + OBSERVE_BUDGET_S
    observed, why = None, None
    while True:
        observed, why = await asyncio.to_thread(_record_observed, app, target_type,
                                                target_id, kind, node, vmid)
        # None means the read itself failed (no monitoring token, guest gone);
        # re-asking would just fail the same way.
        if observed is None or observed == want or loop.time() >= deadline:
            return observed, why
        await asyncio.sleep(OBSERVE_EVERY_S)


def job_kind(target_type: str, action: str) -> str:
    return f"{target_type}.{action}"


def _resolve(app, target_type: str, target_id: int):
    """Blocking: target -> (client, kind, node, vmid, name, host_id). In a thread.

    host_id comes back so the caller can wake that host's poller: the hold on
    a guest lifts on the poller OBSERVING the new state, so without a wake the
    pill spins until the next 30s cycle for an action Proxmox finished in
    three seconds.
    """
    with app.state.sessionmaker() as db:
        model = App if target_type == "app" else Vm
        row = db.get(model, target_id)
        if row is None:
            raise JobFailed(f"{target_type} {target_id} not found")
        host = db.get(Host, row.host_id)
        if host is None:
            raise JobFailed(f"host for {target_type} {target_id} not found")
        try:
            client = client_for_host(app, db, host, capability="lifecycle")
        except ProxmoxError as e:
            # Same sentence as before the extraction: a job reports a missing
            # credential as a failed job, never as a 502. Now also covers a
            # host with monitoring configured but no lifecycle token: the
            # message names lifecycle specifically (CapabilityNotConfigured),
            # not a bare 403 relay.
            raise JobFailed(str(e)) from e
        kind = "lxc" if target_type == "app" else "qemu"
        vmid = row.ctid if target_type == "app" else row.vmid
        node = guest_node(host, row)
        return client, kind, node, int(vmid), row.name, host.id


async def run_lifecycle(ctx: JobContext, target_type: str, action: str,
                        params: dict) -> dict:
    app = ctx.backend.app
    target_id = int(params["target_id"])
    client, kind, node, vmid, name, host_id = await asyncio.to_thread(
        _resolve, app, target_type, target_id)

    ctx.log(f"{action} {name} ({kind} {vmid}) on node {node}")
    try:
        upid = await asyncio.to_thread(client.guest_action, kind, node, vmid,
                                       PVE_VERB[action])
    except asyncio.CancelledError:
        # to_thread cannot interrupt the thread once it has started: the POST
        # may already have reached proxmox, but the UPID it would return is
        # discarded here, so there is no task to point at. Leave a breadcrumb
        # even without one, rather than pretending the job vanished cleanly.
        ctx.log(f"canceled while issuing {action} on {kind} {vmid} at {node}, "
                f"the request may have already reached proxmox; no task id was "
                f"captured to track it", stream="stderr")
        raise
    except ProxmoxError as e:
        # Stopping something already stopped is the outcome the caller wanted,
        # not a failure. PVE answers "CT 502 not running" / "VM 600 not
        # running" with a 500, which surfaced in the UI as a red failed job for
        # a no-op (PVE 9.2.6, 2026-08-10). run_app_uninstall already tolerated
        # exactly this case; the same reasoning belongs here.
        #
        # ponytail: matched on PVE's message text, since there is no status
        # read on the client and adding a /cluster/resources round trip before
        # every stop costs more than this string comparison. If PVE ever
        # rephrases it, the job goes back to failing loudly rather than
        # silently doing the wrong thing.
        if action in ("stop", "shutdown") and "not running" in str(e):
            ctx.log(f"{name} ({kind} {vmid}) is already stopped; nothing to do")
            # No status written here on purpose. busy_guests holds the guest
            # until the poller SEES it stopped, and writing our own answer
            # would end that hold on our own say-so. The wake is what makes
            # that observation arrive now rather than up to 30s from now.
            app.state.poller.wake(host_id)
            app.state.bus.publish("resource", {"type": target_type,
                                               "id": target_id,
                                               "change": "lifecycle"})
            return {"upid": None, "exitstatus": "OK", "node": node,
                    "vmid": vmid, "noop": "already stopped"}
        raise
    status = await await_task(ctx, client, node, upid,
                              timeout_s=TASK_TIMEOUT_S, poll_s=TASK_POLL_S)

    # Nothing is written to the status column here, and that IS the fix for
    # "stop flashes back to running", not a regression of it. Writing
    # RESULT_STATUS here put our belief in the column the poller writes its
    # readings to, and the next poll overwrote it. The hold covers that window
    # now.
    #
    # Which makes this wake load-bearing rather than a nicety: the hold lifts
    # on an OBSERVATION, so without asking for one now the guest spins for the
    # rest of the 30s cycle after an action Proxmox finished in three seconds.
    # /cluster/resources reflects a finished task within 17 to 39 ms (measured
    # on the lab cluster, see Poller.wake), so the re-poll really does return
    # the new state rather than the old one again.
    # Read it, do not assume it, and keep asking until Proxmox agrees.
    #
    # One read is not enough: a task reporting done means the command was
    # accepted, and /cluster/resources can still answer with the PRE-action
    # state for a moment after. A single read that lands in that moment
    # records the old value, the hold stays, and settling falls back to the
    # next full poll cycle, which is seconds. That is the "it went slow
    # again" report.
    #
    # So: ask, and if it is not there yet ask again, for a short budget. Each
    # ask is one field for one guest (42 to 75 ms measured on the lab
    # cluster), so the whole loop normally costs one or two of them. The
    # budget is a ceiling, not a wait: a guest that has arrived returns
    # immediately, and one that has not still gets the wake below.
    observed, why = await _observe_until(app, target_type, target_id, kind,
                                         node, vmid, RESULT_STATUS[action])
    if observed is not None:
        ctx.log(f"{name} is {observed}")
        # Only logged, not published as its own `status` delta. api/live.ts
        # treats every resource event as "go and ask" now rather than as the
        # answer, so the `lifecycle` event below already triggers the one
        # refetch this needs; a second delta would just be a second GET.
    elif why:
        # Said out loud rather than swallowed. This read failing is not a
        # failed action, it just means the pill settles on the next poll
        # instead of now, and a silent version of exactly this hid a 403 for
        # a whole session.
        ctx.log(f"could not read {name} back ({why}); waiting for the poller")
    # Woken ONLY when the read above did not already settle it. Waking on a
    # confirmed guest is what put the 5 second gap in: the targeted read
    # recorded `stopped` and the hold lifted, then the wake'd cycle read
    # /cluster/resources, which still said `running`, wrote that over the top
    # and re-engaged the hold until the following cycle. Measured on the lab
    # cluster: read at 51.7s, clobbered at 51.8s, correct again at 56.9s.
    if observed != RESULT_STATUS[action]:
        app.state.poller.wake(host_id)
    app.state.bus.publish("resource", {"type": target_type, "id": target_id,
                                       "change": "lifecycle"})
    return {"upid": upid, "exitstatus": status.get("exitstatus"),
            "node": node, "vmid": vmid}


def _register(target_type: str, action: str) -> None:
    async def run(ctx: JobContext, params: dict) -> dict:
        return await run_lifecycle(ctx, target_type, action, params)

    run.__name__ = f"{target_type}_{action}"
    HANDLERS[job_kind(target_type, action)] = run


for _verb in APP_ACTIONS:
    _register("app", _verb)
for _verb in VM_ACTIONS:
    _register("vm", _verb)


async def run_app_uninstall(ctx: JobContext, params: dict) -> dict:
    """Destroy an app's CT on PVE, then forget the app row.

    Ordering is deliberate. PVE refuses to destroy a running container, so the
    stop comes first; and the row is deleted only AFTER PVE confirms the
    destroy, because a row deleted first with a failed destroy leaves an
    orphaned CT that Proxploy no longer knows about, which is the one outcome
    with no recovery path through the UI. The reverse (CT gone, row lingering)
    is self-correcting: the poller marks it missing and the operator can forget
    it.

    A stop failure is logged and the destroy is attempted anyway: an already-
    stopped container reports one, and so does a container PVE considers
    wedged, which is exactly when someone reaches for uninstall.
    """
    app = ctx.backend.app
    target_id = int(params["target_id"])
    client, kind, node, vmid, name, host_id = await asyncio.to_thread(
        _resolve, app, "app", target_id)

    ctx.log(f"stopping {name} ({kind} {vmid}) on node {node} before removal")
    try:
        upid = await asyncio.to_thread(client.guest_action, kind, node, vmid, "stop")
        await await_task(ctx, client, node, upid,
                         timeout_s=TASK_TIMEOUT_S, poll_s=TASK_POLL_S)
    except (ProxmoxError, JobFailed) as e:
        ctx.log(f"stop did not succeed ({e}); attempting removal anyway",
                stream="stderr")

    ctx.log(f"destroying {kind} {vmid} on node {node}")
    upid = await asyncio.to_thread(client.guest_delete, kind, node, vmid)
    status = await await_task(ctx, client, node, upid,
                              timeout_s=TASK_TIMEOUT_S, poll_s=TASK_POLL_S)

    def _forget() -> int | None:
        with app.state.sessionmaker() as db:
            row = db.get(App, target_id)
            if row is None:
                return None
            host_id = row.host_id
            # app_scripts cascades on the FK; nothing else references apps.
            db.delete(row)
            db.commit()
            return host_id

    host_id = await asyncio.to_thread(_forget)
    ctx.log(f"{name} removed")
    if host_id is not None:
        # The app row is gone from the DB already, so the list is right without
        # any help. The wake is for the poller's snapshot, which still holds
        # this CT and therefore keeps offering the container an operator just
        # destroyed as an adoptable one on the Apps page until the next cycle.
        app.state.poller.wake(host_id)
    app.state.bus.publish("resource", {"type": "app", "id": target_id,
                                       "change": "removed"})
    return {"upid": upid, "exitstatus": status.get("exitstatus"),
            "node": node, "vmid": vmid, "removed": True}


HANDLERS["app.uninstall"] = run_app_uninstall
