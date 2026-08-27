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
# Narrower refusals, for the two shapes an answer still cannot reach. Kept
# distinct from UNSUPPORTED_INTERACTIVE because they say different things to
# an operator reading a card: one is "nobody can drive this unattended", the
# other two are "we can drive it but not this particular question".
UNSUPPORTED_UNNAMED_PROMPT = (
    "install script prompts without assigning the answer to a variable, "
    "so there is nothing to answer")
UNSUPPORTED_RETRY_LOOP = (
    "install script re-prompts until the answer validates, which a supplied "
    "answer cannot satisfy without hanging")


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


# The prompt sentence a script shows a human, recovered from `read -p`. This
# is the ONLY description of the value that exists: there is no schema, no
# help text, nothing upstream declares. The variable name is not a substitute
# (see SENSITIVE_PROMPT_RE below for why).
# `-\w*p` because short flags combine: `read -rp "..."` is as common upstream
# as `read -r -p "..."`, and matching only the spaced form lost the label on a
# quarter of all prompts, silently falling back to the variable name.
PROMPT_TEXT_RE = re.compile(r"""-\w*p\s+(?:"([^"]*)"|'([^']*)')""")

# Whether the value should be masked in the UI and routed to the secretstore
# instead of jobs.params, decided from the PROMPT TEXT and never from the
# variable name.
#
# The name is chosen by whoever wrote the upstream installer and carries no
# reliable signal. Measured against the real catalog on 2026-08-27: of 15
# prompts asking for something sensitive, 11 have a name services/audit.py's
# heuristic does not catch, including `ziti_pwd` for an admin password and
# `prompt` for an openziti enrollment JWT. The sentence next to that last one
# reads "Please paste an identity enrollment token(JTW)", which is the signal.
#
# This is still a heuristic, and it is allowed to be, because of what it now
# decides. Since the secretstore landed it chooses whether a field is MASKED
# and stored encrypted, not whether it is written to the database in clear.
# A false negative is a value shown in a transcript, not a plaintext secret at
# rest. Do not move this back onto the variable name to "make it consistent"
# with audit.py: those two are answering different questions about different
# data whose names we control to different degrees.
# `read -s` suppresses the echo, which means the script author has already
# declared this value too sensitive to appear on a terminal. That is a
# statement of intent, not a guess about wording, so it outranks the sentence
# heuristic below and applies even when there is no prompt text to read: a
# bare `read -s PASS` labels itself "pass", which matches nothing.
SILENT_READ_RE = re.compile(r"\bread\b(?:\s+-\w+)*\s+-\w*s\b")

SENSITIVE_PROMPT_RE = re.compile(
    r"\b(?:password|passwd|passphrase|secret|api[ _-]?key|access[ _-]?key|"
    r"token|credential|private[ _-]?key|client[ _-]?secret)\b", re.I)

# Enumerated choices the prompt spells out, e.g. "(15/16/17/18)" or
# "[1=agent, 2=agent2]". Recovered so the UI can offer a select rather than a
# free text box the operator has to guess into.
# Enumerated alternatives, digits or short letters: "(15/16/17/18)" and
# "<n/l/a>" are the same offer written two ways. Checked AFTER YESNO_RE, which
# would otherwise be swallowed by this since "<y/N>" has the identical shape.
# Tokens are capped at 3 characters so this cannot swallow a sentence
# containing a slash.
CHOICES_RE = re.compile(r"[(\[<](\w{1,3}(?:/\w{1,3}){1,3})[)\]>]")
# A yes/no prompt, and which way it defaults: upstream writes the default as
# the capitalised letter, so "[y/N]" declines and "[Y/n]" accepts.
YESNO_RE = re.compile(r"[\[(<]\s*(y/n|yes/no)\s*[\])>]", re.I)
# Checked AFTER YESNO_RE, or "[y/N]" is read as a default literally spelled
# "y/N" and offered to the operator as if it were a value.
DEFAULT_RE = re.compile(r"\[([^\[\]]{1,24})\]\s*:?\s*$")


# A prompt whose answer can ABORT the run: an `exit` guarded by the prompt's
# own variable, close enough after the read to be that prompt's consequence.
#
# Detected mechanically rather than from the wording, and the wording is why.
# These read "This script will run an external installer from a third-party
# source ... NOT maintained or audited by our repository. Do you want to
# continue? [y/N]", and no phrasing rule separates that reliably from "Would
# you like to add Unbound?". The `exit` does: one aborts the install, the other
# skips an extra.
#
# 16 of the 70 blocked scripts have one, 155,205 recorded installs. It matters
# because the capitalised default is `n`, so defaulting it aborts the install
# and reports failure, while flipping it to `y` silently consents to running
# unaudited third-party code on the operator's behalf. Neither is ours to pick,
# which is why `answerable_without_asking` below refuses to touch one.
GATE_WINDOW = 8
EXIT_RE = re.compile(r"\bexit\b")

# A prompt inside a retry loop, which the read shim cannot safely answer.
#
# The shim answers from the environment EVERY time the script calls read, so a
# loop that re-prompts until the answer validates never sees a different value.
# Give it something the loop rejects and it spins forever: the install hangs
# rather than failing, which is the worst outcome available. Falling through to
# `builtin read` on the retry does not help either, since EOF leaves the value
# empty and empty is rejected too.
#
# 8 of the 70 blocked scripts have one. They stay unsupported until the answer
# can be validated against something the loop is known to accept, which is
# possible for an enumerated choice and not for free text.
LOOP_OPEN_RE = re.compile(r"^\s*(?:while|until)\b")
LOOP_CLOSE_RE = re.compile(r"^\s*done\b")


def answerable_without_asking(prompt: dict) -> bool:
    """True when the prompt can be satisfied with no operator input.

    A gate NEVER can, at any layer. That is asserted rather than merely
    intended: pre-answering a consent question is the same act as defaulting
    it to yes with extra steps.
    """
    if prompt.get("gate"):
        return False
    return prompt["kind"] == "yesno" or prompt.get("default") is not None


def extract_prompts(install_script: str) -> list[dict]:
    """Every unguarded prompt, in source order, as the UI needs to ask it.

    Same walk and the same guards as classify_install_feasibility, so the two
    can never disagree about what counts as a prompt. A guarded prompt is
    absent on purpose: build.func already satisfies it from the environment,
    so there is nothing to ask.

    Returns [] for a script with no unguarded prompts, which is also what a
    fully installable script returns, so a caller needs no special case.
    """
    out: list[dict] = []
    lines = install_script.splitlines()
    loop_depth = 0
    for i, line in enumerate(lines):
        bare = _unquoted(line)
        # Tracked before the prompt checks so a `while read` header, which
        # NOT_A_PROMPT_RE already discards, still opens its loop.
        if LOOP_OPEN_RE.match(bare):
            loop_depth += 1
        elif LOOP_CLOSE_RE.match(bare):
            loop_depth = max(0, loop_depth - 1)
        if WHIPTAIL_RE.search(bare):
            targets: set[str] = set()
        elif READ_RE.search(bare) and not NOT_A_PROMPT_RE.search(bare):
            targets = _read_targets(bare)
        else:
            continue
        if "||" in bare:
            continue
        if _is_guarded(lines[max(0, i - 3):i], targets):
            continue
        # The variable is read from the RAW line: _unquoted has already thrown
        # away the -p prompt text, which is where the human-readable part is.
        m = PROMPT_TEXT_RE.search(line)
        text = (m.group(1) or m.group(2) or "") if m else ""
        # ${TAB3} and friends are layout, not words: upstream indents prompts
        # with them and they would render as literal noise in a form label.
        text = re.sub(r"\$\{?\w+\}?", "", text).strip()
        name = sorted(targets)[0] if targets else None
        if not name:
            continue
        yesno = YESNO_RE.search(text)
        choices = None if yesno else CHOICES_RE.search(text)
        default = None
        if yesno:
            # The capitalised side is upstream's own default. Declining is also
            # the safe answer when it is ambiguous: these prompts gate OPTIONAL
            # extras, so "no" installs strictly less.
            default = "y" if yesno.group(1)[0].isupper() else "n"
        else:
            m2 = DEFAULT_RE.search(text)
            default = m2.group(1) if m2 else None
        window = "\n".join(lines[i + 1:i + 1 + GATE_WINDOW])
        gate = bool(EXIT_RE.search(window)
                    and re.search(re.escape(name), window, re.I))
        out.append({
            "variable": name,
            "label": text or name,
            "gate": gate,
            "in_loop": loop_depth > 0,
            "sensitive": bool(SILENT_READ_RE.search(bare)
                              or SENSITIVE_PROMPT_RE.search(text)),
            "kind": "yesno" if yesno else ("choice" if choices else "text"),
            "choices": choices.group(1).split("/") if choices else None,
            "default": default,
        })
    return out


def classify_install_feasibility(ct_script: str, install_script: str) -> tuple[bool, str | None]:
    if len(BUILD_CONTAINER_RE.findall(ct_script)) != 1:
        return False, UNSUPPORTED_MULTI_CT

    # An unguarded prompt no longer refuses the script outright. If every one of
    # them can be turned into a question, the operator answers it in the install
    # dialog and services/appstore's read shim supplies the answer BY VARIABLE.
    #
    # The bar is EVERY prompt, not most. One prompt we cannot answer blocks the
    # whole install behind a closed stdin, and a card that says installable and
    # then hangs is worse than one that honestly says unsupported.
    for prompt in extract_prompts(install_script):
        if prompt["in_loop"]:
            return False, UNSUPPORTED_RETRY_LOOP

    # extract_prompts drops a prompt it cannot name, so a count mismatch means
    # this script asks something we would never present. Compared rather than
    # trusted: a silent drop is exactly how a script becomes installable and
    # then blocks on the question nobody was shown.
    if _unanswerable_prompt_count(install_script):
        return False, UNSUPPORTED_UNNAMED_PROMPT

    return True, None


def _unanswerable_prompt_count(install_script: str) -> int:
    """Unguarded prompts that yield no variable to answer, so extract_prompts
    could not offer them. whiptail/dialog menus are the whole population here:
    they assign nothing, so there is no name to key an answer on."""
    count = 0
    lines = install_script.splitlines()
    for i, line in enumerate(lines):
        bare = _unquoted(line)
        if WHIPTAIL_RE.search(bare):
            targets: set[str] = set()
        elif READ_RE.search(bare) and not NOT_A_PROMPT_RE.search(bare):
            targets = _read_targets(bare)
        else:
            continue
        if "||" in bare:
            continue
        if _is_guarded(lines[max(0, i - 3):i], targets):
            continue
        if not targets:
            count += 1
    return count
