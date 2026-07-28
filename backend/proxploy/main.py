import http.client

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from proxploy.config import Settings, get_settings


def create_app(
    settings: Settings | None = None,
    *,
    public_keys: dict[str, str] | None = None,
    proxmox_factory=None,
    license_client=None,
) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="Proxploy", docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.settings = settings

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
