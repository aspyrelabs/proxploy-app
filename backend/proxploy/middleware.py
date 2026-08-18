import hmac
import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

MUTATING = {"POST", "PUT", "PATCH", "DELETE"}


# Byte-for-byte what api/deps.py::current_user accepts, so a header that
# skips CSRF here cannot then fail to authenticate there, or the reverse.
API_KEY_SCHEME = "Bearer ppk_"


class CSRFMiddleware(BaseHTTPMiddleware):
    """Double-submit CSRF (doc 08 §5). API-key clients are exempt.

    The exemption is keyed on the API-key scheme, not on the mere presence of
    an Authorization header. A browser can be made to send an Authorization
    header it did not choose the value of (a stale `Basic` credential the user
    once entered for the same origin, an extension, a proxy), and any such
    header used to buy a full CSRF bypass on every mutating route. Only
    `Bearer ppk_...` does now, which is a value a cross-site page cannot make
    the browser attach on its own.
    """

    def __init__(self, app, cookie_name: str = "pp_csrf", secure: bool = False):
        super().__init__(app)
        self.cookie_name = cookie_name
        self.secure = secure

    async def dispatch(self, request, call_next):
        auth = request.headers.get("authorization", "")
        if (request.url.path.startswith("/api/") and request.method in MUTATING
                and not auth.startswith(API_KEY_SCHEME)):
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
