"""Whether a password is good enough to accept.

A length floor and the four character classes, then zxcvbn for everything
that a composition rule cannot see: common passwords, keyboard runs, dates,
names, l33t spellings, and this product's own words. The frontend runs the
same library against the same thresholds, so the meter and the server agree.
"""
from __future__ import annotations

import re

from zxcvbn import zxcvbn

MIN_LENGTH = 12
MIN_SCORE = 3

CLASSES: tuple[tuple[str, str], ...] = (
    ("a lower case letter", r"[a-z]"),
    ("an upper case letter", r"[A-Z]"),
    ("a digit", r"\d"),
    ("a symbol", r"[^A-Za-z0-9]"),
)

_PRODUCT_WORDS = ["proxploy", "proxmox"]


def _listed(items: list[str]) -> str:
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]


def refuse(password: str, *, email: str | None = None) -> str | None:
    """The reason this password cannot be used, or None if it can."""
    if len(password) < MIN_LENGTH:
        return f"Use at least {MIN_LENGTH} characters."
    missing = [name for name, pattern in CLASSES if not re.search(pattern, password)]
    if missing:
        return "Add " + _listed(missing) + "."
    inputs = list(_PRODUCT_WORDS)
    if email:
        inputs += [email, email.split("@", 1)[0]]
    result = zxcvbn(password, user_inputs=inputs)
    if result["score"] >= MIN_SCORE:
        return None
    feedback = result["feedback"]
    return (feedback["warning"] or (feedback["suggestions"] or [""])[0]
            or "That password is guessed too easily. Choose another.")
