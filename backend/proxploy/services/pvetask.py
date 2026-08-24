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
from collections.abc import Callable

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
                     start_pct: int = 10, end_pct: int = 100,
                     report_progress: bool = True,
                     pct_from: Callable[[str], int | None] | None = None) -> dict:
    """Log the UPID, poll it to completion, stream its task log into the job.

    Returns the final task-status dict (`{status, exitstatus, ...}`). Raises
    JobFailed on timeout or on any exitstatus other than "OK".

    `report_progress=False` skips both ctx.progress() calls below for a caller
    with no honest percentage to report (services/guestjobs.py::run_host_power:
    a node reboot/power-off task finishing tells you Proxmox accepted the
    command, not that the node has actually finished rebooting or coming back
    up, so a percentage here would claim certainty the job does not have).
    The polling, logging and exitstatus handling stay identical either way;
    every other caller keeps reporting by default.

    `pct_from` reads a real percentage out of the task log PVE is already
    streaming here, and is the only way this loop can report anything between
    start_pct and the end: /tasks/{upid}/status carries no percentage at all,
    so without it a 40-minute vzdump sat on 10% until it finished. Return None
    for a line that says nothing about progress; the returned 0..100 is scaled
    into the caller's [start_pct, end_pct] band. Never reported backwards, so a
    per-guest counter that restarts cannot make the bar go left.
    """
    ctx.log(f"proxmox task {upid}")
    if report_progress:
        ctx.progress(start_pct)

    seen = 0
    reported = start_pct
    deadline = asyncio.get_running_loop().time() + timeout_s
    try:
        while True:
            status = await asyncio.to_thread(client.task_status, node, upid)
            rows = await asyncio.to_thread(client.task_log, node, upid, seen)
            for r in rows:
                line = str(r.get("t", ""))
                ctx.log(line)
                seen = max(seen, int(r.get("n", seen)))
                if pct_from is None or not report_progress:
                    continue
                p = pct_from(line)
                if p is None:
                    continue
                scaled = start_pct + (end_pct - start_pct) * max(0, min(100, p)) // 100
                if scaled > reported:
                    reported = scaled
                    ctx.progress(reported)
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
    # Proxmox reports three shapes here: "OK", "WARNINGS: <n>" for a task that
    # COMPLETED but logged warnings, and an error string for a real failure.
    # Only the third is a failure; PVE's own UI shows the second as finished.
    # Treating it as failure marked successful work red, and for the handlers
    # that clean up after a JobFailed it undid work that had actually landed.
    # Caught on PVE 9.2.6 (2026-08-10) by a `pct reboot` that returned
    # "WARNINGS: 1" and rebooted the container perfectly well.
    if exitstatus and exitstatus.startswith("WARNINGS:"):
        ctx.log(f"proxmox task {upid} finished with {exitstatus.lower()}; "
                f"see the task log above", stream="stderr")
    elif exitstatus != "OK":
        # Fail closed: a stopped task with a missing/None exitstatus is an
        # unknown outcome, not a success, contra proxmox.py's own contract.
        reason = exitstatus if exitstatus else "no exitstatus reported"
        raise JobFailed(f"proxmox task {upid} failed: {reason}")

    if report_progress:
        ctx.progress(end_pct)
    return status
