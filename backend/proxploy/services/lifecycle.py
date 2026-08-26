"""Lifecycle job handlers. Proxploy's verbs are not Proxmox's: `restart` is
Proxmox's `reboot`, `pause` is `suspend` (the mapping lives once, in PVE_VERB
below). `stop` is the hard kill; `shutdown` is the graceful ACPI/init one.

Every action is: one status POST (returns a UPID), then poll the node's task
status and stream its task log into `job_events` until the task stops. These
are per-guest calls, deliberately outside the poller's O(nodes) budget; they
are triggered by a human, not a clock.
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
    """{(target_type, target_id): status} for guests with a job in flight.

    The value is what the guest should READ as, not the job kind: "removing"
    for an uninstall (the one that ends with the row gone), "pending" otherwise.

    One query for a whole list or poll cycle. `started_at` is NULL while a job
    is queued — the moment it most deserves the hold — so a missing stamp
    counts as fresh.
    """
    from datetime import timedelta

    from sqlalchemy import or_ as sa_or

    from proxploy.models import Job

    stale_before = now - timedelta(seconds=LIFECYCLE_HOLD_S)
    return {(t, i): ("removing" if k == "app.uninstall" else "pending")
            for t, i, k in db.query(Job.target_type, Job.target_id, Job.kind)
            .filter(Job.kind.in_(LIFECYCLE_KINDS),
                    Job.status.in_(("queued", "running")),
                    Job.target_id.isnot(None),
                    sa_or(Job.started_at.is_(None),
                          Job.started_at >= stale_before)).all()}

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


def _settle_status(app, target_type: str, target_id: int, status: str) -> None:
    """Write the known outcome of a finished action to the cached status
    column, before the resource event that makes open tabs refetch (a refetch
    before this write reads the poller's stale pre-action value). Corrected by
    the poller's next cycle; only the status field is touched.
    """
    with app.state.sessionmaker() as db:
        model = App if target_type == "app" else Vm
        row = db.get(model, target_id)
        if row is None:
            return
        if target_type == "app":
            row.status_cached = status
        else:
            row.status = status
        db.commit()


def job_kind(target_type: str, action: str) -> str:
    return f"{target_type}.{action}"


def _resolve(app, target_type: str, target_id: int):
    """Blocking: target -> (ProxmoxClient, kind, node, vmid, name). Runs in a thread."""
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
            # A missing credential is a failed job, not a 502; the message names
            # lifecycle specifically (CapabilityNotConfigured), not a bare 403.
            raise JobFailed(str(e)) from e
        kind = "lxc" if target_type == "app" else "qemu"
        vmid = row.ctid if target_type == "app" else row.vmid
        node = guest_node(host, row)
        return client, kind, node, int(vmid), row.name


async def run_lifecycle(ctx: JobContext, target_type: str, action: str,
                        params: dict) -> dict:
    app = ctx.backend.app
    target_id = int(params["target_id"])
    client, kind, node, vmid, name = await asyncio.to_thread(
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
        # "not running" + 500 is a no-op, not a failure (the outcome the
        # caller wanted).
        #
        # ponytail: matched on PVE's message text, since there is no status
        # read on the client and adding a /cluster/resources round trip before
        # every stop costs more than this string comparison. If PVE ever
        # rephrases it, the job goes back to failing loudly rather than
        # silently doing the wrong thing.
        if action in ("stop", "shutdown") and "not running" in str(e):
            ctx.log(f"{name} ({kind} {vmid}) is already stopped; nothing to do")
            # Stopped is the outcome the caller wanted, even though PVE never
            # ran a task for it, so settle the row the same way a real
            # stop/shutdown does below rather than leaving whatever the
            # poller last saw (which is what triggered the stop in the
            # first place).
            await asyncio.to_thread(_settle_status, app, target_type,
                                    target_id, "stopped")
            app.state.bus.publish("resource", {"type": target_type,
                                               "id": target_id,
                                               "change": "lifecycle"})
            return {"upid": None, "exitstatus": "OK", "node": node,
                    "vmid": vmid, "noop": "already stopped"}
        raise
    status = await await_task(ctx, client, node, upid,
                              timeout_s=TASK_TIMEOUT_S, poll_s=TASK_POLL_S)

    # await_task raises JobFailed unless PVE confirmed success, so reaching
    # here means the action completed. Write status before the resource event:
    # a refetch before this write reads the poller's stale value ("stop
    # flashes back to running" bug).
    await asyncio.to_thread(_settle_status, app, target_type, target_id,
                            RESULT_STATUS[action])
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
    """Destroy an app's CT on PVE, then forget the app row. Stop first (PVE
    refuses to destroy a running CT); delete the row only AFTER PVE confirms
    the destroy — deleting first with a failed destroy leaves an orphaned CT
    with no recovery path. A stop failure is logged and the destroy still
    attempted.
    """
    app = ctx.backend.app
    target_id = int(params["target_id"])
    client, kind, node, vmid, name = await asyncio.to_thread(
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
