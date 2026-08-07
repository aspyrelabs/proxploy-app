"""The shared UPID poll-and-drain loop (doc 02 §3, doc 03).

Every mutating Proxmox call returns a UPID and then has to be watched: poll
/nodes/{node}/tasks/{upid}/status, drain /log into job_events, fail closed on
anything that is not exitstatus "OK". services/lifecycle.py proved that shape
in Phase 3; Phase 6 adds twelve more handlers that need exactly it, so it lives
here once instead of thirteen times.

Both the cancellation breadcrumb and the fail-closed exitstatus check are
carried over verbatim; they are the two pieces a re-derivation gets wrong:
a cancelled job must never imply the proxmox-side task was undone, and a
stopped task with a missing exitstatus is an unknown outcome, not a success.
"""
from __future__ import annotations

import asyncio

from proxploy.jobs import JobContext, JobFailed
from proxploy.services.proxmox import ProxmoxClient

TASK_POLL_S = 1.0
# ponytail: flat wall-clock ceiling per task. A slow shutdown or a 40 GB
# restore that genuinely needs longer belongs to a per-kind timeout table,
# which is worth building when a real workload proves one operation needs it.
# Callers that already know they are slow pass their own timeout_s (Phase 6's
# handlers pass settings.pve_task_timeout_s).
TASK_TIMEOUT_S = 300.0


async def await_task(ctx: JobContext, client: ProxmoxClient, node: str, upid: str, *,
                     timeout_s: float = TASK_TIMEOUT_S, poll_s: float = TASK_POLL_S,
                     start_pct: int = 10, end_pct: int = 100) -> dict:
    """Log the UPID, poll it to completion, stream its task log into the job.

    Returns the final task-status dict (`{status, exitstatus, ...}`). Raises
    JobFailed on timeout or on any exitstatus other than "OK".
    """
    ctx.log(f"proxmox task {upid}")
    ctx.progress(start_pct)

    seen = 0
    deadline = asyncio.get_running_loop().time() + timeout_s
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
                                f"{timeout_s:.0f}s, giving up on the log, the "
                                f"task itself is untouched on the node")
            await asyncio.sleep(poll_s)
    except asyncio.CancelledError:
        # The POST already reached proxmox and is unaffected by a local cancel, 
        # telling the user it was "canceled" without this line would read as
        # "nothing happened", which is false.
        ctx.log(f"canceled locally; proxmox task {upid} keeps running on {node}",
                stream="stderr")
        raise

    exitstatus = status.get("exitstatus")
    if exitstatus != "OK":
        # Fail closed: a stopped task with a missing/None exitstatus is an
        # unknown outcome, not a success, contra proxmox.py's own contract.
        reason = exitstatus if exitstatus else "no exitstatus reported"
        raise JobFailed(f"proxmox task {upid} failed: {reason}")

    ctx.progress(end_pct)
    return status
