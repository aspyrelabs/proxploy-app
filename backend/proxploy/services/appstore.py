"""App Store install job handler (doc 10 Phase 4 DoD: pin + diff + consent +
stream + archive). Mirrors services/lifecycle.py's shape: blocking _resolve
helper in a thread, ctx.log/ctx.progress narration, JobFailed for expected
errors, module-bottom HANDLERS registration.

Root-consent gating lives at the API layer (Task 6) — this handler assumes
the caller has already obtained consent and only does the pin + SSH-install
+ archive work.
"""
from __future__ import annotations

import asyncio
import hashlib

from proxploy.executor import SSHExecutor
from proxploy.jobs import HANDLERS, JobContext, JobFailed
from proxploy.models import App, AppScript, CatalogEntry, Host
from proxploy.services.catalog import raw_url


SHORT_SHA = 7


def pinned_ref(db, app_id: int) -> str | None:
    """The upstream commit the app's newest saved script came from."""
    latest = (db.query(AppScript).filter_by(app_id=app_id)
              .order_by(AppScript.version.desc()).first())
    return latest.upstream_ref if latest else None


def mark_updates_available(db) -> dict:
    """Recompute `apps.update_available` for every app. Blocking.

    community-scripts publishes no version numbers (doc 01 §3), so the only
    honest signal is "the commit this app was pinned to is behind the commit
    the catalog now holds". The column stores the SHORT sha an update would
    move the app to, which is what doc 06's "Update to vX" renders.

    This is DERIVED state, recomputed wholesale rather than latched: an app
    that updated, or whose catalog entry was rolled back, must stop advertising
    an update. `cleared` counts exactly that.

    Skipped, each for a reason rather than as an oversight:
      - no `catalog_slug` — a hand-rolled CT adopted in Phase 4 has no upstream;
      - no `app_scripts` row — an adopted app has no "from" commit, so there is
        no diff to show and nothing to consent to;
      - catalog entry with no `upstream_sha` — never successfully refreshed.
    """
    shas = {c.slug: c.upstream_sha
            for c in db.query(CatalogEntry.slug, CatalogEntry.upstream_sha).all()}
    marked = cleared = 0
    for a in db.query(App).all():
        want = None
        upstream = shas.get(a.catalog_slug) if a.catalog_slug else None
        if upstream:
            ref = pinned_ref(db, a.id)
            if ref and ref != upstream:
                want = upstream[:SHORT_SHA]
        if want == a.update_available:
            continue
        if want:
            marked += 1
        else:
            cleared += 1
        a.update_available = want
    db.commit()
    return {"marked": marked, "cleared": cleared}


def _resolve(app, catalog_slug: str, host_id: int):
    """Blocking: (catalog row, host, install script). Runs in a thread.

    Deliberately does NOT fetch the SSH private key here: only
    proxploy/executor/ may reference `get_ssh_private_key`
    (scripts/check_executor_isolation.py) — the key is instead resolved
    inside `SSHExecutor.run_for_host` at connect time.
    """
    with app.state.sessionmaker() as db:
        entry = db.query(CatalogEntry).filter_by(slug=catalog_slug).one_or_none()
        if entry is None:
            raise JobFailed(f"catalog entry {catalog_slug} not found")
        if not entry.installable:
            raise JobFailed(f"{catalog_slug} is not installable: {entry.unsupported_reason}")
        if not entry.upstream_sha:
            # Without a pinned commit there is nothing to execute that matches
            # what was classified and diffed — never silently fall back to
            # `main`, which is the bug this guard exists to prevent.
            raise JobFailed(f"{catalog_slug} has no pinned upstream commit; "
                            f"refresh the catalog before installing")
        host = db.get(Host, host_id)
        if host is None:
            raise JobFailed(f"host {host_id} not found")
        install_script = (entry.raw or {}).get("install_script", "")
        return entry, host, install_script


async def run_install(ctx: JobContext, params: dict) -> dict:
    app = ctx.backend.app
    catalog_slug = params["catalog_slug"]
    host_id = int(params["host_id"])
    ctid = int(params["ctid"])
    name = params["name"]
    overrides = params.get("overrides") or {}

    entry, host, install_script = await asyncio.to_thread(
        _resolve, app, catalog_slug, host_id)

    ctx.log(f"installing {catalog_slug} on {host.name} as CT {ctid}")
    env = {"MODE": "default", "PHS_SILENT": "1"}
    for key, val in overrides.items():
        env[f"var_{key}"] = str(val)
    # Set last so it always wins over an `overrides` entry: the App row below
    # records this ctid as fact, so the container has to actually land there.
    # misc/build.func honours it (`local requested_id="${var_ctid:-$NEXTID}"`);
    # without it the script silently auto-picks the next free ID instead and
    # the App row points at a CT that doesn't exist.
    env["var_ctid"] = str(ctid)

    executor = SSHExecutor(connect_factory=app.state.ssh_connect_factory)

    def on_new_fingerprint(fp: str) -> None:
        # Fresh session, not the `_resolve` one above — that session is
        # already closed by the time the SSH connection is made.
        with app.state.sessionmaker() as db:
            h = db.get(Host, host_id)
            if h is not None:
                h.ssh_host_key_fingerprint = fp
                db.commit()

    # Pinned to the exact commit that was ingested, classified and diffed —
    # not to `main`, which would be a fresh, possibly-different fetch at
    # execution time and would make the app_scripts pin decorative.
    #
    # RESIDUAL LIMITATION (deliberately not solved here): the pinned ct/*.sh
    # itself contains a literal `source <(curl -fsSL .../main/misc/build.func)`
    # line. That line's text is frozen at this commit, but the framework file
    # it names is still fetched live from `main` at execution time, one level
    # down. Full transitive vendoring of the community-scripts framework is a
    # separate, larger piece of work — see docs/notes/phase-4-store.md.
    command = (
        f"bash -c \"$(curl -fsSL {raw_url(entry.upstream_sha, entry.script_path)})\""
    )
    try:
        status = await executor.run_for_host(
            app.state.sessionmaker, app.state.secretstore, host_id, host.address, command,
            pinned_fingerprint=host.ssh_host_key_fingerprint,
            on_new_fingerprint=on_new_fingerprint, env=env,
            on_line=lambda stream, line: ctx.log(line, stream=stream),
        )
    except LookupError as e:
        raise JobFailed(str(e)) from e
    if status != 0:
        raise JobFailed(f"install script exited {status}")
    ctx.progress(80)

    # host_id is part of the slug, not just catalog_slug+ctid: App.slug has a
    # global UNIQUE constraint, and two different hosts could each install
    # the same catalog app onto the same CTID, which would collide without
    # host_id in the slug.
    slug = f"{catalog_slug}-{host_id}-{ctid}"
    with app.state.sessionmaker() as db:
        row = App(host_id=host_id, ctid=ctid, name=name, slug=slug,
                  catalog_slug=catalog_slug, category=entry.category,
                  web_protocol="http", web_path="/", adopted=True,
                  update_available=None)
        db.add(row)
        db.flush()
        db.add(AppScript(app_id=row.id, version=1, content=install_script,
                         content_sha256=hashlib.sha256(install_script.encode()).hexdigest(),
                         source="upstream", upstream_ref=entry.upstream_sha))
        db.commit()
        app_id, out_slug = row.id, row.slug

    ctx.progress(100)
    app.state.bus.publish("resource", {"type": "app", "id": app_id, "change": "installed"})
    return {"app_id": app_id, "slug": out_slug}


HANDLERS["app.install"] = run_install
