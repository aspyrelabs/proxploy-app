"""Bodies are Markdown, and notifier.send_one marks them so; Apprise converts
per service: real HTML for email, blocks for Slack, plain text for ntfy and the
rest.
"""
from __future__ import annotations

from datetime import datetime


def human_duration(started: datetime | None, finished: datetime | None) -> str:
    """"2m 14s", not "134.203399s". Empty when either end is missing, which is
    a job that never started rather than one that took no time."""
    if not started or not finished:
        return ""
    total = int((finished - started).total_seconds())
    if total < 0:
        return ""
    if total < 60:
        return f"{total}s"
    minutes, seconds = divmod(total, 60)
    if minutes < 60:
        return f"{minutes}m {seconds}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m"


def compose(facts: list[tuple[str, str]], detail: str | None = None,
            link: str = "") -> str:
    """One notification body: the facts as a list, the reason, then the link.

    The title already carries what happened, so it is not repeated here. A fact
    with no value is dropped rather than printed empty.
    """
    lines = [f"- **{label}:** {value}" for label, value in facts if value]
    if detail:
        lines += ["", detail.strip()]
    if link:
        # Last, and only when there is somewhere real to go. services/links.py
        # returns "" rather than guessing a host, because a link to the wrong
        # installation is worse than none.
        lines += ["", f"[Open in Proxploy]({link})"]
    return "\n".join(lines)


def job_facts(*, job_id: int, target_name: str | None, target_type: str | None,
              duration: str, schedule_name: str | None) -> list[tuple[str, str]]:
    """The facts worth carrying about a finished job.

    `target_name` is captured at enqueue precisely so a destroy job can still
    name what it destroyed. The schedule name answers "did I do this, or did
    the machine?".
    """
    label = (target_type or "target").replace("_", " ").capitalize()
    return [
        (label, target_name or ""),
        ("Took", duration),
        ("Ran from", schedule_name or ""),
        ("Job", f"#{job_id}"),
    ]
