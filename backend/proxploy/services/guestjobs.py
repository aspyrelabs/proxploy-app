"""Guest- and node-shaped job handlers (doc 10 Phase 6).

Shared home for every Phase 6 handler that is not storage or backups:
`network.apply` lands here first; Tasks 10 and 11 append `vm.snapshot_*`,
`vm.create`, `vm.clone` and `vm.delete` to this same module rather than
starting new ones. Shape is services/lifecycle.py's: a blocking `_resolve` in
a thread, ctx.log/ctx.progress narration, the shared await_task poll loop,
module-bottom HANDLERS registration.

Registration is by import side effect — main.py's lifespan imports this module
with a `# noqa: F401`, and without that import none of these kinds exist.
"""
from __future__ import annotations

import asyncio

from proxploy.jobs import HANDLERS, JobContext, JobFailed
from proxploy.models import Host, Vm
from proxploy.services.hostclient import client_for_host
from proxploy.services.pvetask import await_task


def _resolve_host(app, host_id: int):
    """Blocking: host_id -> (ProxmoxClient, host name). Runs in a thread."""
    with app.state.sessionmaker() as db:
        host = db.get(Host, host_id)
        if host is None:
            raise JobFailed(f"host {host_id} not found")
        return client_for_host(app, db, host), host.name


async def run_network_apply(ctx: JobContext, params: dict) -> dict:
    """Promote /etc/network/interfaces.new on one node (PUT /nodes/{node}/network).

    The confirmation gate lives at the API layer (api/network.py::apply_network);
    by the time this runs the operator has already typed the node name back.
    A failure here can mean the node is unreachable rather than that the apply
    failed — await_task raising on a lost connection is the honest outcome
    either way, and the transcript keeps the UPID so an operator at the console
    can look the task up locally.
    """
    app = ctx.backend.app
    host_id = int(params["host_id"])
    node = str(params["node"])
    client, host_name = await asyncio.to_thread(_resolve_host, app, host_id)
    ctx.log(f"applying staged network config on node {node} ({host_name})")
    ctx.progress(5)
    upid = await asyncio.to_thread(client.network_apply, node)
    status = await await_task(ctx, client, node, upid, start_pct=10, end_pct=100)
    app.state.bus.publish("resource", {"type": "network", "id": host_id,
                                       "change": "applied"})
    return {"upid": upid, "exitstatus": status.get("exitstatus"),
            "node": node, "host_id": host_id}


HANDLERS["network.apply"] = run_network_apply


def _vm_target(app, vm_id: int):
    """Blocking: vms.id -> (client, node, vmid, name, host_id). Runs in a thread.

    Same shape as services/lifecycle.py::_resolve, minus the app/CT branch —
    everything in this module is qemu-only (doc 05 puts snapshots, create and
    clone under /vms).
    """
    with app.state.sessionmaker() as db:
        v = db.get(Vm, vm_id)
        if v is None:
            raise JobFailed(f"vm {vm_id} not found")
        host = db.get(Host, v.host_id)
        if host is None:
            raise JobFailed(f"host {v.host_id} not found")
        return (client_for_host(app, db, host), host.node_name or "",
                int(v.vmid), v.name or f"VM {v.vmid}", host.id)


async def snapshot_create_job(ctx: JobContext, params: dict) -> dict:
    """`vm.snapshot_create` — take a snapshot, optionally with RAM."""
    app = ctx.backend.app
    vm_id = int(params["vm_id"])
    name = params["name"]
    client, node, vmid, vm_name, _host_id = await asyncio.to_thread(
        _vm_target, app, vm_id)
    vmstate = bool(params.get("vmstate"))
    ctx.log(f"snapshot {name!r} of {vm_name} (qemu {vmid}) on {node}"
            f"{' including RAM' if vmstate else ''}")
    upid = await asyncio.to_thread(client.snapshot_create, "qemu", node, vmid,
                                   name, params.get("description"), vmstate)
    status = await await_task(ctx, client, node, upid)
    app.state.bus.publish("resource", {"type": "vm", "id": vm_id,
                                       "change": "snapshot"})
    return {"upid": upid, "exitstatus": status.get("exitstatus"), "name": name,
            "vmid": vmid, "vmstate": vmstate}


async def snapshot_rollback_job(ctx: JobContext, params: dict) -> dict:
    """`vm.snapshot_rollback` — discard everything since the snapshot.

    The route already took the typed confirmation. PVE refuses a rollback of a
    running VM unless the snapshot carries vmstate, and that refusal is surfaced
    verbatim rather than pre-checked here: the guest's cached status can be up
    to one poll cycle stale, so a local check would produce a second, less
    accurate answer than the one Proxmox gives.
    """
    app = ctx.backend.app
    vm_id = int(params["vm_id"])
    name = params["name"]
    client, node, vmid, vm_name, _host_id = await asyncio.to_thread(
        _vm_target, app, vm_id)
    ctx.log(f"rolling {vm_name} (qemu {vmid}) back to snapshot {name!r} on {node}")
    upid = await asyncio.to_thread(client.snapshot_rollback, "qemu", node, vmid,
                                   name)
    status = await await_task(ctx, client, node, upid)
    app.state.bus.publish("resource", {"type": "vm", "id": vm_id,
                                       "change": "rollback"})
    return {"upid": upid, "exitstatus": status.get("exitstatus"), "name": name,
            "vmid": vmid}


async def snapshot_delete_job(ctx: JobContext, params: dict) -> dict:
    """`vm.snapshot_delete` — remove one snapshot; the guest is untouched."""
    app = ctx.backend.app
    vm_id = int(params["vm_id"])
    name = params["name"]
    client, node, vmid, vm_name, _host_id = await asyncio.to_thread(
        _vm_target, app, vm_id)
    ctx.log(f"deleting snapshot {name!r} of {vm_name} (qemu {vmid}) on {node}")
    upid = await asyncio.to_thread(client.snapshot_delete, "qemu", node, vmid,
                                   name)
    status = await await_task(ctx, client, node, upid)
    app.state.bus.publish("resource", {"type": "vm", "id": vm_id,
                                       "change": "snapshot"})
    return {"upid": upid, "exitstatus": status.get("exitstatus"), "name": name,
            "vmid": vmid}


HANDLERS["vm.snapshot_create"] = snapshot_create_job
HANDLERS["vm.snapshot_rollback"] = snapshot_rollback_job
HANDLERS["vm.snapshot_delete"] = snapshot_delete_job
