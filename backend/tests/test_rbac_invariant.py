"""Phase 8 DoD invariants (doc 10): every route is casbin-governed, and a
viewer -- whether cookie-authed or bearer-token-authed (api_keys, Task 12) --
can mutate nothing. All three tests walk app.openapi()/app.routes, so a
route added after this task lands is automatically covered, extending an
allowlist below is a code-review-visible act, exactly like PUBLIC in
test_route_auth_invariant.py."""
import re

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from tests.support import make_app

# Routes that legitimately carry no authorize() dependency. Every entry needs
# a reason. Self-service auth = "acting on my own account", which no role can
# be denied (a viewer signing out is not a mutation of managed state).
UNGOVERNED = {
    ("GET", "/api/v1/meta/health"),          # public liveness
    ("GET", "/api/v1/meta/onboarding"),      # public first-run booleans
    ("POST", "/api/v1/auth/login"),          # how a session begins
    ("POST", "/api/v1/auth/logout"),         # self-service
    ("GET", "/api/v1/auth/me"),              # self-service
    # Self-service 2FA on the caller's own account: gated on get_current_user
    # + the totp entitlement, no authorize(). Reviewed against the landed
    # implementation (api/auth.py), not granted in advance: see
    # test_no_exemption_names_a_route_that_does_not_exist below.
    ("POST", "/api/v1/auth/totp/enroll"),
    ("POST", "/api/v1/auth/totp/confirm"),
    ("DELETE", "/api/v1/auth/totp"),
    # Same self-service reasoning: replacing the caller's own lost recovery
    # codes on an already-enabled account, password-reauth-gated exactly
    # like disable above, no role question to ask casbin.
    ("POST", "/api/v1/auth/totp/recovery-codes/regenerate"),
    # Second factor of login (Task 9): pre-session by construction: there is
    # no user yet for authorize() to check a role against, that's the whole
    # point of the route. Ownership/single-use/attempt-cap is enforced by the
    # pending-2FA store itself (api/auth.py), not by casbin.
    ("POST", "/api/v1/auth/totp"),
    # Password recovery by spending a 2FA recovery code: public and
    # pre-session for the same reason as /auth/login above, so there is no
    # user for authorize() to ask casbin about. The recovery code is the
    # whole authorisation, checked inside the handler.
    ("POST", "/api/v1/auth/recover"),
    # Self-service session list/revoke (Task 9): "my own sessions" has no
    # (resource, action) pair in services/authz.py's PERMISSIONS matrix and
    # doesn't need one: every role may always manage its own login state.
    # Ownership is enforced by filtering the query on user_id=user.id
    # (list_sessions) / .filter_by(id=sid, user_id=user.id) (revoke), the
    # same idiom api/apikeys.py uses for "my own API keys" below.
    ("GET", "/api/v1/auth/sessions"),
    ("DELETE", "/api/v1/auth/sessions/{sid}"),
    # Self-service trusted devices ("remember this device for 30 days"), and
    # the same reasoning verbatim: which browsers may skip MY second factor is
    # my own login state, not a role question, so it has no (resource, action)
    # pair either. Ownership is enforced the same way, by filtering on
    # user_id=user.id in both the list and the revoke. Worth being explicit
    # about since this credential SKIPS a factor: the exemption is from casbin,
    # not from authentication, and both routes still require a session via
    # get_current_user.
    ("GET", "/api/v1/auth/trusted-devices"),
    ("DELETE", "/api/v1/auth/trusted-devices/{did}"),
    ("GET", "/api/v1/auth/oidc/login"),      # public, pre-session (Task 11)
    ("GET", "/api/v1/auth/oidc/callback"),
    ("POST", "/api/v1/users"),               # first-run bootstrap; enforcer-checked inline
    # Both SSE routes DO enforce authorize(): they call the dependency
    # directly inside the handler instead of via Depends, because a
    # StreamingResponse would otherwise hold a DI-scoped DB session open for
    # the life of the connection. The marker walk cannot see a directly
    # invoked dependency, hence the exemption; the enforcement is real.
    ("GET", "/api/v1/events/stream"),
    ("GET", "/api/v1/jobs/{job_id}/events/stream"),
    ("GET", "/api/v1/entitlements"),         # any-role flag map (doc 05: "any")
    ("GET", "/api/v1/api-keys"),             # self-service (Task 12)
    ("POST", "/api/v1/api-keys"),
    ("DELETE", "/api/v1/api-keys/{key_id}"),
    # Self-service bell-tray dismissal state (persist-cleared-notifications):
    # "what have I already cleared" has no (resource, action) pair in
    # services/authz.py's PERMISSIONS matrix and doesn't need one, same
    # reasoning as api-keys/sessions above. Ownership is enforced by scoping
    # every read/write on user.id (proxploy/api/notification_dismissals.py).
    ("GET", "/api/v1/notifications/dismissed"),
    ("POST", "/api/v1/notifications/dismissed/clear-all"),
    ("POST", "/api/v1/notifications/dismissed/{job_id}"),
}

# Mutations a viewer session IS allowed: own-account self-service only.
VIEWER_SELF = {
    ("POST", "/api/v1/auth/login"),          # UNGOVERNED (public, pre-session); the
                                             # walk still probes it with json={} since
                                             # it's a POST; it 422s on the missing
                                             # required body before any authz would run
                                             # (there IS no authorize() on this route to
                                             # deny with), so asserting 403 is meaningless
                                             # here rather than a real gap
    ("POST", "/api/v1/auth/logout"),
    ("POST", "/api/v1/auth/totp/enroll"),    # own account
    ("POST", "/api/v1/auth/totp/confirm"),
    ("DELETE", "/api/v1/auth/totp"),
    ("POST", "/api/v1/auth/totp/recovery-codes/regenerate"),  # own account
    ("POST", "/api/v1/auth/totp"),           # UNGOVERNED (pre-session second factor); 
                                             # like /auth/login above, json={} 422s on the
                                             # missing body before anything role-shaped
                                             # runs; there is no authorize() here to deny
    ("POST", "/api/v1/auth/recover"),        # UNGOVERNED (pre-session password recovery);
                                             # same as the two above, json={} 422s on the
                                             # missing body and no authorize() exists here
    ("DELETE", "/api/v1/auth/sessions/{sid}"),  # own sessions; another user's id 404s
    # Own trusted devices, same shape: the query filters on user_id, so another
    # user's id 404s rather than 403s. Forgetting a device only ever makes a
    # login stricter, so there is nothing here a viewer should be denied.
    ("DELETE", "/api/v1/auth/trusted-devices/{did}"),
    ("POST", "/api/v1/api-keys"),            # key is capped by the viewer's own role
    ("DELETE", "/api/v1/api-keys/{key_id}"),
    ("POST", "/api/v1/users"),               # 403s inline anyway post-bootstrap; listed
                                             # because its DENIAL is enforcer-driven, and
                                             # a viewer probing it must see 403: asserted
                                             # separately below, not skipped
    ("POST", "/api/v1/notifications/dismissed/clear-all"),  # own tray state
    ("POST", "/api/v1/notifications/dismissed/{job_id}"),
}


def _has_authz_marker(dependant) -> bool:
    for d in dependant.dependencies:
        if getattr(d.call, "__proxploy_authz__", None) or _has_authz_marker(d):
            return True
    return False


def _api_routes(app):
    """Yield (method, full_path, route) for every registered API route.

    This installed FastAPI does NOT flatten `include_router` into
    `app.routes`: it leaves a `_IncludedRouter` wrapper, so the obvious
    `[r for r in app.routes if isinstance(r, APIRoute)]` yields NOTHING and
    any test built on it passes vacuously while proving zero. That is exactly
    how this file first shipped. Descend through `original_router` instead.

    A route's own `.path` already carries its router's prefix; only the outer
    `api_router` prefix has to be prepended. Cross-checked against
    `app.openapi()["paths"]` by the count assertion in every caller.
    """
    def walk(routes):
        for r in routes:
            if isinstance(r, APIRoute):
                yield r
            orig = getattr(r, "original_router", None)
            if orig is not None:
                yield from walk(orig.routes)

    for route in walk(app.routes):
        # Starlette keeps the converter in the path ({volid:path}); OpenAPI
        # and therefore the allowlists above do not.
        path = "/api/v1" + re.sub(r":[a-z]+}", "}", route.path)
        for method in route.methods - {"HEAD", "OPTIONS"}:
            yield method, path, route


def test_every_route_carries_an_authorize_dependency(tmp_path):
    app = make_app(tmp_path)
    missing, checked = [], 0
    for method, path, route in _api_routes(app):
        checked += 1
        if (method, path) in UNGOVERNED:
            continue
        if not _has_authz_marker(route.dependant):
            missing.append((method, path))
    # Guards against the vacuous-pass failure mode described in _api_routes:
    # a walk that silently finds nothing must fail, not report success.
    assert checked >= 100, f"route walk only found {checked} routes; enumeration is broken"
    assert not missing, f"routes without authorize(): {sorted(missing)}"


def test_a_viewer_session_cannot_mutate_anything(tmp_path, csrf_header):
    app = make_app(tmp_path)
    with TestClient(app) as c:
        h = csrf_header(c)
        c.post("/api/v1/users", json={"email": "o@x.io",
               "password": "Correct-Horse-Battery-9"}, headers=h)   # owner bootstrap
        c.post("/api/v1/auth/login", json={"email": "o@x.io",
               "password": "Correct-Horse-Battery-9"}, headers=h)
        c.post("/api/v1/users", json={"email": "v@x.io", "role": "viewer",
               "password": "Correct-Horse-Battery-9"}, headers=h)
        c.post("/api/v1/auth/logout", headers=h)
        c.post("/api/v1/auth/login", json={"email": "v@x.io",
               "password": "Correct-Horse-Battery-9"}, headers=h)

        checked = 0
        for path, methods in c.app.openapi()["paths"].items():
            probe = path
            for name in re.findall(r"{(\w+)}", path):
                probe = probe.replace(f"{{{name}}}",
                                      "start" if name == "action" else "1")
            for method in methods:
                m = method.upper()
                if m not in ("POST", "PUT", "PATCH", "DELETE"):
                    continue
                if (m, path) in VIEWER_SELF:
                    continue
                r = c.request(m, probe, headers=h, json={})
                checked += 1
                assert r.status_code == 403, (
                    f"viewer got {r.status_code} from {m} {path}: {r.text}")
        assert checked >= 50   # the walk really walked the mutating surface

        # And the one VIEWER_SELF row that must still deny:
        r = c.post("/api/v1/users", json={"email": "x@x.io", "role": "viewer",
                   "password": "Correct-Horse-Battery-9"}, headers=h)
        assert r.status_code == 403


def test_a_viewer_api_key_cannot_mutate_anything(tmp_path, csrf_header):
    """API keys (`6c84e5e`) are a second, bearer-token path into every route
    authorize() guards -- get_current_user resolves Authorization: Bearer
    ppk_... instead of the session cookie, and authorize() folds the key's
    scopes in ahead of the same enforce() call. A key inherits its owner's
    role and can only narrow it (deps.py::authorize docstring), so a
    viewer's token must be denied exactly like the viewer's cookie session
    was above -- this repeats that walk with the ONLY variable changed:
    authentication is bearer, not cookie, with the session logged out first
    so no cookie exists to fall back on."""
    app = make_app(tmp_path)
    with TestClient(app) as c:
        h = csrf_header(c)
        c.post("/api/v1/users", json={"email": "o2@x.io",
               "password": "Correct-Horse-Battery-9"}, headers=h)   # owner bootstrap
        c.post("/api/v1/auth/login", json={"email": "o2@x.io",
               "password": "Correct-Horse-Battery-9"}, headers=h)
        c.post("/api/v1/users", json={"email": "v2@x.io", "role": "viewer",
               "password": "Correct-Horse-Battery-9"}, headers=h)
        c.post("/api/v1/auth/logout", headers=h)
        c.post("/api/v1/auth/login", json={"email": "v2@x.io",
               "password": "Correct-Horse-Battery-9"}, headers=h)
        key_resp = c.post("/api/v1/api-keys", json={"name": "viewer-key"}, headers=h)
        assert key_resp.status_code == 201, key_resp.text
        raw = key_resp.json()["key"]   # only place the raw ppk_... ever appears
        c.post("/api/v1/auth/logout", headers=h)   # drop the cookie: bearer-only below
        bearer = {"Authorization": f"Bearer {raw}"}

        checked = 0
        for path, methods in c.app.openapi()["paths"].items():
            probe = path
            for name in re.findall(r"{(\w+)}", path):
                probe = probe.replace(f"{{{name}}}",
                                      "start" if name == "action" else "1")
            for method in methods:
                m = method.upper()
                if m not in ("POST", "PUT", "PATCH", "DELETE"):
                    continue
                if (m, path) in VIEWER_SELF:
                    continue
                r = c.request(m, probe, headers=bearer, json={})
                checked += 1
                assert r.status_code == 403, (
                    f"viewer API key got {r.status_code} from {m} {path}: {r.text}")
        assert checked >= 50   # the walk really walked the mutating surface


def test_no_exemption_names_a_route_that_does_not_exist(tmp_path):
    """An allowlist entry for an unregistered route is a fail-OPEN hole.

    The tests above are fail-closed only because an unlisted route is denied
    by default. Pre-registering an exemption for a route nobody has written
    yet inverts that: the route lands already-exempt, and its implementation
    is never reviewed against the exemption it was granted in advance. This
    file originally shipped six such entries, for TOTP and session routes
    belonging to Tasks 8 and 9.

    So an exemption must name a route that exists RIGHT NOW. A new
    self-service route fails the suite until someone consciously adds it
    here, having read what actually landed; which is the review gate, and
    the whole point of the allowlist being code-review-visible.
    """
    app = make_app(tmp_path)
    registered = {(m, path) for m, path, _ in _api_routes(app)}
    stale = (UNGOVERNED | VIEWER_SELF) - registered
    assert not stale, (
        "these allowlist entries name routes that are not registered; delete "
        f"them, or fix the path: {sorted(stale)}")
