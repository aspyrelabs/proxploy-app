"""Answers to an install script's unguarded prompts, kept out of jobs.params.

WHY A SEPARATE STORE AND NOT JUST REDACTION. JobBackend.enqueue redacts
params by KEY NAME (services/audit.py). That works everywhere else because we
choose those keys. It cannot work here: the key is the shell variable a
community-scripts prompt assigns into, named by whoever wrote the installer.
Measured against the real catalog on 2026-08-27, of 15 prompts whose text asks
for something sensitive, 11 have a name the heuristic does not catch, among
them `ziti_pwd` holding an admin password, four API keys named `*key` (which
REDACT_SUBSTRINGS excludes on purpose), and an openziti enrollment JWT read
into a variable called `prompt`.

No substring list catches `prompt`. So the value never enters params at all.
The route stages it here, params carries only the handle, and redaction stops
being load-bearing because there is nothing left in the row to redact.

The staging shape mirrors `spool_path`, which api/storage.py writes for an
upload job to consume, with two differences that both follow from this being a
secret: it lives in the database encrypted rather than on disk, and it is
KEPT after a successful install rather than deleted, because app.update
re-runs the same script and meets the same prompts. An answer given once
should not have to be typed again to apply a patch release.
"""
from __future__ import annotations

import json
import re
import secrets
from datetime import timedelta

from sqlalchemy import select

from proxploy.models import InstallAnswer, utcnow
from proxploy.services.classifier import answerable_without_asking

# How long an unbound row may sit before the sweeper takes it. Long enough to
# cover a slow install (build_container plus a large image pull), short enough
# that an abandoned dialog does not leave a secret at rest indefinitely.
ORPHAN_TTL = timedelta(hours=6)


def stage(db, secretstore, answers: dict[str, str]) -> str | None:
    """Encrypt `answers` and return the handle to put in jobs.params.

    None for an empty dict, so a caller can pass the result straight through
    without branching and an app with no sensitive prompts stores no row.
    """
    if not answers:
        return None
    handle = secrets.token_urlsafe(24)
    blob, version = secretstore.encrypt(json.dumps(answers).encode())
    db.add(InstallAnswer(handle=handle, encrypted_blob=blob, key_version=version))
    db.commit()
    return handle


def load(db, secretstore, handle: str | None) -> dict[str, str]:
    """The staged answers, or {} if the handle is unknown or already swept.

    Never raises on a missing handle: a job retried after the sweeper ran is a
    normal thing to survive, and the install will simply fail at the prompt it
    can no longer answer, which is a better failure than a 500.
    """
    if not handle:
        return {}
    row = db.scalar(select(InstallAnswer).where(InstallAnswer.handle == handle))
    if row is None:
        return {}
    return json.loads(secretstore.decrypt(row.encrypted_blob).decode())


def for_app(db, secretstore, app_id: int) -> dict[str, str]:
    """Everything bound to this app, for app.update to re-answer with."""
    rows = db.scalars(
        select(InstallAnswer).where(InstallAnswer.app_id == app_id)).all()
    out: dict[str, str] = {}
    for row in rows:
        out.update(json.loads(secretstore.decrypt(row.encrypted_blob).decode()))
    return out


def bind(db, handle: str | None, app_id: int) -> None:
    """Attach a staged row to the app the install just built.

    Until this runs the row is an orphan with a TTL. After it runs the row
    lives and dies with the app, by ON DELETE CASCADE, so uninstalling takes
    the secrets with it and nothing has to remember to.
    """
    if not handle:
        return
    row = db.scalar(select(InstallAnswer).where(InstallAnswer.handle == handle))
    if row is not None:
        row.app_id = app_id
        db.commit()


def discard(db, handle: str | None) -> None:
    """Drop a staged row whose install never produced an app."""
    if not handle:
        return
    row = db.scalar(select(InstallAnswer).where(InstallAnswer.handle == handle))
    if row is not None:
        db.delete(row)
        db.commit()


def sweep_orphans(db) -> int:
    """Unbound rows older than ORPHAN_TTL. Returns how many were removed.

    The backstop for the paths `discard` cannot reach: a crash between staging
    and running, or a dialog the operator abandoned after typing a token.
    """
    cutoff = utcnow() - ORPHAN_TTL
    rows = db.scalars(
        select(InstallAnswer).where(InstallAnswer.app_id.is_(None),
                                    InstallAnswer.created_at < cutoff)).all()
    for row in rows:
        db.delete(row)
    if rows:
        db.commit()
    return len(rows)


# Affirmative answers to a consent gate. Anything else, including empty and
# including "n", is a refusal, and a refusal means do not install.
AFFIRMATIVE = {"y", "yes", "true", "1", "on"}

# A shell variable name we are willing to export. The names come from the
# catalog, which is upstream data, and they land in the environment of a root
# shell on the operator's node. Anything outside this cannot be an identifier
# a `read` assigns into, so refusing it costs nothing real.
_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class AnswerError(ValueError):
    """A refusal the route turns into a 400, never a 500."""


def prepare(prompts: list[dict] | None, answers: dict[str, str] | None
            ) -> tuple[dict, dict]:
    """Validate answers against the prompts, split into (plain, secret).

    `plain` may ride jobs.params; `secret` must be staged and referenced by
    handle. Raises AnswerError on anything the operator has to fix.

    Every rule here is a refusal rather than a repair. A missing answer that we
    guess at produces an install that hangs or aborts halfway, which is worse
    than one that never started, and a value we quietly drop produces an app
    configured differently from what was asked for.
    """
    prompts = prompts or []
    answers = answers or {}
    by_name = {p["variable"]: p for p in prompts}

    unknown = sorted(set(answers) - set(by_name))
    if unknown:
        # Not pedantry: these become environment variables in a root shell on
        # the node. Only names this script actually asks about may pass.
        raise AnswerError(f"not asked by this install script: {', '.join(unknown)}")

    plain: dict[str, str] = {}
    secret: dict[str, str] = {}
    for name, prompt in by_name.items():
        if not _NAME_RE.fullmatch(name):
            raise AnswerError(f"unusable variable name in the catalog: {name!r}")
        given = answers.get(name)
        if given is None or str(given) == "":
            if prompt.get("gate"):
                raise AnswerError(
                    f"{name}: this install asks for confirmation and cannot be "
                    f"answered on your behalf")
            if not answerable_without_asking(prompt):
                raise AnswerError(f"{name}: an answer is required ({prompt['label']})")
            continue          # a default covers it; the handler fills it in
        value = str(given)
        if prompt.get("gate") and value.strip().lower() not in AFFIRMATIVE:
            raise AnswerError(f"{name}: not confirmed, so nothing was installed")
        (secret if prompt.get("sensitive") else plain)[name] = value
    return plain, secret


def defaults_for(prompts: list[dict] | None) -> dict[str, str]:
    """What the handler fills in for prompts nobody was asked about.

    A gate is absent by construction: answerable_without_asking refuses one, so
    it can never acquire a default here however it is shaped.
    """
    out: dict[str, str] = {}
    for p in prompts or []:
        if not answerable_without_asking(p):
            continue
        if p["kind"] == "yesno":
            out[p["variable"]] = p.get("default") or "n"
        elif p.get("default") is not None:
            out[p["variable"]] = str(p["default"])
    return out
