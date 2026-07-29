"""Lifecycle job handlers (doc 10 Phase 3, doc 01 §2/§4, doc 05 Apps/VMs rows).

Proxploy's verbs are not Proxmox's verbs — `restart` is Proxmox's `reboot`,
`pause` is `suspend`. The mapping is stated once, here, and nowhere else.
`stop` is the hard kill; `shutdown` is the graceful ACPI/init one, matching
Proxmox's own distinction.

Every action is: one status POST (which returns a UPID), then poll the node's
task status and stream its task log into `job_events` until the task stops.
These are per-guest calls, deliberately outside the poller's O(nodes) budget
(doc 02 §3) — they are triggered by a human, not by a clock.
"""
from __future__ import annotations

import asyncio
import json as jsonlib

from proxploy.jobs import HANDLERS, JobContext, JobFailed
from proxploy.models import App, Host, HostCredential, Vm
from proxploy.services.proxmox import ProxmoxClient

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

TASK_POLL_S = 1.0
# ponytail: flat wall-clock ceiling per lifecycle action. A slow shutdown that
# genuinely needs longer belongs to a per-kind timeout table, which is worth
# building when a real workload proves one action needs it.
TASK_TIMEOUT_S = 300.0


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
        cred = (db.query(HostCredential)
                .filter_by(host_id=host.id, kind="api_token").one_or_none())
        if cred is None:
            raise JobFailed(f"host {host.name} has no API token credential")
        tok = jsonlib.loads(app.state.secretstore.decrypt(cred.encrypted_blob))
        client = ProxmoxClient(host.address, tok["token_id"], tok["token_secret"],
                               verify_tls=host.verify_tls,
                               tls_fingerprint=host.tls_fingerprint,
                               factory=app.state.proxmox_factory)
        kind = "lxc" if target_type == "app" else "qemu"
        vmid = row.ctid if target_type == "app" else row.vmid
        node = host.node_name or ""
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
        # to_thread cannot interrupt the thread once it has started — the POST
        # may already have reached proxmox, but the UPID it would return is
        # discarded here, so there is no task to point at. Leave a breadcrumb
        # even without one, rather than pretending the job vanished cleanly.
        ctx.log(f"canceled while issuing {action} on {kind} {vmid} at {node} — "
                f"the request may have already reached proxmox; no task id was "
                f"captured to track it", stream="stderr")
        raise
    ctx.log(f"proxmox task {upid}")
    ctx.progress(10)

    seen = 0
    deadline = asyncio.get_running_loop().time() + TASK_TIMEOUT_S
    ctx.progress(50)
    try:
        while True:
            status = await asyncio.to_thread(client.task_status, node, upid)
            rows = await asyncio.to_thread(client.task_log, node, upid, seen)
            for r in rows:
                ctx.log(str(r.get("t", "")))
                seen = max(seen, int(r.get("n", seen)))
            if status.get("status") != "running":
                break
            if asyncio.get_running_loop().time() > deadline:
                raise JobFailed(f"proxmox task {upid} still running after "
                                f"{TASK_TIMEOUT_S:.0f}s — giving up on the log, the "
                                f"task itself is untouched on the node")
            await asyncio.sleep(TASK_POLL_S)
    except asyncio.CancelledError:
        # The status/action POST already reached proxmox and is unaffected by a
        # local cancel — telling the user it was "canceled" without this line
        # would read as "nothing happened", which is false.
        ctx.log(f"canceled locally; proxmox task {upid} keeps running on {node}",
               stream="stderr")
        raise

    exitstatus = status.get("exitstatus")
    if exitstatus != "OK":
        # Fail closed: a stopped task with a missing/None exitstatus is an
        # unknown outcome, not a success, contra proxmox.py's own contract.
        reason = exitstatus if exitstatus else "no exitstatus reported"
        raise JobFailed(f"{action} failed: {reason}")

    ctx.progress(100)
    # Nudge every open tab to refetch rather than assert a status we have not
    # polled yet — the poller owns cached state (doc 04: Proxmox is the truth).
    app.state.bus.publish("resource", {"type": target_type, "id": target_id,
                                       "change": "lifecycle"})
    return {"upid": upid, "exitstatus": exitstatus, "node": node, "vmid": vmid}


def _register(target_type: str, action: str) -> None:
    async def run(ctx: JobContext, params: dict) -> dict:
        return await run_lifecycle(ctx, target_type, action, params)

    run.__name__ = f"{target_type}_{action}"
    HANDLERS[job_kind(target_type, action)] = run


for _verb in APP_ACTIONS:
    _register("app", _verb)
for _verb in VM_ACTIONS:
    _register("vm", _verb)
