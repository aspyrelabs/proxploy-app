import hmac
import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

MUTATING = {"POST", "PUT", "PATCH", "DELETE"}


class CSRFMiddleware(BaseHTTPMiddleware):
    """Double-submit CSRF (doc 08 §5). API-key (Authorization header) clients are exempt."""

    def __init__(self, app, cookie_name: str = "pp_csrf", secure: bool = False):
        super().__init__(app)
        self.cookie_name = cookie_name
        self.secure = secure

    async def dispatch(self, request, call_next):
        if (request.url.path.startswith("/api/") and request.method in MUTATING
                and "authorization" not in request.headers):
            cookie = request.cookies.get(self.cookie_name, "")
            header = request.headers.get("x-csrf-token", "")
            if not cookie or not hmac.compare_digest(cookie, header):
                return JSONResponse(
                    {"type": "about:blank", "title": "Forbidden", "status": 403,
                     "detail": "CSRF token missing or invalid"},
                    status_code=403, media_type="application/problem+json")
        response = await call_next(request)
        if self.cookie_name not in request.cookies:
            response.set_cookie(self.cookie_name, secrets.token_urlsafe(32),
                                samesite="lax", httponly=False, secure=self.secure)
        return response
