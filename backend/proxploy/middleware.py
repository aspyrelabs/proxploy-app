import hmac
import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

MUTATING = {"POST", "PUT", "PATCH", "DELETE"}


# Byte-for-byte what api/deps.py::current_user accepts, so a header that
# skips CSRF here cannot then fail to authenticate there, or the reverse.
API_KEY_SCHEME = "Bearer ppk_"


class CSRFMiddleware(BaseHTTPMiddleware):
    """Double-submit CSRF. API-key clients exempt, keyed on the scheme
    (`Bearer ppk_...`), not on the presence of any Authorization header: a
    browser can attach a header it did not choose (stale Basic, an extension,
    a proxy), which would otherwise buy a CSRF bypass on every mutating route.
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
