# backend/proxploy/services/storagejobs.py
"""Storage content job handlers (doc 05 §Storage, doc 01 §5 "Content browser").

Both handlers are the shape services/lifecycle.py established and Task 2
extracted: resolve in a thread, POST to Proxmox, hand the UPID to `await_task`.

The upload one carries one extra obligation. Proxmox's upload endpoint takes a
multipart body — there is no "fetch this URL yourself" variant — so an ISO is
transferred TWICE: browser -> Proxploy (spooled to `data_dir/uploads` by the
route, never buffered in RAM) and Proxploy -> PVE (read back here). The Proxploy
host therefore needs transient free disk equal to the file size for the life of
the job, and the upload takes about twice as long as a direct PVE upload. That
is the accepted cost of proxying it; what is not acceptable is holding the file
in memory, which is why the route streams and this handler takes a path rather
than bytes. The spool file is deleted in a `finally` on EVERY exit — success,
PVE failure, timeout, cancellation — because nothing else ever will.
"""
from __future__ import annotations

import asyncio
import contextlib
import os

from proxploy.jobs import HANDLERS, JobContext, JobFailed
from proxploy.models import Host
from proxploy.services.hostclient import client_for_host
from proxploy.services.proxmox import ProxmoxError
from proxploy.services.pvetask import await_task


def _resolve(app, host_id: int, node: str | None):
    """Blocking: host_id -> (ProxmoxClient, node). Runs in a thread."""
    with app.state.sessionmaker() as db:
        host = db.get(Host, host_id)
        if host is None:
            raise JobFailed(f"host {host_id} not found")
        try:
            return client_for_host(app, db, host), (node or host.node_name or "")
        except ProxmoxError as e:
            raise JobFailed(str(e)) from e


async def run_upload(ctx: JobContext, params: dict) -> dict:
    app = ctx.backend.app
    host_id = int(params["host_id"])
    storage, content = params["storage"], params["content"]
    filename, path = params["filename"], params["path"]
    try:
        client, node = await asyncio.to_thread(_resolve, app, host_id, params.get("node"))
        ctx.log(f"uploading {filename} ({params.get('size_bytes', 0)} bytes) "
                f"to {storage} on {node}")
        upid = await asyncio.to_thread(client.storage_upload, node, storage,
                                       content, filename, path)
        status = await await_task(ctx, client, node, upid,
                                  timeout_s=app.state.settings.pve_task_timeout_s)
        app.state.bus.publish("resource", {"type": "storage", "id": host_id,
                                           "change": "content"})
        return {"upid": upid, "exitstatus": status.get("exitstatus"), "node": node,
                "storage": storage, "volid": f"{storage}:{content}/{filename}"}
    finally:
        # The ONLY place this file is ever removed. Suppressed because a failure
        # to unlink must not turn a succeeded upload into a failed job — the
        # bytes are already on PVE by then.
        with contextlib.suppress(OSError):
            os.unlink(path)


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
        # dir/lvm plugins delete inline and return no UPID — there is no task to
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
