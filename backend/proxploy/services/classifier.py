"""Install-feasibility classifier (doc 01 §3, doc 04 `catalog_entries`,
docs/notes/phase-4-spike.md). Mechanical, not a guess: every
community-scripts install script runs under `catch_errors()`'s
`set -Ee -o pipefail` + `trap ERR` (misc/error_handler.func), so a bare
`read`/`whiptail`/`dialog` prompt returns a non-zero exit on EOF and
hard-aborts the whole install rather than defaulting — confirmed
empirically in the spike, not assumed. A prompt only counts as safe if it's
guarded: either an env-var short-circuit within a few lines above it, or
the read itself falls back via `||` (the jellyfin/plex hwaccel pattern)."""
from __future__ import annotations

import re

BUILD_CONTAINER_RE = re.compile(r"^\s*build_container\b", re.MULTILINE)
PROMPT_RE = re.compile(r"\bread\b[^\n]*-[a-zA-Z]*p\b|\bwhiptail\b|\bdialog\b")
GUARD_RE = re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]*:-|-[nz]\s+\"\$\{")

UNSUPPORTED_MULTI_CT = "multi-CT / docker-compose pattern"
UNSUPPORTED_INTERACTIVE = "install script requires interactive input, no non-interactive entrypoint"


def classify_install_feasibility(ct_script: str, install_script: str) -> tuple[bool, str | None]:
    if len(BUILD_CONTAINER_RE.findall(ct_script)) != 1:
        return False, UNSUPPORTED_MULTI_CT

    lines = install_script.splitlines()
    for i, line in enumerate(lines):
        if not PROMPT_RE.search(line):
            continue
        if "||" in line:  # e.g. `read ... || nvidia_reply=""`
            continue
        preceding = "\n".join(lines[max(0, i - 3):i])
        if GUARD_RE.search(preceding):
            continue
        return False, UNSUPPORTED_INTERACTIVE

    return True, None
