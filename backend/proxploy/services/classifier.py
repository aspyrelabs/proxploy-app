"""Install-feasibility classifier (doc 01 §3, doc 04 `catalog_entries`).
Mechanical, not a guess: community-scripts install scripts run under `set -Ee
-o pipefail` + `trap ERR`, so a bare `read`/`whiptail`/`dialog` prompt
hard-aborts the whole install. A prompt is safe only when guarded: an env-var
short-circuit a few lines above it, or the read itself falls back via `||`.
"""
from __future__ import annotations

import re

BUILD_CONTAINER_RE = re.compile(r"^\s*build_container\b", re.MULTILINE)

# Any `read` is a potential prompt, not just `read -p`: a bare `read ANSWER`
# or a `read -s PASS` blocks on stdin exactly the same way, and under closed
# stdin + `set -Ee` it aborts the install just as hard.
# Anchored to command position (line start or after a shell separator) so a
# path or package name that merely ends in "read" isn't mistaken for one.
READ_RE = re.compile(r"(?:^|[;&|]|\b(?:then|do|else)\b)\s*read\b")
# ...except when it's plainly not reading from a terminal: a loop consuming a
# stream (`while read line`, `while IFS= read -r x`), any redirect or herestring
# (`read x < file`, `read x <<< "$s"`), a pipe (`… | read x`), or a non-stdin fd
# (`read -u 3 x`). Checked against the line with quoted strings removed, so a
# `<` inside prompt text (`<y/N>`) is not mistaken for a redirect. `while`/
# `until` must precede the `read` on the line: a `for` loop doesn't consume
# stdin, and a genuine prompt inside a loop body must still be flagged.
NOT_A_PROMPT_RE = re.compile(
    r"\b(?:while|until)\s+[^;]*\bread\b|<|\|\s*read\b|\bread\s+(?:-\w+\s+)*-\w*u\b")
WHIPTAIL_RE = re.compile(r"\bwhiptail\b|\bdialog\b")

# A guard is an env-var default/emptiness test (`${X:-…}`, `[[ -z "$X" ]]`).
GUARD_LINE_RE = re.compile(r"\$\{[A-Za-z_]\w*:[-=?]|-[nz]\s+\"?\$")
GUARD_VAR_RE = re.compile(r"\$\{?([A-Za-z_]\w*)")
IDENT_RE = re.compile(r"[A-Za-z_]\w*")

# A ct script that delegates its in-container step to tools/addon/<slug>.sh
# instead of shipping install/<slug>-install.sh. Anchored on the real path
# structure and a captured slug, NOT on the word "addon" appearing somewhere:
# these scripts print "has been migrated to an addon script" in a msg_warn, so
# a loose match would fire on prose, and the captured slug is what gets
# fetched. The character class deliberately excludes "/" so the capture cannot
# walk out of tools/addon/.
ADDON_DELEGATION_RE = re.compile(r"tools/addon/([A-Za-z0-9][A-Za-z0-9._-]*)\.sh\b")

UNSUPPORTED_MULTI_CT = "multi-CT / docker-compose pattern"
# An addon-delegating ct script is ALWAYS unsupported, whatever its addon
# script contains. Not a judgement about the addon script's content: a
# judgement about what `build_container` actually runs. See the long note on
# `addon_delegation_slug` and services/catalog.py::ensure_classified.
UNSUPPORTED_ADDON_DELEGATED = (
    "no install script upstream; it installs via an addon script "
    "run inside the container")
UNSUPPORTED_INTERACTIVE = "install script requires interactive input, no non-interactive entrypoint"


def addon_delegation_slug(ct_script: str) -> str | None:
    """The addon slug a ct script delegates its in-container step to, or None.

    Returns None unless unambiguous: exactly one `build_container` and exactly
    one distinct `tools/addon/<slug>.sh` capture. Read from script content, not
    a fixed slug list (an allowlist already missed `runtipi` once).

    An addon-delegating script is NOT installable, full stop: `build_container`
    installs via `curl .../install/${var_install}.sh`, which 404s for these
    apps (curl's 56 is swallowed, `bash -c ""` exits 0), so upstream builds an
    EMPTY container and reports success. The verdict is fixed at the call site
    (catalog.py::ensure_classified), not derived from the addon script.
    """
    if len(BUILD_CONTAINER_RE.findall(ct_script)) != 1:
        return None
    slugs = set(ADDON_DELEGATION_RE.findall(ct_script))
    if len(slugs) != 1:
        return None
    return slugs.pop()


def _unquoted(line: str) -> str:
    """Line with quoted strings and trailing comments stripped."""
    return re.sub(r'"[^"]*"|\'[^\']*\'', "", line).split("#", 1)[0]


def _read_targets(bare: str) -> set[str]:
    """Variable names a `read` assigns into (lowercased). Flags and their
    arguments are dropped; the `-p` prompt text is already gone with the
    quotes."""
    _, _, after = bare.partition("read")
    return {t.lower() for t in after.split() if IDENT_RE.fullmatch(t)}


def _is_guarded(preceding: list[str], targets: set[str]) -> bool:
    """True if one of the preceding lines actually guards THIS prompt.

    Requires the guard to name a variable the `read` also names, an
    unrelated `${FOO:-bar}` a line above a `read BAR` prompt is not a guard,
    which is what the old "any `${x:-}` nearby" check wrongly accepted.
    A whiptail/dialog prompt has no assignment target to correlate against,
    so for those any guard-shaped line still counts.
    """
    # Raw lines here, not _unquoted: the guarding variable normally lives
    # *inside* the quotes (`[[ -z "${ADMIN_EMAIL:-}" ]]`), so stripping them
    # would throw away the very name we need to correlate.
    for line in preceding:
        if not GUARD_LINE_RE.search(line):
            continue
        if not targets:
            return True
        if any(v.lower() in targets for v in GUARD_VAR_RE.findall(line)):
            return True
    return False


def classify_install_feasibility(ct_script: str, install_script: str) -> tuple[bool, str | None]:
    if len(BUILD_CONTAINER_RE.findall(ct_script)) != 1:
        return False, UNSUPPORTED_MULTI_CT

    lines = install_script.splitlines()
    for i, line in enumerate(lines):
        bare = _unquoted(line)
        if WHIPTAIL_RE.search(bare):
            targets: set[str] = set()
        elif READ_RE.search(bare) and not NOT_A_PROMPT_RE.search(bare):
            targets = _read_targets(bare)
        else:
            continue
        if "||" in bare:  # e.g. `read ... || nvidia_reply=""`
            continue
        if _is_guarded(lines[max(0, i - 3):i], targets):
            continue
        return False, UNSUPPORTED_INTERACTIVE

    return True, None
