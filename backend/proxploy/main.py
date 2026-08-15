import http.client
import shutil
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from proxploy import __version__
from proxploy.config import Settings, get_settings
from proxploy.db import make_engine, make_sessionmaker, run_migrations
from proxploy.models import AppSetting, utcnow


def _init_reporting(settings: Settings) -> str:
    """Start crash reporting if the operator opted in; say what happened.

    Opt-in only (see `Settings.sentry_dsn`), and called before the app is
    built so a failure during lifespan startup is still reported.

    A malformed DSN is caught rather than raised. This runs on someone else's
    hardware, often headless, and refusing to boot the whole management plane
    over a typo in an optional setting would be a far worse failure than not
    collecting crashes. The returned string surfaces on `GET /meta/version`,
    so an operator who set the DSN can confirm it actually took effect instead
    of assuming.
    """
    if not settings.sentry_dsn:
        return "off"
    try:
        import sentry_sdk
        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            environment=settings.env,
            release=__version__,
            # Non-negotiable on this side: an operator who opts into crash
            # reports is not opting into shipping us their request bodies,
            # headers or LAN addresses. Everything this app touches (PVE
            # credentials, session cookies, host names) would ride along.
            send_default_pii=False,
        )
    except Exception as e:
        return f"error: {type(e).__name__}"
    return "on"


def create_app(
    settings: Settings | None = None,
    *,
    roots: dict[str, str] | None = None,
    proxmox_factory=None,
    ssh_factory=None,
    license_client=None,
) -> FastAPI:
    settings = settings or get_settings()

    reporting = _init_reporting(settings)

    from proxploy.entitlements.client import Entitlements
    from proxploy.entitlements.keys import load_root_keys
    from proxploy.services.license_client import LicenseClient

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        from proxploy.secretstore import SecretStore

        db_file = settings.db_url.removeprefix("sqlite:///")
        db_exists = settings.db_url.startswith("sqlite") and Path(db_file).exists()
        SecretStore.ensure_key_file(settings.master_key_file, db_file_exists=db_exists)
        app.state.secretstore = SecretStore(settings.master_key_file)
        from proxploy.executor.ssh import default_connect_factory
        app.state.ssh_connect_factory = ssh_factory or default_connect_factory
        run_migrations(settings)
        app.state.engine = make_engine(settings)
        app.state.sessionmaker = make_sessionmaker(app.state.engine)
        with app.state.sessionmaker() as db:
            app.state.entitlements.load(db, app.state.secretstore)

        from proxploy.services.authz import build_enforcer
        with app.state.sessionmaker() as db:
            app.state.authz = build_enforcer(db)

        import asyncio

        async def _refresh_loop():
            import random

            from proxploy.api.entitlements import apply_new_token  # helper reuse
            while True:
                await asyncio.sleep(3600 * 24 + random.uniform(0, 600))  # ~half of 72h exp is fine at Phase 1 granularity; jittered
                try:
                    with app.state.sessionmaker() as db:
                        row = (db.query(AppSetting)
                               .filter_by(key="license.refresh_credential.enc").one_or_none())
                        if not row:
                            # continue, not return: an owner who removes the
                            # license and activates a new one later would
                            # otherwise get no auto-refresh until a restart,
                            # and the token lapses to builtin after grace.
                            continue
                        install_row = (db.query(AppSetting)
                                       .filter_by(key="license.install_id").one_or_none())
                        cred = app.state.secretstore.decrypt(row.value.encode()).decode()
                        # refresh() is synchronous httpx with a 10s timeout.
                        # On the loop it stalls SSE pings, console frames and
                        # every job's await_task poll with it, the same reason
                        # the poller and scheduler hand their blocking calls to
                        # a thread.
                        out = await asyncio.to_thread(
                            app.state.license_client.refresh,
                            cred, install_row.value if install_row else None)
                        # apply via a fake-request shim: the helper only needs .app
                        class _Req:  # noqa: N801  (minimal shim)
                            pass
                        req = _Req(); req.app = app
                        apply_new_token(req, db, out["token"], out.get("cert"))
                except Exception:
                    continue  # doc 07 §8: transient failure = keep serving, retry later

        with app.state.sessionmaker() as db:
            licensed = (db.query(AppSetting)
                        .filter_by(key="license.refresh_credential.enc").one_or_none())
        refresh_task = asyncio.create_task(_refresh_loop()) if licensed else None

        from proxploy.events import EventBus

        app.state.bus = EventBus()
        app.state.loop = asyncio.get_running_loop()  # test seam for cross-thread publishes

        from proxploy.jobs import JobBackend, Scheduler
        from proxploy.pollers import Poller
        from proxploy.services import appstore as _appstore  # noqa: F401  (registers app.install / app.update)
        from proxploy.services import backupjobs as _backupjobs  # noqa: F401  (registers backup.sync)
        from proxploy.services import catalog as _catalog  # noqa: F401  (registers catalog.refresh)
        from proxploy.services import guestjobs as _guestjobs  # noqa: F401  (registers network.apply)
        from proxploy.services import lifecycle  # noqa: F401  (registers job handlers)
        from proxploy.services import migrate as _migrate  # noqa: F401  (registers migrate.app)
        from proxploy.services import storagejobs as _storagejobs  # noqa: F401  (registers storage.upload/delete_volume)
        from proxploy.services import metrics as _metrics  # noqa: F401  (registers metrics.maintain)

        app.state.jobs = JobBackend(app)
        app.state.jobs.sweep_orphans()  # doc 02 §3: mark orphans, never resume
        # A spooled upload belongs to a job sweep_orphans just marked
        # `interrupted` above: this runner never resumes a job across a
        # restart: so anything left in the upload spool dir at boot is
        # provably orphaned. Clear it rather than let a crash/OOM/deploy
        # mid-upload strand a multi-GB temp file on disk forever.
        shutil.rmtree(settings.data_dir / "uploads", ignore_errors=True)
        app.state.poller = Poller(app)
        app.state.scheduler = Scheduler(app)
        poller_task = scheduler_task = None
        if settings.poll_enabled:
            poller_task = asyncio.create_task(app.state.poller.run())
        if settings.scheduler_enabled:
            # Seeding needs every handler registered, which the imports above
            # have just done; priming needs the seeded rows.
            from proxploy.jobs.scheduler import prime, seed_system_schedules
            with app.state.sessionmaker() as db:
                seed_system_schedules(db)
                prime(db, utcnow())
            scheduler_task = asyncio.create_task(app.state.scheduler.run())

        # Phase 9a: the installer knows which CT it built Proxploy into and
        # puts it in the env file; persist it once so services/selfguard.py
        # can recognise our own container. Write-once: a later operator
        # correction (Proxploy moved) must survive restarts, so an existing
        # value wins.
        if settings.self_ctid is not None:
            from proxploy.services.settings import get_setting, set_setting
            with app.state.sessionmaker() as db:
                if get_setting(db, "self.ctid") is None:
                    set_setting(db, "self.ctid", settings.self_ctid)

        yield
        if refresh_task:
            refresh_task.cancel()
        if poller_task:
            poller_task.cancel()
        if scheduler_task:
            scheduler_task.cancel()
        app.state.scheduler.stop()
        app.state.poller.stop()
        app.state.jobs.stop()
        app.state.engine.dispose()

    app = FastAPI(title="Proxploy", version=__version__, docs_url="/api/docs",
                  openapi_url="/api/openapi.json", lifespan=lifespan)
    app.state.settings = settings
    app.state.reporting = reporting
    app.state.entitlements = Entitlements(roots or load_root_keys(settings))
    app.state.license_client = license_client or LicenseClient(settings.api_base_url)
    app.state.proxmox_factory = proxmox_factory
    # OIDC single-use state store (services/oidc.py): {state: (verifier, nonce,
    # expires_at)}, pruned on access. app.state.oidc_transport is deliberately
    # NOT set here: it defaults (via getattr) to None = real network, and is
    # the seam tests substitute an ASGITransport into.
    app.state.oidc_states = {}
    # Pending-2FA store (Task 9, api/auth.py): {sha256(raw): (user_id,
    # expires_at, attempts)}, pruned on access. Deliberately NOT a session:
    # holding this token lets a caller do exactly one thing (finish or
    # exhaust the second factor), never resolve_session()/get_current_user.
    # ponytail: in-memory pending-2FA store: single-process app by design
    # (in-process JobBackend); a restart mid-2FA costs one re-login. Move to
    # a table if multi-worker ever lands.
    app.state.pending_totp = {}

    from proxploy.api.auth import limiter
    from proxploy.middleware import CSRFMiddleware

    app.state.limiter = limiter
    # No dedicated RateLimitExceeded handler: it subclasses Starlette's HTTPException
    # (status_code=429, detail=<limit string>), so the problem_handler below already
    # covers it with the same RFC 9457 problem+json shape as every other error path.
    app.add_middleware(CSRFMiddleware, cookie_name=settings.csrf_cookie,
                       secure=settings.cookie_secure)

    from proxploy.api import api_router

    app.include_router(api_router)

    from fastapi.staticfiles import StaticFiles

    dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if dist.exists():
        app.mount("/", StaticFiles(directory=dist, html=True), name="spa")

    @app.exception_handler(RequestValidationError)
    async def _no_echo_validation_errors(request, exc):
        # Pydantic v2's "missing" error carries the whole parent body as
        # `input` (e.g. omit HostIn.name and token_secret rides back out in
        # the 422). Three routes take a secret in the body (ChannelIn.url,
        # HostIn.token_secret, LicenseIn.license_key): strip `input` from
        # every error repo-wide rather than patching each route.
        return JSONResponse(status_code=422, content=jsonable_encoder({
            "detail": [{k: v for k, v in e.items() if k != "input"} for e in exc.errors()]}))

    from proxploy.services.hostclient import CapabilityNotConfigured

    @app.exception_handler(CapabilityNotConfigured)
    async def capability_not_configured_handler(request, exc):
        # Every request-path call site (api/vms.py, api/consoles.py,
        # api/network.py, api/apps.py, api/backups.py) calls client_for_host
        # outside its `except ProxmoxError` block, so this used to escape
        # unhandled into a bare 500. One handler here fixes all of them
        # instead of wrapping each call site individually. 409, not 500 or
        # 502: this is a configuration gap caught before any Proxmox call,
        # not an upstream failure. Only CapabilityNotConfigured, not the
        # broader ProxmoxError: a genuine upstream failure should stay a 502.
        status_code = 409
        return JSONResponse(
            {"type": "about:blank",
             "title": http.client.responses.get(status_code, "Error"),
             "status": status_code, "detail": str(exc)},
            status_code=status_code, media_type="application/problem+json",
        )

    @app.exception_handler(StarletteHTTPException)
    async def problem_handler(request, exc):
        body = {
            "type": "about:blank",
            "title": http.client.responses.get(exc.status_code, "Error"),
            "status": exc.status_code,
        }
        if isinstance(exc.detail, dict):
            body.update(exc.detail)
        else:
            body["detail"] = exc.detail
        return JSONResponse(
            body, status_code=exc.status_code,
            media_type="application/problem+json", headers=exc.headers,
        )

    return app
