"""Guest- and node-shaped job handlers (doc 10 Phase 6).

Shared home for every Phase 6 handler that is not storage or backups:
`network.apply` lands here first; Tasks 10 and 11 append `vm.snapshot_*`,
`vm.create`, `vm.clone` and `vm.delete` to this same module rather than
starting new ones. Shape is services/lifecycle.py's: a blocking `_resolve` in
a thread, ctx.log/ctx.progress narration, the shared await_task poll loop,
module-bottom HANDLERS registration.

Registration is by import side effect, main.py's lifespan imports this module
with a `# noqa: F401`, and without that import none of these kinds exist.
"""
from __future__ import annotations

import asyncio

from proxploy.jobs import HANDLERS, JobContext, JobFailed
from proxploy.models import Host, Vm
from proxploy.services.hostclient import client_for_host, guest_node
from proxploy.services.proxmox import ProxmoxError
from proxploy.services.pvetask import await_task


def _resolve_host(app, host_id: int, capability: str = "monitoring"):
    """Blocking: host_id -> (ProxmoxClient, host name). Runs in a thread.

    Shared by `run_network_apply` (needs "lifecycle": staging/applying a
    bridge is Sys.Modify) and `run_host_power` (deliberately left at the
    "monitoring" default -- node power is its own capability dimension,
    landing separately per per-capability-tokens-plan.md §3 footnote 3;
    changing what it resolves to is out of scope for this sweep).
    """
    with app.state.sessionmaker() as db:
        host = db.get(Host, host_id)
        if host is None:
            raise JobFailed(f"host {host_id} not found")
        try:
            return client_for_host(app, db, host, capability=capability), host.name
        except ProxmoxError as e:
            # Same sentence as lifecycle.py::_resolve: a job reports a missing
            # credential as a failed job, never as a 502.
            raise JobFailed(str(e)) from e


async def run_network_apply(ctx: JobContext, params: dict) -> dict:
    """Promote /etc/network/interfaces.new on one node (PUT /nodes/{node}/network).

    The confirmation gate lives at the API layer (api/network.py::apply_network);
    by the time this runs the operator has already typed the node name back.
    A failure here can mean the node is unreachable rather than that the apply
    failed, await_task raising on a lost connection is the honest outcome
    either way, and the transcript keeps the UPID so an operator at the console
    can look the task up locally.
    """
    app = ctx.backend.app
    host_id = int(params["host_id"])
    node = str(params["node"])
    client, host_name = await asyncio.to_thread(
        _resolve_host, app, host_id, "lifecycle")
    ctx.log(f"applying staged network config on node {node} ({host_name})")
    # Said BEFORE the call, so the transcript carries it even if this job never
    # gets to write another line. On real hardware an apply that moved vmbr0's
    # address returned a UPID in 0.1 seconds and the node then vanished for 193
    # seconds, and the very same UPID reported TASK OK once it returned (doc 12
    # check 8). So a failure below is genuinely ambiguous, and the transcript has
    # to say which readings are possible rather than leaving the operator to
    # assume the safest one.
    ctx.log("if this change costs the node its own network, this job will report "
            "a failure it cannot distinguish from a real one: the apply may have "
            "succeeded. The task id above is readable on the node itself.")
    ctx.progress(5)
    upid = await asyncio.to_thread(client.network_apply, node)
    status = await await_task(ctx, client, node, upid, start_pct=10, end_pct=100,
                              timeout_s=app.state.settings.pve_task_timeout_s)
    app.state.bus.publish("resource", {"type": "network", "id": host_id,
                                       "change": "applied"})
    return {"upid": upid, "exitstatus": status.get("exitstatus"),
            "node": node, "host_id": host_id}


HANDLERS["network.apply"] = run_network_apply


async def run_host_power(ctx: JobContext, params: dict) -> dict:
    """Reboot or power off a Proxmox NODE (host actions menu, doc 02 §9,
    doc 08 §1 and §9 row 14).

    The typed-confirmation gate, including the self-guard warning that the
    target can be the node Proxploy itself runs on, lives entirely at the API
    layer (api/hosts.py::power_node); by the time this job runs the operator
    has already typed the node's name back.

    If the node this runs on turns out to be the one Proxploy itself is on,
    the job engine dies mid-poll along with everything else on that machine:
    there is no in-process way to catch that, the whole process disappears
    with no chance to write a terminal row. Nothing here needs to handle it.
    JobBackend.sweep_orphans already marks any job still `queued`/`running`
    as `interrupted` on the next boot, the same as an ordinary ungraceful
    restart catches any other job mid-flight; a row stuck showing `running`
    forever would be its own kind of lie, and this needs no special case to
    avoid that, the existing sweep already covers it.

    No percentage progress is reported (`report_progress=False`): the only
    thing this job can measure is whether Proxmox accepted the command and
    the issuing task finished, which usually happens in well under a second,
    long before the node itself has actually gone anywhere. That says
    nothing about whether the node has finished rebooting or come back up,
    so reporting a percentage (even a 10 -> 100 jump) would claim more
    certainty than this job actually has.
    """
    app = ctx.backend.app
    host_id = int(params["host_id"])
    node = str(params["node"])
    command = str(params["command"])
    # Deliberately the "monitoring" default, not "lifecycle": node power is
    # its own capability dimension and does not exist as one of the four
    # `kind="api_token:<capability>"` rows this sweep encodes (see
    # _resolve_host's docstring). Unchanged behaviour, out of scope here.
    client, host_name = await asyncio.to_thread(_resolve_host, app, host_id)
    verb = "rebooting" if command == "reboot" else "powering off"
    ctx.log(f"{verb} node {node} ({host_name})")
    upid = await asyncio.to_thread(client.node_power, node, command)
    # Proxmox answers this one with null, not a UPID: node_cmd reboots or
    # shuts the node down inside the request handler rather than forking a
    # task (see ProxmoxClient.node_power). Feeding that None to await_task
    # asked the node for the log of a task called "None", so every real power
    # off ended as a failed job reading "task log failed for None: 400 Bad
    # Request" while the node powered off perfectly well behind it. Only
    # follow a task when Proxmox actually gave us one.
    exitstatus = None
    if upid:
        status = await await_task(ctx, client, node, upid, report_progress=False,
                                  timeout_s=app.state.settings.pve_task_timeout_s)
        exitstatus = status.get("exitstatus")
    else:
        ctx.log(f"proxmox ran the {command} on {node} directly, with no task "
                f"to follow")
    ctx.log(f"{node} accepted the {command} command; whether it actually "
            f"{'reboots' if command == 'reboot' else 'powers off'} is not "
            f"tracked here")
    app.state.bus.publish("resource", {"type": "host", "id": host_id, "change": "power"})
    return {"upid": upid, "exitstatus": exitstatus, "node": node,
            "host_id": host_id, "command": command}


HANDLERS["host.reboot"] = run_host_power
HANDLERS["host.shutdown"] = run_host_power


def _vm_target(app, vm_id: int):
    """Blocking: vms.id -> (client, node, vmid, name, host_id). Runs in a thread.

    Same shape as services/lifecycle.py::_resolve, minus the app/CT branch; 
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
        try:
            client = client_for_host(app, db, host, capability="lifecycle")
        except ProxmoxError as e:
            raise JobFailed(str(e)) from e
        # The GUEST's node, not the host's. On a cluster every polled host
        # mirrors every VM (/cluster/resources answers for the whole cluster),
        # so host.node_name is the wrong node for every row but the owning
        # one, and PVE answered each action with `500 Configuration file
        # 'nodes/<other>/qemu-server/<id>.conf' does not exist` (doc 12 check
        # 18). Falls back to the host's node for a row not polled since
        # vms.node_name existed, which is exactly the old behaviour.
        return (client, guest_node(host, v),
                int(v.vmid), v.name or f"VM {v.vmid}", host.id)


async def snapshot_create_job(ctx: JobContext, params: dict) -> dict:
    """`vm.snapshot_create`, take a snapshot, optionally with RAM."""
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
    status = await await_task(ctx, client, node, upid,
                              timeout_s=app.state.settings.pve_task_timeout_s)
    app.state.bus.publish("resource", {"type": "vm", "id": vm_id,
                                       "change": "snapshot"})
    return {"upid": upid, "exitstatus": status.get("exitstatus"), "name": name,
            "vmid": vmid, "vmstate": vmstate}


async def snapshot_rollback_job(ctx: JobContext, params: dict) -> dict:
    """`vm.snapshot_rollback`, discard everything since the snapshot.

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
    status = await await_task(ctx, client, node, upid,
                              timeout_s=app.state.settings.pve_task_timeout_s)
    app.state.bus.publish("resource", {"type": "vm", "id": vm_id,
                                       "change": "rollback"})
    return {"upid": upid, "exitstatus": status.get("exitstatus"), "name": name,
            "vmid": vmid}


async def snapshot_delete_job(ctx: JobContext, params: dict) -> dict:
    """`vm.snapshot_delete`, remove one snapshot; the guest is untouched."""
    app = ctx.backend.app
    vm_id = int(params["vm_id"])
    name = params["name"]
    client, node, vmid, vm_name, _host_id = await asyncio.to_thread(
        _vm_target, app, vm_id)
    ctx.log(f"deleting snapshot {name!r} of {vm_name} (qemu {vmid}) on {node}")
    upid = await asyncio.to_thread(client.snapshot_delete, "qemu", node, vmid,
                                   name)
    status = await await_task(ctx, client, node, upid,
                              timeout_s=app.state.settings.pve_task_timeout_s)
    app.state.bus.publish("resource", {"type": "vm", "id": vm_id,
                                       "change": "snapshot"})
    return {"upid": upid, "exitstatus": status.get("exitstatus"), "name": name,
            "vmid": vmid}


HANDLERS["vm.snapshot_create"] = snapshot_create_job
HANDLERS["vm.snapshot_rollback"] = snapshot_rollback_job
HANDLERS["vm.snapshot_delete"] = snapshot_delete_job


def _host_client(app, host_id: int):
    """Blocking: hosts.id -> (client, node, host name). Create has no guest row
    to resolve from yet, so it resolves the host directly."""
    with app.state.sessionmaker() as db:
        host = db.get(Host, host_id)
        if host is None:
            raise JobFailed(f"host {host_id} not found")
        try:
            return (client_for_host(app, db, host, capability="lifecycle"),
                    host.node_name or "", host.name)
        except ProxmoxError as e:
            raise JobFailed(str(e)) from e


def _create_params(params: dict) -> dict:
    """The one place Proxploy's create spec becomes PVE's qemu parameters.

    Deliberately opinionated defaults rather than a passthrough of arbitrary
    PVE keys: virtio-scsi-single + a virtio NIC is what the Proxmox UI's own
    defaults produce, and a create wizard that lets a caller post raw qemu
    config would be an unvalidated write to the hypervisor.
    """
    iso = params.get("iso")

    def _net0(p: dict) -> str:
        # PVE spells a VLAN on a guest NIC as `,tag=N` inside the netN string
        # (same grammar services/netconfig.py round-trips for edits). Absent or
        # falsy tag means untagged: never emit `tag=` with an empty value.
        spec = f"virtio,bridge={p.get('bridge') or 'vmbr0'}"
        tag = p.get("vlan_tag")
        return f"{spec},tag={int(tag)}" if tag else spec

    call = {
        "vmid": int(params["vmid"]),
        "name": params["name"],
        "cores": int(params["cores"]),
        "sockets": 1,
        "memory": int(params["memory_mb"]),
        "ostype": params.get("ostype") or "l26",
        "scsihw": "virtio-scsi-single",
        "scsi0": f"{params['storage']}:{int(params['disk_gb'])}",
        "net0": _net0(params),
        "boot": "order=scsi0;ide2" if iso else "order=scsi0",
    }
    if iso:
        call["ide2"] = f"{iso},media=cdrom"
    if params.get("start"):
        call["start"] = 1
    return call


async def create_vm(ctx: JobContext, params: dict) -> dict:
    """`vm.create`, post the spec, poll the task, nudge the UI.

    No `Vm` row is written here. `vms` is the poller's droppable mirror (doc 04:
    Proxmox is the truth) and writing one from this side would create a row the
    next poll cycle either confirms or deletes, a second, worse source of
    truth. The resource publish below is the same nudge run_lifecycle emits, so
    an open tab refetches instead of waiting out the 30 s interval.

    That nudge on its own bought nothing, though: the refetch it triggers reads
    the mirror, which the poller has not refreshed yet, so the tab got the same
    stale list back and the VM still took a poll interval to appear. The
    poller.wake() below is the missing half. It is measured as sufficient: the
    guest is in /cluster/resources ~18 ms after the task finishes (see
    Poller.wake), so the cycle it asks for actually finds it, and that cycle
    publishes its own vm/list event once the mirror is fresh.
    """
    app = ctx.backend.app
    host_id = int(params["host_id"])
    client, host_node, host_name = await asyncio.to_thread(_host_client, app,
                                                           host_id)
    node = params.get("node") or host_node
    call = _create_params(params)
    ctx.log(f"creating VM {call['vmid']} ({call['name']}) on {host_name}/{node}: "
            f"{call['cores']} cores, {call['memory']} MiB, {call['scsi0']}")
    # ponytail: no retry on a taken vmid. PVE is the authority on uniqueness and
    # rejects a duplicate outright; retrying with the next free id would race a
    # second orchestrator indefinitely and silently create a guest under an id
    # the caller never asked for. The error is surfaced verbatim instead.
    upid = await asyncio.to_thread(client.vm_create, node, call)
    status = await await_task(ctx, client, node, upid,
                              timeout_s=app.state.settings.pve_task_timeout_s)
    app.state.poller.wake(host_id)
    app.state.bus.publish("resource", {"type": "vm", "id": None,
                                       "change": "created"})
    return {"upid": upid, "exitstatus": status.get("exitstatus"),
            "vmid": call["vmid"], "name": call["name"], "node": node}


HANDLERS["vm.create"] = create_vm


async def clone_vm(ctx: JobContext, params: dict) -> dict:
    """`vm.clone`, full or linked, per the caller's `full` flag.

    `full` is passed through untouched. PVE allows `full=0` (a linked clone)
    only from a template, and Proxploy has no way to know which VMs are
    templates, the `vms` table has no `template` column and the poller does not
    read `/cluster/resources`'s `template` field, so PVE's own rejection is the
    answer the caller gets, verbatim, instead of a guess made here.
    """
    app = ctx.backend.app
    vm_id = int(params["vm_id"])
    client, node, vmid, vm_name, host_id = await asyncio.to_thread(
        _vm_target, app, vm_id)
    call: dict = {"newid": int(params["newid"]), "full": 1 if params.get("full") else 0}
    for key in ("name", "target", "storage"):
        if params.get(key):
            call[key] = params[key]
    ctx.log(f"{'full' if call['full'] else 'linked'} clone of {vm_name} "
            f"(qemu {vmid}) on {node} -> {call['newid']}")
    upid = await asyncio.to_thread(client.vm_clone, node, vmid, call)
    status = await await_task(ctx, client, node, upid,
                              timeout_s=app.state.settings.pve_task_timeout_s)
    # Same reason as create_vm's wake: a clone is a create as far as the mirror
    # is concerned, and speeding up only one of them means the next report is
    # about the other.
    app.state.poller.wake(host_id)
    app.state.bus.publish("resource", {"type": "vm", "id": None,
                                       "change": "created"})
    return {"upid": upid, "exitstatus": status.get("exitstatus"),
            "newid": call["newid"], "source_vmid": vmid, "full": bool(call["full"])}


async def delete_vm(ctx: JobContext, params: dict) -> dict:
    """`vm.delete`, destroy the guest and its disks.

    The route already required owner role, a typed name, a non-running guest and
    a selfguard pass. As with create, the `vms` row is left to the poller to
    drop: deleting it here would beat the poller to a state Proxmox has not
    confirmed yet.

    A destroy needs no more than the wake either, and specifically no targeted
    row deletion from this side. Unlike apps, `vms` has no missing_since grace
    period (see the sweep in pollers/__init__.py: "a trustworthy cycle still
    deletes at once"), so the very next cycle drops the row, and the guest is
    measured out of /cluster/resources 27 to 39 ms after the destroy task
    finishes. `_absence_is_trustworthy` is untouched and still decides.
    """
    app = ctx.backend.app
    vm_id = int(params["vm_id"])
    client, node, vmid, vm_name, host_id = await asyncio.to_thread(
        _vm_target, app, vm_id)
    ctx.log(f"destroying {vm_name} (qemu {vmid}) on {node}")
    upid = await asyncio.to_thread(client.guest_delete, "qemu", node, vmid)
    status = await await_task(ctx, client, node, upid,
                              timeout_s=app.state.settings.pve_task_timeout_s)
    app.state.poller.wake(host_id)
    app.state.bus.publish("resource", {"type": "vm", "id": None,
                                       "change": "deleted"})
    return {"upid": upid, "exitstatus": status.get("exitstatus"), "vmid": vmid,
            "name": vm_name}


HANDLERS["vm.clone"] = clone_vm
HANDLERS["vm.delete"] = delete_vm
