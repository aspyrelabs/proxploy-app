import http.client
import shutil
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from proxploy.config import Settings, get_settings
from proxploy.db import make_engine, make_sessionmaker, run_migrations
from proxploy.models import AppSetting


def create_app(
    settings: Settings | None = None,
    *,
    public_keys: dict[str, str] | None = None,
    proxmox_factory=None,
    ssh_factory=None,
    license_client=None,
) -> FastAPI:
    settings = settings or get_settings()

    from proxploy.entitlements.client import Entitlements
    from proxploy.entitlements.keys import load_public_keys
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
                            return
                        cred = app.state.secretstore.decrypt(row.value.encode()).decode()
                        out = app.state.license_client.refresh(cred)
                        # apply via a fake-request shim: the helper only needs .app
                        class _Req:  # noqa: N801 — minimal shim
                            pass
                        req = _Req(); req.app = app
                        apply_new_token(req, db, out["token"])
                except Exception:
                    continue  # doc 07 §8: transient failure = keep serving, retry later

        with app.state.sessionmaker() as db:
            licensed = (db.query(AppSetting)
                        .filter_by(key="license.refresh_credential.enc").one_or_none())
        refresh_task = asyncio.create_task(_refresh_loop()) if licensed else None

        from proxploy.events import EventBus

        app.state.bus = EventBus()
        app.state.loop = asyncio.get_running_loop()  # test seam for cross-thread publishes

        from proxploy.jobs import JobBackend
        from proxploy.pollers import Poller
        from proxploy.services import appstore as _appstore  # noqa: F401 — registers app.install
        from proxploy.services import backupjobs as _backupjobs  # noqa: F401 — registers backup.sync
        from proxploy.services import catalog as _catalog  # noqa: F401 — registers catalog.refresh
        from proxploy.services import guestjobs as _guestjobs  # noqa: F401 — registers network.apply
        from proxploy.services import lifecycle  # noqa: F401 — registers job handlers
        from proxploy.services import storagejobs as _storagejobs  # noqa: F401 — registers storage.upload/delete_volume
        from proxploy.services.metrics import metrics_loop

        app.state.jobs = JobBackend(app)
        app.state.jobs.sweep_orphans()  # doc 02 §3: mark orphans, never resume
        # A spooled upload belongs to a job sweep_orphans just marked
        # `interrupted` above — this runner never resumes a job across a
        # restart — so anything left in the upload spool dir at boot is
        # provably orphaned. Clear it rather than let a crash/OOM/deploy
        # mid-upload strand a multi-GB temp file on disk forever.
        shutil.rmtree(settings.data_dir / "uploads", ignore_errors=True)
        app.state.poller = Poller(app)
        poller_task = metrics_task = None
        if settings.poll_enabled:
            poller_task = asyncio.create_task(app.state.poller.run())
            metrics_task = asyncio.create_task(metrics_loop(app))

        yield
        if refresh_task:
            refresh_task.cancel()
        if poller_task:
            poller_task.cancel()
        if metrics_task:
            metrics_task.cancel()
        app.state.poller.stop()
        app.state.jobs.stop()
        app.state.engine.dispose()

    app = FastAPI(title="Proxploy", docs_url="/api/docs",
                  openapi_url="/api/openapi.json", lifespan=lifespan)
    app.state.settings = settings
    app.state.entitlements = Entitlements(public_keys or load_public_keys(settings))
    app.state.license_client = license_client or LicenseClient(settings.api_base_url)
    app.state.proxmox_factory = proxmox_factory

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
        # HostIn.token_secret, LicenseIn.license_key) — strip `input` from
        # every error repo-wide rather than patching each route.
        return JSONResponse(status_code=422, content=jsonable_encoder({
            "detail": [{k: v for k, v in e.items() if k != "input"} for e in exc.errors()]}))

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
