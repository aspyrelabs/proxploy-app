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
    column, before the resource event that tells open tabs to refetch it.

    This does not contradict doc 04's "Proxmox is the truth": the poller
    stays the sole authority on ongoing state and this write does not
    pre-empt it, it is not a reading we invented between polls. It is
    Proxmox itself, via the task result, telling us the action finished, and
    is corrected by the poller's next cycle the same as any other value in
    this column. Only the status field is touched; cpu/mem/disk/net stay
    whatever the poller last measured.
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
            # Same sentence as before the extraction: a job reports a missing
            # credential as a failed job, never as a 502. Now also covers a
            # host with monitoring configured but no lifecycle token: the
            # message names lifecycle specifically (CapabilityNotConfigured),
            # not a bare 403 relay.
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

    # await_task raises JobFailed on anything but a successful exitstatus, so
    # reaching this line means PVE has confirmed the action completed. Write
    # the resulting status now, before publishing the resource event: the
    # event tells every open tab to refetch, and without this write that
    # refetch would read the poller's stale pre-action value, since the
    # poller's own cycle can be up to 30 seconds away (this was the "stop
    # flashes back to running" bug). This is not a guess at unpolled state,
    # it is what the task result just told us; see _settle_status.
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

    def _forget() -> None:
        with app.state.sessionmaker() as db:
            row = db.get(App, target_id)
            if row is not None:
                # app_scripts cascades on the FK; nothing else references apps.
                db.delete(row)
                db.commit()

    await asyncio.to_thread(_forget)
    ctx.log(f"{name} removed")
    app.state.bus.publish("resource", {"type": "app", "id": target_id,
                                       "change": "removed"})
    return {"upid": upid, "exitstatus": status.get("exitstatus"),
            "node": node, "vmid": vmid, "removed": True}


HANDLERS["app.uninstall"] = run_app_uninstall
