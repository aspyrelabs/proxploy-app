import http.client
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from proxploy.config import Settings, get_settings
from proxploy.db import make_engine, make_sessionmaker, run_migrations


def create_app(
    settings: Settings | None = None,
    *,
    public_keys: dict[str, str] | None = None,
    proxmox_factory=None,
    license_client=None,
) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        from proxploy.secretstore import SecretStore

        db_file = settings.db_url.removeprefix("sqlite:///")
        db_exists = settings.db_url.startswith("sqlite") and Path(db_file).exists()
        SecretStore.ensure_key_file(settings.master_key_file, db_file_exists=db_exists)
        app.state.secretstore = SecretStore(settings.master_key_file)
        run_migrations(settings)
        app.state.engine = make_engine(settings)
        app.state.sessionmaker = make_sessionmaker(app.state.engine)
        yield
        app.state.engine.dispose()

    app = FastAPI(title="Proxploy", docs_url="/api/docs",
                  openapi_url="/api/openapi.json", lifespan=lifespan)
    app.state.settings = settings

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
