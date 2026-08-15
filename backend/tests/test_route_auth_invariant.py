"""Behavioural invariant, not a per-router regression test (final Phase 3 fix
wave, item 8): a bare `Depends(require_entitlement(k))` in a route's
`dependencies=[...]` list lands at position 0 of the dependant tree and runs
BEFORE auth, so an anonymous caller gets a 403 (leaking which feature flags
are armed) instead of a 401. This exact bug recurred in four separate
routers (jobs.py, apps.py, vms.py, notifications.py, each carries a
"ROUTE TEMPLATE" comment pointing back at it) before being fixed by listing
`require_role`/`get_current_user` ahead of `require_entitlement` on every
gated route.

Four hand-written per-router tests caught it four times. This one walks
every route FastAPI actually registered and replaces all four: a brand-new
router is wrong by default the moment it 403s an anonymous caller, unless
someone deliberately adds it to PUBLIC below, a code-review-visible act,
unlike a missing regression test nobody thought to write.
"""
import re

from fastapi.testclient import TestClient

# Routes that legitimately answer a session-less caller with something other
# than 401: but NEVER with 403 (403 is reserved for "you have a session but
# lack the role/entitlement"; an anonymous caller has no role or entitlement
# state to leak in the first place). Keep this allowlist short and comment
# each entry: anything not listed here is assumed to require a session.
PUBLIC = {
    ("GET", "/api/v1/meta/health"),      # liveness probe, must work unauthenticated
    ("GET", "/api/v1/meta/onboarding"),  # "does an admin exist yet", "is setup
                                          # finished", "draw the SSO button": the
                                          # three booleans the login page and step 1
                                          # of the wizard need pre-login, and the only
                                          # three it answers a session-less caller
                                          # with. Host and SSH state is added for a
                                          # signed-in caller only (api/meta.py).
    ("POST", "/api/v1/auth/login"),      # how a caller gets a session in the first place
    ("POST", "/api/v1/users"),           # first-run owner bootstrap (doc 08 §8), every
                                          # call after the first user exists 401s instead
                                          # (auth.py::create_user checks this itself,
                                          # not via a FastAPI dependency)
    ("GET", "/api/v1/auth/oidc/login"),    # how an anonymous caller starts SSO in the
                                            # first place; answers 404 when unconfigured/
                                            # not entitled, never 403 (doc 10 Task 11)
    ("GET", "/api/v1/auth/oidc/callback"), # IdP redirects here with no session cookie
                                            # yet: this route is what mints the session
    ("POST", "/api/v1/auth/totp"),         # second factor of login; pre-session by
                                            # definition (Task 9). No get_current_user
                                            # dependency exists to 401 an anonymous caller;
                                            # a bad/missing pending+code pair 422s or 401s
                                            # from inside the handler, never leaks a 403.
}


def test_no_gated_route_answers_403_to_an_anonymous_caller(tmp_path, csrf_header):
    """Walks every registered route. A new router is wrong by default until
    someone adds it to PUBLIC, which is a code-review-visible act."""
    from tests.support import make_app

    app = make_app(tmp_path)
    with TestClient(app) as c:
        h = csrf_header(c)  # clears the unrelated CSRF gate; not a session
        # Every entitlement flag resolves ON by default (builtin tier), which
        # means require_entitlement()'s dep() never actually raises and the
        # ordering bug this test exists to catch never fires either way, 
        # false green. Blanket-disable every flag (enabled() falls back to
        # False for any key not in the dict) so every gated route's
        # entitlement check is live for this walk, same as the per-router
        # tests that flip one flag at a time (e.g.
        # test_notifications_api.py::test_entitlement_gate_runs_after_auth_not_before).
        c.app.state.entitlements._features = {}
        paths = app.openapi()["paths"]
        checked = []
        for path, methods in paths.items():
            probe_path = path
            for name in re.findall(r"{(\w+)}", path):
                # every path param in this API is either a numeric id or the
                # `action` verb on a lifecycle route: both need a value that
                # actually reaches the handler (a non-parsing value would
                # 422 out of routing before any dependency runs).
                probe_path = probe_path.replace(f"{{{name}}}",
                                                "start" if name == "action" else "1")
            for method in methods:
                method = method.upper()
                if method not in ("GET", "POST", "PUT", "PATCH", "DELETE"):
                    continue
                kwargs = {"headers": h} if method != "GET" else {}
                if method in ("POST", "PUT", "PATCH"):
                    kwargs["json"] = {}
                r = c.request(method, probe_path, **kwargs)
                checked.append((method, path))
                if (method, path) not in PUBLIC:
                    assert r.status_code == 401, (
                        f"{method} {path} answered an anonymous caller with "
                        f"{r.status_code} (expected 401, or add it to PUBLIC "
                        f"with a reason): {r.text}")
        # Sanity: the walk actually walked the API, not an empty schema.
        assert len(checked) >= 30
        assert any(m == "GET" and p == "/api/v1/jobs" for m, p in checked)
