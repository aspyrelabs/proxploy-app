import http.client
import logging
import shutil
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path

from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import Headers
from starlette.exceptions import HTTPException as StarletteHTTPException

from proxploy import __version__
from proxploy.config import Settings, get_settings
from proxploy.db import make_engine, make_sessionmaker, run_migrations
from proxploy.models import AppSetting, utcnow

logger = logging.getLogger(__name__)


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


class _SPAStatic(StaticFiles):
    """StaticFiles that also serves index.html for client-side routes.

    `html=True` falls back to index.html for a DIRECTORY, never for a
    client-side route, and every route in this product is client-side. So
    refreshing on /settings or /store/plex returned the app's 404 in
    production while Vite did the fallback in dev (doc 12).

    Subclassing here rather than registering a 404 exception handler is the
    whole point. A handler ALSO replaced the body of every other 404, which
    flattened the structured `detail` that routes like
    `HTTPException(404, {"error": "oidc_not_configured"})` pass, and that is
    why the first attempt was reverted. This code only ever runs for a path
    that reached the mount, i.e. one the API router did not claim, so no
    route's own 404 can pass through it.
    """

    async def get_response(self, path: str, scope):
        # StaticFiles RAISES HTTPException(404) for a missing path rather than
        # returning a 404 response, so this has to catch rather than inspect.
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as e:
            if e.status_code != 404:
                raise
            # An unmatched /api/... path is a caller error, not a page: let its
            # 404 stand rather than answering with HTML.
            if scope.get("path", "").startswith("/api/"):
                raise
            # Accept is the discriminator, not the path shape: a navigation
            # sends text/html, while a fetch for a missing module sends */*. A
            # missing asset must stay a 404; handing the loader HTML instead
            # fails further from the cause.
            if "text/html" not in Headers(scope=scope).get("accept", ""):
                raise
            return await super().get_response("index.html", scope)


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
            app.state.entitlements.load(
                db, app.state.secretstore,
                timedelta(days=settings.license_revalidation_days))

        from proxploy.services.authz import build_enforcer
        with app.state.sessionmaker() as db:
            app.state.authz = build_enforcer(db)

        import asyncio

        # start_refresh_loop is idempotent; boot starts it only when a license
        # is already on file (the activation route calls it too).
        from proxploy.api.entitlements import start_refresh_loop

        with app.state.sessionmaker() as db:
            licensed = (db.query(AppSetting)
                        .filter_by(key="license.refresh_credential.enc").one_or_none())
        if licensed:
            start_refresh_loop(app)

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
        from proxploy.services import maintenance as _maintenance  # noqa: F401  (registers sessions.cleanup / jobs.prune / db.compact / update.check)
        from proxploy.services import migrate as _migrate  # noqa: F401  (registers migrate.app)
        from proxploy.services import storagejobs as _storagejobs  # noqa: F401  (registers storage.upload/delete_volume)
        from proxploy.services import metrics as _metrics  # noqa: F401  (registers metrics.maintain)

        app.state.jobs = JobBackend(app)
        app.state.jobs.sweep_orphans()  # doc 02 §3: mark orphans, never resume

        # Off the boot path on purpose, never awaited here. Every host costs
        # several PVE round trips plus an SSH connection, and packaging/
        # proxploy-update health-checks the new release right after it
        # switches: a slow boot would fail that check and roll back the very
        # upgrade this repair exists to complete.
        async def _repair_privileges_at_boot():
            from proxploy.models import Host
            from proxploy.services.privrepair import repair_host_privileges

            with app.state.sessionmaker() as db:
                host_ids = [h.id for h in db.query(Host).all()]
            for host_id in host_ids:
                try:
                    with app.state.sessionmaker() as db:
                        host = db.get(Host, host_id)
                        if host is not None:
                            await repair_host_privileges(app, db, host,
                                                         actor_type="system")
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("privilege repair failed for host %s", host_id)
        # A spooled upload belongs to a job sweep_orphans just marked
        # `interrupted` above: this runner never resumes a job across a
        # restart: so anything left in the upload spool dir at boot is
        # provably orphaned. Clear it rather than let a crash/OOM/deploy
        # mid-upload strand a multi-GB temp file on disk forever.
        shutil.rmtree(settings.data_dir / "uploads", ignore_errors=True)
        app.state.poller = Poller(app)
        app.state.scheduler = Scheduler(app)
        poller_task = scheduler_task = None
        repair_task = asyncio.create_task(_repair_privileges_at_boot())
        if settings.alerts_enabled:
            # Evaluation rides the poll loop (pollers/__init__.py), so the rules
            # are seeded on the same flag, matching how the scheduler seeds its
            # own rows below. A fresh install otherwise had no rule for either
            # condition that means "this host cannot be used", so a dead or
            # unwritable host notified nobody.
            from proxploy.services.alerts import seed_default_alert_rules
            with app.state.sessionmaker() as db:
                seed_default_alert_rules(db)
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

        # Persist the installer-supplied CT id once (write-once: an existing
        # value wins) so services/selfguard.py can recognise our own container.
        if settings.self_ctid is not None:
            from proxploy.services.settings import get_setting, set_setting
            with app.state.sessionmaker() as db:
                if get_setting(db, "self.ctid") is None:
                    set_setting(db, "self.ctid", settings.self_ctid)

        yield
        refresh_task = getattr(app.state, "refresh_task", None)
        if refresh_task:
            refresh_task.cancel()
        repair_task.cancel()
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

    dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if dist.exists():
        app.mount("/", _SPAStatic(directory=dist, html=True), name="spa")

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
