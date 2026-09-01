"""Storage content job handlers.

Upload proxies the ISO twice — browser -> Proxploy (spooled to
`data_dir/uploads` by the route, never buffered in RAM) and Proxploy -> PVE —
so the host needs transient free disk equal to the file size and the upload
takes about twice as long as a direct PVE upload. The spool file is deleted by
the job runner (JobBackend._run's `finally`, keyed on the `spool_path` param)
on EVERY exit — success, PVE failure, timeout, cancellation, or a job cancelled
while queued — which is why this handler takes a path, not bytes.
"""
from __future__ import annotations

import asyncio

from proxploy.jobs import HANDLERS, JobContext, JobFailed
from proxploy.models import Host
from proxploy.services.hostclient import client_for_host
from proxploy.services.proxmox import ProxmoxError
from proxploy.services.pvetask import await_task


def _resolve(app, host_id: int, node: str | None):
    """Blocking: host_id -> (ProxmoxClient, node). Runs in a thread.

    `capability="lifecycle"`: uploading an ISO or deleting a volume needs
    Datastore.AllocateSpace, a node-infrastructure privilege on the lifecycle
    role, not monitoring's read-only set.
    """
    with app.state.sessionmaker() as db:
        host = db.get(Host, host_id)
        if host is None:
            raise JobFailed(f"host {host_id} not found")
        try:
            return (client_for_host(app, db, host, capability="lifecycle"),
                    (node or host.node_name or ""))
        except ProxmoxError as e:
            raise JobFailed(str(e)) from e


# Sending the bytes to the node is nearly all of the wall clock, and PVE's own
# task afterwards only moves the finished file into place. The send owns the
# bar up to here and await_task takes it from there, so the two never disagree
# about which direction progress moves.
UPLOAD_SEND_PCT = 90


async def run_upload(ctx: JobContext, params: dict) -> dict:
    app = ctx.backend.app
    host_id = int(params["host_id"])
    storage, content = params["storage"], params["content"]
    filename, path = params["filename"], params["spool_path"]
    client, node = await asyncio.to_thread(_resolve, app, host_id, params.get("node"))
    total = int(params.get("size_bytes") or 0)
    ctx.log(f"uploading {filename} ({total} bytes) to {storage} on {node}")
    loop = asyncio.get_running_loop()
    reported = 0

    def on_progress(sent: int) -> None:
        nonlocal reported
        if total <= 0:
            return
        pct = min(UPLOAD_SEND_PCT, sent * UPLOAD_SEND_PCT // total)
        if pct > reported:
            reported = pct
            loop.call_soon_threadsafe(ctx.progress, pct)

    upid = await asyncio.to_thread(client.storage_upload, node, storage,
                                   content, filename, path, on_progress)
    status = await await_task(ctx, client, node, upid,
                              start_pct=UPLOAD_SEND_PCT,
                              timeout_s=app.state.settings.pve_task_timeout_s)
    app.state.bus.publish("resource", {"type": "storage", "id": host_id,
                                       "change": "content"})
    return {"upid": upid, "exitstatus": status.get("exitstatus"), "node": node,
            "storage": storage, "volid": f"{storage}:{content}/{filename}"}


async def run_delete_volume(ctx: JobContext, params: dict) -> dict:
    app = ctx.backend.app
    host_id = int(params["host_id"])
    storage, volid = params["storage"], params["volid"]
    client, node = await asyncio.to_thread(_resolve, app, host_id, params.get("node"))
    ctx.log(f"deleting {volid} from {storage} on {node}")
    upid = await asyncio.to_thread(client.storage_delete_volume, node, storage, volid)
    exitstatus = "OK"
    if upid:
        exitstatus = (await await_task(
            ctx, client, node, upid,
            timeout_s=app.state.settings.pve_task_timeout_s)).get("exitstatus")
    else:
        # dir/lvm plugins delete inline and return no UPID: there is no task to
        # poll, and treating a missing UPID as a failure would fail every
        # successful ISO delete on local storage.
        ctx.log("deleted synchronously (no task id)")
        ctx.progress(100)
    app.state.bus.publish("resource", {"type": "storage", "id": host_id,
                                       "change": "content"})
    return {"upid": upid, "exitstatus": exitstatus, "node": node,
            "storage": storage, "volid": volid}


HANDLERS["storage.upload"] = run_upload
HANDLERS["storage.delete_volume"] = run_delete_volume
