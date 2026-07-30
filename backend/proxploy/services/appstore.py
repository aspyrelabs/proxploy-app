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

    executor = SSHExecutor(connect_factory=app.state.ssh_connect_factory)

    def on_new_fingerprint(fp: str) -> None:
        # Fresh session, not the `_resolve` one above — that session is
        # already closed by the time the SSH connection is made.
        with app.state.sessionmaker() as db:
            h = db.get(Host, host_id)
            if h is not None:
                h.ssh_host_key_fingerprint = fp
                db.commit()

    command = (
        f"bash -c \"$(curl -fsSL "
        f"https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main/{entry.script_path})\""
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
                  web_protocol="http", web_path="/", adopted=True)
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
