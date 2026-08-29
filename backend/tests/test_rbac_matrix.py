"""The whole role ladder against the whole route surface.

test_rbac_invariant.py proves two ends of the ladder: every route carries an
authorize() dependency, and a viewer can mutate nothing. Between those lies
the part nobody exercised. There are four roles and PERMISSIONS grades actions
across all four, so the boundaries that decide privilege ESCALATION are
operator -> admin and admin -> owner, and neither had a test.

Those boundaries are not academic. `host.credentials` (rotate stored secrets)
and `host.power` (reboot the node) are owner-only, and `app.install` is
admin-only because it runs a community script as root over SSH. An off-by-one
in that table, or a route wired to the wrong pair, hands one of those to a rung
that should not reach it, and the viewer test would still pass.

This walks every registered route, recovers the (resource, action) pair from
the authorize() dependency's own marker, looks up the rank the table demands,
and asserts each role is refused exactly when it is outranked. Data-driven on
purpose: a route added later is covered the day it lands, and a permission
moved between rungs shows up here rather than in production.
"""
import re

import pytest
from fastapi.testclient import TestClient

from proxploy.api.deps import ROLE_ORDER
from proxploy.services.authz import PERMISSIONS
from tests.support import make_app

PASSWORD = "Correct-Horse-Battery-9"

# Acting on your own account is never a role question, so these carry no
# authorize() and are not part of the matrix. Same list, same reasoning as
# test_rbac_invariant.py's VIEWER_SELF; kept local so neither file's
# allowlist can quietly widen the other's.
SELF_SERVICE = {"/api/v1/auth/logout", "/api/v1/auth/totp",
                "/api/v1/auth/totp/enroll", "/api/v1/auth/totp/confirm",
                "/api/v1/auth/totp/recovery-codes/regenerate",
                "/api/v1/auth/recover", "/api/v1/auth/login",
                "/api/v1/auth/sessions", "/api/v1/users"}


def _authz_pair(dependant):
    for d in dependant.dependencies:
        pair = getattr(d.call, "__proxploy_authz__", None)
        if pair:
            return pair
        found = _authz_pair(d)
        if found:
            return found
    return None


def _api_routes(app):
    """Every registered API route, with its authorize() pair.

    Descends `original_router` for the reason test_rbac_invariant.py records:
    this FastAPI leaves an `_IncludedRouter` wrapper in app.routes, so the
    obvious isinstance walk yields nothing and passes vacuously.
    """
    out = []

    def walk(routes):
        for r in routes:
            if hasattr(r, "dependant") and getattr(r, "methods", None):
                pair = _authz_pair(r.dependant)
                if pair is not None:
                    # "/api/v1" is the outer api_router prefix, which a route's
                    # own .path does not carry. Starlette keeps the converter
                    # in the path ({volid:path}); strip it so a probe URL and
                    # the allowlists agree, exactly as test_rbac_invariant does.
                    path = "/api/v1" + re.sub(r":[a-z]+}", "}", r.path)
                    for m in r.methods - {"HEAD", "OPTIONS"}:
                        out.append((m, path, pair))
            inner = getattr(r, "original_router", None)
            if inner is not None:
                walk(inner.routes)

    walk(app.routes)
    return out


def _denied_by_role(response):
    """A 403 from authorize(), not from require_entitlement().

    Both refuse with 403 and the matrix has to tell them apart: on a free
    install app.migrate answers 403 to an OWNER, because the licence does not
    include it, which says nothing about the role ladder. entitlement_error()
    in api/deps.py gives every entitlement denial the same body, so the
    distinction is readable rather than guessed at.
    """
    if response.status_code != 403:
        return False
    try:
        body = response.json()
    except ValueError:
        return True
    detail = body.get("detail", body) if isinstance(body, dict) else body
    if isinstance(detail, dict) and detail.get("error") == "entitlement_required":
        return False
    return True


def _probe_path(path):
    for name in re.findall(r"{(\w+)}", path):
        path = path.replace(f"{{{name}}}", "start" if name == "action" else "1")
    return path


@pytest.fixture
def laddered(tmp_path, csrf_header):
    """One app with a user at every rung, and a client logged in as each."""
    app = make_app(tmp_path)
    with TestClient(app) as c:
        h = csrf_header(c)
        c.post("/api/v1/users", json={"email": "owner@x.io", "password": PASSWORD},
               headers=h)
        c.post("/api/v1/auth/login", json={"email": "owner@x.io", "password": PASSWORD},
               headers=h)
        for role in ("admin", "operator", "viewer"):
            r = c.post("/api/v1/users",
                       json={"email": f"{role}@x.io", "role": role, "password": PASSWORD},
                       headers=h)
            assert r.status_code in (200, 201), f"seeding {role} failed: {r.text}"
        c.post("/api/v1/auth/logout", headers=h)
        yield app, c, h


def _login(c, h, role):
    email = "owner@x.io" if role == "owner" else f"{role}@x.io"
    c.post("/api/v1/auth/logout", headers=h)
    r = c.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD},
               headers=h)
    assert r.status_code == 200, f"login as {role} failed: {r.text}"


@pytest.mark.parametrize("role", ["viewer", "operator", "admin"])
def test_a_role_is_refused_exactly_what_the_table_puts_above_it(laddered, role):
    """Every route whose pair outranks `role` must answer 403, and no route
    at or below it may. The second half is what stops this test passing by
    denying everything, which would be a matrix that proves nothing."""
    app, c, h = laddered
    _login(c, h, role)
    rank = ROLE_ORDER[role]

    wrongly_allowed, wrongly_denied, checked = [], [], 0
    for method, path, pair in _api_routes(app):
        if method not in ("POST", "PUT", "PATCH", "DELETE"):
            continue
        if path in SELF_SERVICE:
            continue
        required = PERMISSIONS.get(pair)
        if required is None:
            continue
        checked += 1
        r = c.request(method, _probe_path(path), headers=h, json={})
        outranked = rank < ROLE_ORDER[required]
        if outranked and r.status_code != 403:
            wrongly_allowed.append((method, path, pair, required, r.status_code))
        # A permitted route may fail for any downstream reason (404, 422, 409,
        # a missing host, or a licence that does not include the feature). What
        # it must never do is refuse on the ROLE, which would mean the ladder
        # denied a rung the table grants.
        if not outranked and _denied_by_role(r):
            wrongly_denied.append((method, path, pair, required))

    assert checked >= 40, f"route walk found only {checked} governed mutations"
    assert not wrongly_allowed, (
        f"{role} reached routes the table puts above it: {sorted(wrongly_allowed)}")
    assert not wrongly_denied, (
        f"{role} was refused routes the table grants it: {sorted(wrongly_denied)}")


def test_the_owner_only_actions_are_reachable_by_nobody_below_owner(laddered):
    """The three that matter most, named rather than swept up in the walk, so
    a change to them fails with their own name on it: rotating stored host
    credentials, powering the node off, and destroying a VM."""
    app, c, h = laddered
    owner_only = [p for p, min_role in PERMISSIONS.items() if min_role == "owner"]
    assert ("host", "credentials") in owner_only
    assert ("host", "power") in owner_only

    routes = [(m, p, pair) for m, p, pair in _api_routes(app)
              if pair in owner_only and m in ("POST", "PUT", "PATCH", "DELETE")]
    assert routes, "no owner-only mutating route found; the walk is broken"

    for role in ("viewer", "operator", "admin"):
        _login(c, h, role)
        for method, path, pair in routes:
            r = c.request(method, _probe_path(path), headers=h, json={})
            assert r.status_code == 403, (
                f"{role} reached owner-only {pair} via {method} {path}: {r.status_code}")


# Pairs in PERMISSIONS that no authorize() call names. Each is deliberate and
# already reasoned about in authz.py itself; they are listed again here so a
# NEW orphan fails. A route that silently loses its guard adds one of these,
# and that is the case worth catching: the matrix above can only test a pair
# it can find a route for, so an unexplained orphan is coverage quietly
# disappearing.
#
# None of the three is a privilege discrepancy. Each sits at the same rank as
# the pair its route actually enforces, so nothing is reachable by a rung the
# table would have refused.
UNWIRED = {
    # GET /audit/export is gated on ("audit", "read"), which is also "admin".
    ("audit", "export"),
    # Self-update; authz.py marks the route as not built yet.
    ("meta", "update"),
    # Guest network config is enforced as app.configure / vm.configure, both
    # "operator", the same rank this pair carries.
    ("network", "guest"),
}


def test_every_permission_pair_is_wired_to_a_route_or_is_a_known_orphan(laddered):
    """A pair with no route behind it is either dead weight or a route that
    lost its guard, and the matrix above stops covering it either way."""
    app, _, _ = laddered
    wired = {pair for _, _, pair in _api_routes(app)}
    orphaned = sorted(set(PERMISSIONS) - wired - UNWIRED)
    assert not orphaned, f"permission pairs with no route: {orphaned}"

    # And the allowlist may not outlive what it excuses: a pair listed here
    # that has since gained a route, or left the table, is stale.
    stale = sorted((UNWIRED & wired) | (UNWIRED - set(PERMISSIONS)))
    assert not stale, f"UNWIRED names pairs that are wired or gone: {stale}"
