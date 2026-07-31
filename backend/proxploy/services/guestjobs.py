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
from proxploy.models import Host
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
