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
import secrets
from datetime import timedelta

from sqlalchemy import select

from proxploy.models import InstallAnswer, utcnow

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

