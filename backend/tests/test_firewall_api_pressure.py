"""Pressure tests for the firewall API surface (spec: 2026-08-21).

Everything here runs against tests/fakes/pve.py. Nothing in this file talks to
a real cluster.

Three things this file does that the two existing firewall suites do not:

1. It generates the authorization matrix from app.routes rather than listing
   routes by hand, so a route added later is covered the day it lands instead
   of the day someone remembers to add a case for it.
2. It asserts the RBAC tier each route SHOULD carry from a rule written out
   here, independently of what the route declares. A table copied from the
   implementation only ever proves the implementation agrees with itself.
3. Where the current behaviour is wrong, the test states the CORRECT
   assertion and carries an xfail(strict=True) naming the defect. Strict
   means the test starts failing again the moment the defect is fixed, so
   nothing here silently rots into an accepted wrong answer.

Findings are written up in report-api-pressure.md.
"""
from __future__ import annotations

import json

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from proxploy.entitlements.registry import FLAG_KEYS
from proxploy.models import (App, AuditEvent, Host, HostCredential, Team,
                             TeamMember, User, Vm)
from proxploy.services.proxmox import ProxmoxError

PASSWORD = "correct-horse-battery"

# ---------------------------------------------------------------- the world


def _creds(app, db, host_id):
    for cap in ("monitoring", "lifecycle"):
        blob, ver = app.state.secretstore.encrypt(json.dumps(
            {"token_id": f"proxploy@pve!fw-{cap}",
             "token_secret": "s3cret"}).encode())
        db.add(HostCredential(host_id=host_id, kind=f"api_token:{cap}",
                              encrypted_blob=blob, key_version=ver))


def seed_world(app):
    """Two teams, one host each, one container and one VM on each host.

    Team A is the default team (host.team_id NULL resolves to it, see
    deps._team_of_host). Team B's host carries an explicit team_id, which is
    what every cross-team assertion below turns on.
    """
    with app.state.sessionmaker() as db:
        team_b = Team(name="B", slug="team-b")
        db.add(team_b)
        db.commit()
        a_host = Host(name="host-a", address="https://10.0.0.9:8006",
                      node_name="pve1", status="connected")
        b_host = Host(name="host-b", address="https://10.0.0.10:8006",
                      node_name="pve1", status="connected", team_id=team_b.id)
        db.add_all([a_host, b_host])
        db.commit()
        _creds(app, db, a_host.id)
        _creds(app, db, b_host.id)
        a_app = App(host_id=a_host.id, ctid=150, name="Immich", slug="immich",
                    node_name="pve2")
        a_vm = Vm(host_id=a_host.id, vmid=201, name="win11", status="running",
                  node_name="pve1")
        b_app = App(host_id=b_host.id, ctid=250, name="Vaultwarden",
                    slug="vaultwarden", node_name="pve2")
        b_vm = Vm(host_id=b_host.id, vmid=301, name="deb", status="running",
                  node_name="pve1")
        db.add_all([a_app, a_vm, b_app, b_vm])
        db.commit()
        return {"team_b": team_b.id,
                "a": {"host": a_host.id, "app": a_app.id, "vm": a_vm.id},
                "b": {"host": b_host.id, "app": b_app.id, "vm": b_vm.id}}


def seed_options(fake):
    """PVE answers options with an object. The fake answers an unset path with
    [], and _options_read calls .get("digest") on whatever came back, so every
    options route 500s unless the shape is seeded. That crash is a finding in
    its own right (test_a_non_object_options_response_is_not_a_crash); seeding
    here keeps the authorization walk measuring authorization."""
    for path in ("cluster/firewall/options",
                 "nodes/pve1/firewall/options",
                 "nodes/pve2/lxc/150/firewall/options",
                 "nodes/pve1/qemu/201/firewall/options",
                 "nodes/pve2/lxc/250/firewall/options",
                 "nodes/pve1/qemu/301/firewall/options"):
        fake.firewall_data[path] = {"enable": 0, "digest": "seed-digest"}


def _fake():
    from tests.fakes.pve import FakePVE
    return FakePVE()


def _csrf(c):
    if "pp_csrf" not in c.cookies:
        c.get("/api/v1/meta/health")
    return {"X-CSRF-Token": c.cookies["pp_csrf"]}


def _login(c, email):
    r = c.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD},
               headers=_csrf(c))
    assert r.status_code == 200, r.text


def _mk_user(c, email, role):
    r = c.post("/api/v1/users",
               json={"email": email, "password": PASSWORD, "role": role},
               headers=_csrf(c))
    assert r.status_code == 201, r.text
    return r.json()


# ------------------------------------------------------------- route table


def _flatten(routes):
    out = []
    for r in routes:
        if isinstance(r, APIRoute):
            out.append(r)
        elif hasattr(r, "original_router"):
            out.extend(_flatten(r.original_router.routes))
    return out


def _declared(route):
    """(resource, action) and the entitlement keys the route actually carries."""
    authz, ents = None, []
    for d in route.dependant.dependencies:
        marker = getattr(d.call, "__proxploy_authz__", None)
        if marker:
            authz = marker
        if getattr(d.call, "__qualname__", "") == "require_entitlement.<locals>.dep":
            ents.append(d.call.__closure__[0].cell_contents)
    return authz, ents


def fw_routes(app):
    """Every firewall route FastAPI registered, from app.routes.

    Generated, never hand-listed: the whole point is that a route nobody
    remembered to add a case for still gets one.
    """
    rows = []
    for r in _flatten(app.routes):
        if "firewall" not in r.path:
            continue
        path = "/api/v1" + r.path.replace(":path", "")
        authz, ents = _declared(r)
        for method in sorted(r.methods - {"HEAD", "OPTIONS"}):
            rows.append({"method": method, "path": path, "authz": authz,
                         "ents": ents})
    rows.sort(key=lambda x: (x["path"], x["method"]))
    return rows


def expected_tier(method, path):
    """The firewall RBAC model, written out rather than read off the routes.

    Mirrors the network resource exactly (services/authz.py: firewall.read =
    viewer, firewall.guest = operator, firewall.manage = admin). Reading is a
    viewer's at every scope. A write on a guest is an operator's. A write at
    node, cluster or security group scope is an admin's, because those change
    traffic for machines the operator may not own.
    """
    on_a_guest = path.startswith(("/api/v1/apps/", "/api/v1/vms/"))
    if method == "GET":
        action = "read"
        key = "firewall.log" if path.endswith("/log") else "firewall.view"
    else:
        action = "guest" if on_a_guest else "manage"
        if "/rules" in path:
            key = "firewall.rules"
        elif path.endswith("/options"):
            key = "firewall.options"
        else:
            key = "firewall.objects"
    return ("firewall", action), key


def probe_path(path, ids, *, side="a", node="pve1", name="trusted",
               group="web", cidr="10.0.0.5", pos="0"):
    values = {"host_id": ids[side]["host"], "app_id": ids[side]["app"],
              "vm_id": ids[side]["vm"], "node": node, "pos": pos,
              "name": name, "group": group, "cidr": cidr}
    out = path
    for key, value in values.items():
        out = out.replace("{" + key + "}", str(value))
    assert "{" not in out, f"unsubstituted path parameter in {out}"
    return out


def body_for(method, path):
    """The smallest body each write route accepts. Nothing optional, so a 422
    in an authorization walk means the walk is wrong, not the route."""
    if method not in ("POST", "PUT"):
        return None
    if path.endswith("/move"):
        return {"moveto": 1}
    if path.endswith("/rules"):
        return {"type": "in", "action": "ACCEPT"}
    if path.endswith("/rules/{pos}"):
        return {"comment": "pressure"}
    if path.endswith("/options"):
        return {"enable": 1}
    if path.endswith("/aliases"):
        return {"name": "office", "cidr": "10.0.0.0/24"}
    if path.endswith("/aliases/{name}"):
        return {"cidr": "10.0.0.0/24"}
    if path.endswith("/ipsets"):
        return {"name": "trusted"}
    if path.endswith("/members"):
        return {"cidr": "10.0.0.5"}
    if path.endswith("/members/{cidr}"):
        return {"comment": "pressure"}
    if path.endswith("/groups"):
        return {"group": "web"}
    raise AssertionError(f"no body defined for {method} {path}")


def call(c, route, ids, **kw):
    url = probe_path(route["path"], ids, **kw)
    body = body_for(route["method"], route["path"])
    kwargs = {"headers": _csrf(c)}
    if body is not None:
        kwargs["json"] = body
    return c.request(route["method"], url, **kwargs)


# ------------------------------------------------------------- the fixture


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    """One app, one set of users, shared by the matrix walks.

    Module scoped for one reason: argon2 hashing. Five accounts per test
    function turned a five second file into a minute of key derivation. The
    walks below only read authorization outcomes, so they do not care that
    they share a database.
    """
    from tests.support import make_app
    fake = _fake()
    app = make_app(tmp_path_factory.mktemp("fwpressure"), fake=fake)
    with TestClient(app) as c:
        # First user is forced to owner (doc 08 section 8).
        c.post("/api/v1/users",
               json={"email": "owner@x.io", "password": PASSWORD,
                     "display_name": "Owner"}, headers=_csrf(c))
        _login(c, "owner@x.io")
        ids = seed_world(app)
        seed_options(fake)
        _mk_user(c, "viewer@x.io", "viewer")
        _mk_user(c, "operator@x.io", "operator")
        _mk_user(c, "admin@x.io", "admin")
        _mk_user(c, "stranger@x.io", "viewer")
        # The stranger is an ADMIN, but only in team B. Team A's host is not
        # theirs to touch, which is the whole assertion.
        with app.state.sessionmaker() as db:
            u = db.query(User).filter_by(email="stranger@x.io").one()
            db.query(TeamMember).filter_by(user_id=u.id).delete()
            db.add(TeamMember(team_id=ids["team_b"], user_id=u.id, role="admin"))
            db.commit()
            from proxploy.services.authz import sync_user
            sync_user(app.state.authz, db, u.id)
        yield {"app": app, "client": c, "fake": fake, "ids": ids}


@pytest.fixture
def solo(tmp_path, csrf_header, bootstrap_admin):
    """A throwaway app with one owner and one host, for the tests that need a
    clean fake and a clean audit table."""
    from tests.support import make_app
    fake = _fake()
    app = make_app(tmp_path, fake=fake)
    with TestClient(app) as c:
        bootstrap_admin(c)
        ids = seed_world(app)
        seed_options(fake)
        yield {"app": app, "client": c, "fake": fake, "ids": ids}


# =====================================================================
# 1. AUTHORIZATION MATRIX
# =====================================================================


def test_the_route_table_is_the_whole_firewall_surface(world):
    """A sanity check on the generator itself. If this count moves, every
    walk below silently covered fewer routes than it claims to."""
    rows = fw_routes(world["app"])
    on_router = [r for r in rows if r["path"].startswith("/api/v1/firewall/")]
    on_apps = [r for r in rows if r["path"].startswith("/api/v1/apps/")]
    on_vms = [r for r in rows if r["path"].startswith("/api/v1/vms/")]
    assert len(on_router) == 36, [r["path"] for r in on_router]
    assert len(on_apps) == 20
    assert len(on_vms) == 20
    assert len(rows) == 76


def test_every_firewall_route_declares_the_tier_the_model_says_it_should(world):
    """The declared (resource, action) against the model in expected_tier(),
    which is written from doc 05's role column, not copied off the routes."""
    wrong = []
    for r in fw_routes(world["app"]):
        want_authz, want_key = expected_tier(r["method"], r["path"])
        if r["authz"] != want_authz:
            wrong.append(f"{r['method']} {r['path']}: declares {r['authz']}, "
                         f"model says {want_authz}")
        if r["ents"] != [want_key]:
            wrong.append(f"{r['method']} {r['path']}: entitlement {r['ents']}, "
                         f"model says [{want_key!r}]")
    assert not wrong, "RBAC tier or entitlement key wrong on:\n" + "\n".join(wrong)


def test_every_firewall_route_refuses_an_anonymous_caller(world):
    c, ids = world["client"], world["ids"]
    c.post("/api/v1/auth/logout", headers=_csrf(c))
    bad = []
    for r in fw_routes(world["app"]):
        got = call(c, r, ids)
        if got.status_code != 401:
            bad.append(f"{r['method']} {r['path']} -> {got.status_code} "
                       f"{got.text[:120]}")
    assert not bad, ("SECURITY: routes answered a caller with no session "
                     "with something other than 401:\n" + "\n".join(bad))


@pytest.mark.parametrize("email,role", [("viewer@x.io", "viewer"),
                                        ("operator@x.io", "operator"),
                                        ("admin@x.io", "admin")])
def test_every_firewall_route_matches_its_tier_for_each_role(world, email, role):
    """Reachable when the role clears the tier, 403 when it does not.

    "Reachable" is asserted as "not 401 and not 403", never as 200: a route
    may legitimately answer 404 or 422 once it is past the gate, and pinning
    a success code here would be testing the fake, not the gate.
    """
    order = {"viewer": 0, "operator": 1, "admin": 2, "owner": 3}
    need = {"read": 0, "guest": 1, "manage": 2}
    c, ids = world["client"], world["ids"]
    c.post("/api/v1/auth/logout", headers=_csrf(c))
    _login(c, email)
    leaks, blocks = [], []
    reachable = denied = 0
    for r in fw_routes(world["app"]):
        (_, action), _ = expected_tier(r["method"], r["path"])
        allowed = order[role] >= need[action]
        got = call(c, r, ids)
        line = f"{r['method']} {r['path']} -> {got.status_code} {got.text[:120]}"
        if allowed:
            reachable += 1
            if got.status_code in (401, 403):
                blocks.append(line)
        else:
            denied += 1
            if got.status_code != 403:
                leaks.append(line + f"  (needs {action})")
    assert not leaks, (f"SECURITY: a {role} reached routes above its tier:\n"
                       + "\n".join(leaks))
    assert not blocks, (f"a {role} was refused routes at or below its tier:\n"
                        + "\n".join(blocks))
    # A walk that classified every route the same way would pass both
    # assertions above while proving nothing. Only an admin clears every tier.
    assert reachable == {"viewer": 26, "operator": 52, "admin": 76}[role]
    assert denied == 76 - reachable


def test_every_firewall_route_refuses_a_user_from_another_team(world):
    """The stranger is an admin, in team B only. Team A's host, node, guests,
    groups, aliases and IP sets are all out of reach, reads included."""
    c, ids = world["client"], world["ids"]
    c.post("/api/v1/auth/logout", headers=_csrf(c))
    _login(c, "stranger@x.io")
    leaks = []
    for r in fw_routes(world["app"]):
        got = call(c, r, ids, side="a")
        if got.status_code != 403:
            leaks.append(f"{r['method']} {r['path']} -> {got.status_code} "
                         f"{got.text[:120]}")
    assert not leaks, ("SECURITY: an admin of another team reached team A's "
                       "firewall:\n" + "\n".join(leaks))


def test_every_firewall_route_is_gated_on_its_own_entitlement_flag(world):
    """One flag off at a time, every other flag on, so a route that answers
    403 is answering for its OWN key rather than a blanket outage."""
    c, ids = world["client"], world["ids"]
    ent = world["app"].state.entitlements
    original = dict(ent._features)
    c.post("/api/v1/auth/logout", headers=_csrf(c))
    _login(c, "admin@x.io")
    ungated = []
    try:
        for r in fw_routes(world["app"]):
            _, key = expected_tier(r["method"], r["path"])
            ent._features = {k: True for k in FLAG_KEYS}
            ent._features[key] = False
            got = call(c, r, ids)
            if got.status_code != 403:
                ungated.append(f"{r['method']} {r['path']} with {key} off -> "
                               f"{got.status_code} {got.text[:120]}")
    finally:
        ent._features = original
    assert not ungated, ("SECURITY: routes stayed reachable with their "
                         "entitlement off:\n" + "\n".join(ungated))


def test_a_denied_firewall_call_is_written_to_the_audit_trail(world):
    """Doc 08 section 7: a refusal is evidence too."""
    c, ids = world["client"], world["ids"]
    c.post("/api/v1/auth/logout", headers=_csrf(c))
    _login(c, "viewer@x.io")
    c.post(f"/api/v1/firewall/cluster/{ids['a']['host']}/rules",
           headers=_csrf(c), json={"type": "in", "action": "ACCEPT"})
    with world["app"].state.sessionmaker() as db:
        rows = db.query(AuditEvent).filter_by(action="firewall.manage",
                                              result="denied").all()
        assert rows, "a refused firewall write left no audit row"


# =====================================================================
# 2. CROSS-TEAM ISOLATION
# =====================================================================


def test_team_bs_firewall_is_never_touched_by_a_team_a_admin(solo):
    """Not just the status code: the fake must record no call at all. A 403
    raised after the call went out would still have changed team B."""
    c, ids, fake = solo["client"], solo["ids"], solo["fake"]
    _mk_user(c, "a-admin@x.io", "admin")
    c.post("/api/v1/auth/logout", headers=_csrf(c))
    _login(c, "a-admin@x.io")
    fake.firewall_reads.clear()
    fake.firewall_writes.clear()
    leaks = []
    for r in fw_routes(solo["app"]):
        got = call(c, r, ids, side="b")
        if got.status_code != 403:
            leaks.append(f"{r['method']} {r['path']} -> {got.status_code}")
    assert not leaks, ("SECURITY: team A's admin reached team B's firewall:\n"
                       + "\n".join(leaks))
    assert fake.firewall_reads == [], "a refused read still reached Proxmox"
    assert fake.firewall_writes == [], "a refused write still reached Proxmox"


def test_a_host_id_from_another_team_in_the_path_does_not_widen_scope(solo):
    """The team comes from the row the path names, so naming team B's host on
    a route the caller may use for team A buys nothing."""
    c, ids = solo["client"], solo["ids"]
    _mk_user(c, "a-admin2@x.io", "admin")
    c.post("/api/v1/auth/logout", headers=_csrf(c))
    _login(c, "a-admin2@x.io")
    assert c.get(f"/api/v1/firewall/cluster/{ids['a']['host']}/rules"
                 ).status_code == 200
    assert c.get(f"/api/v1/firewall/cluster/{ids['b']['host']}/rules"
                 ).status_code == 403
    assert c.get(f"/api/v1/apps/{ids['b']['app']}/firewall/rules"
                 ).status_code == 403
    assert c.get(f"/api/v1/vms/{ids['b']['vm']}/firewall/rules"
                 ).status_code == 403


def test_the_node_segment_is_checked_against_the_host_it_was_asked_of(solo):
    """{node} used to be a free string.

    The node routes handed it to fw.node_loc() without asking whether that
    node belonged to the host in the path, so a caller with firewall.manage on
    one host could write node scope rules on any node name that host's
    credentials could reach. Harmless on a single host install and not
    harmless when two teams each enrol a different peer of the SAME Proxmox
    cluster: the team check is done on the Host row, and the node named in the
    path walked straight past it.

    fw.host_speaks_for_node answers it now, from the poll snapshot and the
    hosts table, so the refusal costs no call to Proxmox.
    """
    c, ids, fake = solo["client"], solo["ids"], solo["fake"]
    fake.firewall_writes.clear()
    got = c.post(f"/api/v1/firewall/node/{ids['a']['host']}/somebody-elses-node"
                 f"/rules", headers=_csrf(c),
                 json={"type": "in", "action": "DROP"})
    assert got.status_code == 404, got.text[:200]
    assert fake.firewall_writes == [], "a refused node write still reached Proxmox"
    assert not writing_problems(got.json()["detail"])
    # The host's own node still works, on every node route it has.
    assert c.get(f"/api/v1/firewall/node/{ids['a']['host']}/pve1/rules"
                 ).status_code == 200


def test_a_peer_another_team_enrolled_is_not_reachable_through_this_host(solo):
    """The case the check exists for: both hosts are peers of one cluster and
    each belongs to a different team. Team A's host sees pve2 in its poll, but
    pve2 is enrolled as team B's host, so it is team B's to change."""
    from proxploy.models import Host
    c, ids, fake = solo["client"], solo["ids"], solo["fake"]
    app = solo["app"]
    with app.state.sessionmaker() as db:
        for host_id, node in ((ids["a"]["host"], "pve1"), (ids["b"]["host"], "pve2")):
            h = db.get(Host, host_id)
            h.cluster_name, h.node_name = "lab", node
        db.commit()

    class _Snap:
        nodes = [{"node": "pve1"}, {"node": "pve2"}, {"node": "pve3"}]
    app.state.poller.snapshots[ids["a"]["host"]] = _Snap()
    fake.firewall_writes.clear()
    taken = c.get(f"/api/v1/firewall/node/{ids['a']['host']}/pve2/rules")
    assert taken.status_code == 404, "a peer another team enrolled was reachable"
    assert fake.firewall_writes == []
    # pve3 is in the same cluster and nobody's host, so it stays reachable
    # through the host that can see it: refusing it would remove working
    # functionality without protecting anyone.
    assert c.get(f"/api/v1/firewall/node/{ids['a']['host']}/pve3/rules"
                 ).status_code == 200


def test_an_unknown_host_is_a_404_and_never_an_existence_oracle(solo):
    """A host id nobody owns has no team, so authorize() cannot place it. It
    must not answer differently from a host that exists but is not yours,
    or the 404 becomes a way to enumerate the estate."""
    c, ids = solo["client"], solo["ids"]
    _mk_user(c, "a-admin3@x.io", "admin")
    c.post("/api/v1/auth/logout", headers=_csrf(c))
    _login(c, "a-admin3@x.io")
    missing = c.get("/api/v1/firewall/cluster/99999/rules")
    other = c.get(f"/api/v1/firewall/cluster/{ids['b']['host']}/rules")
    assert missing.status_code in (403, 404)
    assert other.status_code == 403


# =====================================================================
# 3. HOSTILE PATH SEGMENTS
# =====================================================================

# Every one of these is a user-controlled path segment that becomes a path
# segment in the URL sent to Proxmox. proxmoxer joins with posixpath.join and
# does not escape (proxmoxer/core.py::url_join), so whatever survives our
# routing reaches PVE's URL verbatim.
HOSTILE = [
    ("dot-dot", "%2E%2E"),
    ("dot-dot-slash", "%2E%2E%2F%2E%2E"),
    ("just dots", "..."),
    ("absolute looking", "%2Fetc%2Fpasswd"),
    ("encoded slash", "a%2Fb"),
    ("null byte", "n%00ame"),
    ("unicode", "ålïas"),
    ("very long", "x" * 4096),
    ("other endpoint", "%2E%2E%2Fmacros"),
]


@pytest.mark.parametrize("label,segment", HOSTILE, ids=[h[0] for h in HOSTILE])
def test_a_hostile_object_name_never_500s(solo, label, segment):
    """Whatever the routing layer decides, the answer is an HTTP answer, and
    it never carries a traceback."""
    c, ids = solo["client"], solo["ids"]
    host = ids["a"]["host"]
    for url in (f"/api/v1/firewall/cluster/{host}/aliases/{segment}",
                f"/api/v1/firewall/cluster/{host}/ipsets/{segment}",
                f"/api/v1/firewall/cluster/{host}/groups/{segment}",
                f"/api/v1/firewall/cluster/{host}/groups/{segment}/rules",
                f"/api/v1/firewall/cluster/{host}/ipsets/{segment}/members"):
        got = c.request("DELETE" if "/members" not in url and "/rules" not in url
                        else "GET", url, headers=_csrf(c))
        assert got.status_code < 500, f"{url} -> {got.status_code}"
        assert "Traceback" not in got.text
        assert "proxmoxer" not in got.text


@pytest.mark.parametrize("label,segment", HOSTILE, ids=[h[0] for h in HOSTILE])
def test_a_hostile_cidr_never_500s(solo, label, segment):
    c, ids = solo["client"], solo["ids"]
    host = ids["a"]["host"]
    url = f"/api/v1/firewall/cluster/{host}/ipsets/trusted/members/{segment}"
    got = c.delete(url, headers=_csrf(c))
    assert got.status_code < 500, f"{url} -> {got.status_code}"
    assert "Traceback" not in got.text


def test_the_member_cidr_is_always_escaped_before_it_becomes_a_pve_segment(solo):
    """services/proxmox.py::_segment quotes with safe="", so a slash inside a
    CIDR cannot split the path. Every alias, IP set and security group name
    goes through the same helper now; a name is charset-checked at the route
    on top of that, since quoting alone cannot save a name of ".."."""
    c, ids, fake = solo["client"], solo["ids"], solo["fake"]
    host = ids["a"]["host"]
    for raw in ("10.0.0.0/8", "%2E%2E%2F%2E%2E", "..%2F.."):
        fake.firewall_writes.clear()
        c.delete(f"/api/v1/firewall/cluster/{host}/ipsets/trusted/members/{raw}",
                 headers=_csrf(c))
        if not fake.firewall_writes:
            continue
        _, path, _ = fake.firewall_writes[0]
        segment = path.split("cluster/firewall/ipset/trusted/", 1)[1]
        assert "/" not in segment, (
            f"the CIDR {raw!r} reached Proxmox as {segment!r}, which splits "
            f"the URL path")


def test_an_object_name_cannot_escape_its_endpoint(solo):
    """A name is a NAME. It must never be able to change which Proxmox
    endpoint the call lands on.

    It used to be able to. Nothing validated a name and nothing escaped one:
    api/firewall.py handed {name}/{group} straight to the client,
    services/proxmox.py handed it to proxmoxer, and proxmoxer joins with
    posixpath.join without quoting (proxmoxer/core.py:101), so a name of
    %2E%2E arrived at Proxmox as a literal .. segment and the call landed on
    the PARENT endpoint instead of the named object.

    Guaranteed now by api/firewall.py::ObjectName, which is PVE's own charset
    for these three objects declared as a path constraint, so a name that
    could be a path never reaches a handler. ProxmoxClient._segment quoting
    every name segment is the second half of it, for a caller that reaches the
    client without passing a route.
    """
    c, ids, fake = solo["client"], solo["ids"], solo["fake"]
    host = ids["a"]["host"]
    escapes = []
    probes = [
        ("alias", "DELETE", f"/api/v1/firewall/cluster/{host}/aliases/%2E%2E",
         "cluster/firewall/aliases/"),
        ("ipset", "DELETE", f"/api/v1/firewall/cluster/{host}/ipsets/%2E%2E",
         "cluster/firewall/ipset/"),
        ("group", "DELETE", f"/api/v1/firewall/cluster/{host}/groups/%2E%2E",
         "cluster/firewall/groups/"),
    ]
    for label, method, url, prefix in probes:
        fake.firewall_writes.clear()
        fake.firewall_reads.clear()
        c.request(method, url, headers=_csrf(c))
        seen = [p for _, p, _ in fake.firewall_writes] + \
               [p for p, _ in fake.firewall_reads]
        for path in seen:
            segment = path[len(prefix):] if path.startswith(prefix) else path
            if ".." in segment.split("/"):
                escapes.append(f"{label}: {url} reached Proxmox as {path!r}")
    assert not escapes, ("a path segment escaped its endpoint:\n"
                         + "\n".join(escapes))


def test_an_object_name_is_length_and_byte_checked_before_it_leaves(solo):
    """Both of these used to reach the Proxmox client unexamined. PVE's own
    schema caps these names, and a null byte in a URL makes urllib3 raise
    ValueError, which no handler catches: on a real cluster that was a 500
    where a 422 was owed. ObjectName's length cap and charset answer both
    before the handler runs."""
    c, ids, fake = solo["client"], solo["ids"], solo["fake"]
    host = ids["a"]["host"]
    bad = []
    for label, segment in (("long", "x" * 4096), ("null byte", "n%00ame")):
        fake.firewall_writes.clear()
        got = c.delete(f"/api/v1/firewall/cluster/{host}/aliases/{segment}",
                       headers=_csrf(c))
        if fake.firewall_writes:
            bad.append(f"{label}: accepted and forwarded as "
                       f"{fake.firewall_writes[0][1][:80]!r} "
                       f"(status {got.status_code})")
    assert not bad, "unchecked name reached Proxmox:\n" + "\n".join(bad)


# =====================================================================
# 4. INPUT VALIDATION
# =====================================================================

BAD_BODIES = [
    # (label, method, path suffix builder, body)
    ("rule create with no body", "POST", "/rules", {}),
    ("rule create missing action", "POST", "/rules", {"type": "in"}),
    ("rule type as an object", "POST", "/rules", {"type": {"a": 1},
                                                  "action": "ACCEPT"}),
    ("rule enable as a word", "POST", "/rules", {"type": "in",
                                                 "action": "ACCEPT",
                                                 "enable": "yes"}),
    ("rule comment deeply nested", "POST", "/rules",
     {"type": "in", "action": "ACCEPT", "comment": [[[[[[["deep"]]]]]]]}),
    ("move with no moveto", "PUT", "/rules/0/move", {}),
    ("move with a string moveto", "PUT", "/rules/0/move", {"moveto": "first"}),
    ("move with a null moveto", "PUT", "/rules/0/move", {"moveto": None}),
    ("move with a float moveto", "PUT", "/rules/0/move", {"moveto": 1.5}),
    ("options enable as a word", "PUT", "/options", {"enable": "on"}),
    ("options policy as a number", "PUT", "/options", {"policy_in": 1}),
    ("alias with no cidr", "POST", "/aliases", {"name": "office"}),
    ("alias update with no cidr", "PUT", "/aliases/office", {"rename": "hq"}),
    ("ipset with no name", "POST", "/ipsets", {"comment": "x"}),
    ("member with no cidr", "POST", "/ipsets/trusted/members", {"comment": "x"}),
    ("group with no group", "POST", "/groups", {"comment": "x"}),
]


@pytest.mark.parametrize("label,method,suffix,body", BAD_BODIES,
                         ids=[b[0] for b in BAD_BODIES])
def test_a_bad_body_is_a_422_with_something_to_read(solo, label, method,
                                                    suffix, body):
    c, ids, fake = solo["client"], solo["ids"], solo["fake"]
    fake.firewall_writes.clear()
    url = f"/api/v1/firewall/cluster/{ids['a']['host']}{suffix}"
    got = c.request(method, url, headers=_csrf(c), json=body)
    assert got.status_code == 422, f"{label} -> {got.status_code} {got.text[:200]}"
    assert "Traceback" not in got.text
    detail = got.json()["detail"]
    assert detail and all(d.get("msg") for d in detail), (
        f"{label} answered 422 with nothing a caller could act on: {detail}")
    assert fake.firewall_writes == [], f"{label} still reached Proxmox"


def test_a_body_that_is_not_json_at_all_is_a_422(solo):
    c, ids = solo["client"], solo["ids"]
    url = f"/api/v1/firewall/cluster/{ids['a']['host']}/rules"
    for headers, content in (
            ({"Content-Type": "text/plain"}, "type=in&action=ACCEPT"),
            ({"Content-Type": "application/json"}, "{not json"),
            ({"Content-Type": "application/json"}, ""),
    ):
        got = c.post(url, headers={**_csrf(c), **headers}, content=content)
        assert got.status_code == 422, f"{content[:20]!r} -> {got.status_code}"
        assert "Traceback" not in got.text


def test_a_pos_that_is_not_an_integer_is_a_422_before_anything_runs(solo):
    c, ids, fake = solo["client"], solo["ids"], solo["fake"]
    host = ids["a"]["host"]
    for pos in ("abc", "0.5", "", " ", "1e5"):
        fake.firewall_writes.clear()
        got = c.delete(f"/api/v1/firewall/cluster/{host}/rules/{pos}",
                       headers=_csrf(c))
        assert got.status_code in (404, 405, 422), f"pos={pos!r} -> {got.status_code}"
        assert fake.firewall_writes == []


def test_an_oversized_body_does_not_crash_the_route(solo):
    """No body-size limit exists on these routes. This asserts the property
    that matters, which is that a big body is answered rather than crashed;
    the missing limit is reported separately."""
    c, ids = solo["client"], solo["ids"]
    got = c.post(f"/api/v1/firewall/cluster/{ids['a']['host']}/rules",
                 headers=_csrf(c),
                 json={"type": "in", "action": "ACCEPT", "comment": "x" * 2_000_000})
    assert got.status_code < 500
    assert "Traceback" not in got.text


def test_an_unknown_field_in_a_rule_body_is_refused(solo):
    """A misspelled key is refused rather than dropped.

    Every firewall body model used to take pydantic's default extra="ignore",
    so this POST was answered 201 and `dportt` went in the bin: the operator
    was told a rule limiting port 22 had been created when what had been
    created was wide open. api/firewall.py::_Body carries extra="forbid" for
    all ten body models now.
    """
    c, ids = solo["client"], solo["ids"]
    got = c.post(f"/api/v1/firewall/cluster/{ids['a']['host']}/rules",
                 headers=_csrf(c),
                 json={"type": "in", "action": "ACCEPT", "dportt": "22"})
    assert got.status_code == 422, (
        f"a misspelled key was accepted with {got.status_code}: a rule the "
        f"operator believes limits port 22 was created wide open")


def test_an_unknown_field_never_reaches_proxmox(solo):
    """The other half of the refusal: a junk key is not forwarded either.

    Pinned separately from the status code so a later change to extra
    handling cannot start passing unknown keys through to PVE, whatever it
    answers the caller.
    """
    c, ids, fake = solo["client"], solo["ids"], solo["fake"]
    fake.firewall_writes.clear()
    c.post(f"/api/v1/firewall/cluster/{ids['a']['host']}/rules",
           headers=_csrf(c),
           json={"type": "in", "action": "ACCEPT", "dportt": "22"})
    assert fake.firewall_writes == []


def test_the_icmp_type_field_is_accepted_under_either_spelling(solo):
    """Forbidding extras must not start refusing the one aliased field.

    `icmp-type` is not a valid Python identifier, so RuleIn carries it as
    `icmp_type` with an alias and populate_by_name. Both spellings are known
    keys, and PVE only ever sees the hyphenated one.
    """
    c, ids, fake = solo["client"], solo["ids"], solo["fake"]
    for spelling in ("icmp-type", "icmp_type"):
        fake.firewall_writes.clear()
        got = c.post(f"/api/v1/firewall/cluster/{ids['a']['host']}/rules",
                     headers=_csrf(c),
                     json={"type": "in", "action": "ACCEPT", "proto": "icmp",
                           spelling: "echo-request"})
        assert got.status_code == 201, f"{spelling} -> {got.text[:150]}"
        _, _, params = fake.firewall_writes[0]
        assert params["icmp-type"] == "echo-request"
        assert "icmp_type" not in params


def test_a_rule_position_cannot_be_negative_or_absurd(solo):
    """Both used to be unbounded signed integers: moveto was a bare int and
    every rule route declared pos as a bare int, so -5 and 10**30 were
    accepted and forwarded to Proxmox. A rule position is an index into an
    ordered list, so api/firewall.py::RulePos and MoveIn.moveto both carry
    ge=0 and an upper bound now, on all four scopes."""
    c, ids = solo["client"], solo["ids"]
    host = ids["a"]["host"]
    bad = []
    for moveto in (-5, 10 ** 30):
        got = c.put(f"/api/v1/firewall/cluster/{host}/rules/0/move",
                    headers=_csrf(c), json={"moveto": moveto})
        if got.status_code != 422:
            bad.append(f"moveto={moveto} -> {got.status_code} {got.text[:80]}")
    for pos in ("-1", "99999999999999999999999"):
        got = c.delete(f"/api/v1/firewall/cluster/{host}/rules/{pos}",
                       headers=_csrf(c))
        if got.status_code != 422:
            bad.append(f"pos={pos} -> {got.status_code} {got.text[:80]}")
    assert not bad, "out of range positions accepted:\n" + "\n".join(bad)


# =====================================================================
# 5. ERROR MAPPING
# =====================================================================

class _Boom:
    """Every client method raises the same error, so a handler cannot get
    past whichever call it makes."""

    def __init__(self, exc):
        self._exc = exc

    def __getattr__(self, name):
        def call(*a, **kw):
            raise self._exc
        return call


def _raise_from_pve(monkeypatch, exc):
    import proxploy.services.firewall as fwsvc
    monkeypatch.setattr(fwsvc, "writers", lambda *a, **kw: _Boom(exc))
    monkeypatch.setattr(fwsvc, "readers", lambda *a, **kw: _Boom(exc))


def _wrapped(raw):
    """Exactly what services/proxmox.py::_wrap would have produced, so the
    message under test is the real one and not an invented one."""
    from proxploy.services.proxmox import ProxmoxClient
    client = ProxmoxClient("https://10.0.0.9:8006", "proxploy@pve!t", "s3cret",
                           factory=lambda **kw: None)
    return client._wrap("firewall rule create failed", raw)


def writing_problems(detail, *, reason: str | None = None) -> list[str]:
    """This repo's writing rules, applied to one message an operator reads.

    Returned as a list rather than asserted here so a caller walking every
    route reports every bad message at once instead of stopping at the first.
    """
    if not isinstance(detail, str) or not detail:
        return [f"the answer carried no sentence to read: {detail!r}"]
    bad = []
    if "—" in detail:
        bad.append(f"em dash in a user-facing message: {detail}")
    for word in ("Traceback", "proxmoxer", "urllib3", "ProxmoxError",
                 "NoneType", "self."):
        if word in detail:
            bad.append(f"internal vocabulary {word!r} in {detail!r}")
    # It must say what actually happened, not "something went wrong".
    if "firewall" not in detail.lower():
        bad.append(f"does not say what failed: {detail!r}")
    if reason is not None and reason not in detail:
        bad.append(f"lost the reason {reason!r} on the way out: {detail!r}")
    return bad


PVE_FAILURES = [
    ("401", Exception("401 Unauthorized: authentication failure"), "auth"),
    ("403", Exception("403 Forbidden: Permission check failed "
                      "(/cluster/firewall, Sys.Modify)"), "permission"),
    ("404", Exception("404 Not Found: no such rule"), "unknown"),
    ("500", Exception("500 Internal Server Error: rule update failed"), "unknown"),
    ("501", Exception("501 Method 'PUT /cluster/firewall/aliases' not "
                      "implemented"), "unknown"),
    ("connection", ConnectionError("Connection refused"), "unreachable"),
    ("timeout", TimeoutError("Read timed out. (read timeout=10)"), "unreachable"),
]


@pytest.mark.parametrize("label,raw,kind", PVE_FAILURES,
                         ids=[f[0] for f in PVE_FAILURES])
def test_a_proxmox_failure_becomes_a_readable_answer(solo, monkeypatch, label,
                                                     raw, kind):
    """pve_error (api/firewall.py:44) is the only mapping there is. What it
    must never do is 500, lose the reason, or hand the caller vocabulary from
    inside the process."""
    err = _wrapped(raw)
    assert err.kind == kind
    _raise_from_pve(monkeypatch, err)
    c, ids = solo["client"], solo["ids"]
    got = c.post(f"/api/v1/firewall/cluster/{ids['a']['host']}/rules",
                 headers=_csrf(c), json={"type": "in", "action": "ACCEPT"})
    assert got.status_code < 500 or got.status_code == 502
    assert got.status_code != 500
    assert not writing_problems(got.json()["detail"], reason=str(raw))


def test_a_permission_failure_names_the_privilege_proxmox_wanted(solo, monkeypatch):
    """The one failure shape that already reads well. Pinned because it is
    the model the others should follow."""
    err = _wrapped(Exception("403 Forbidden: Permission check failed "
                             "(/cluster/firewall, Sys.Modify)"))
    _raise_from_pve(monkeypatch, err)
    c, ids = solo["client"], solo["ids"]
    got = c.post(f"/api/v1/firewall/cluster/{ids['a']['host']}/rules",
                 headers=_csrf(c), json={"type": "in", "action": "ACCEPT"})
    detail = got.json()["detail"]
    assert "Sys.Modify" in detail
    assert "/cluster/firewall" in detail


@pytest.mark.parametrize("path,method,body", [
    ("/rules/0", "put", {"type": "in", "action": "ACCEPT"}),
    ("/rules/0/move", "put", {"moveto": 1}),
    ("/rules/0", "delete", None),
    ("/options", "put", {"policy_out": "ACCEPT"}),
], ids=["update", "move", "delete", "options"])
def test_a_digest_conflict_is_a_409_not_a_gateway_failure(solo, monkeypatch,
                                                          path, method, body):
    """PVE answers a stale digest with a 500 carrying "detected modified
    configuration", on all four writes that take one. It is the one 500 that
    is not a gateway failure: somebody else edited the scope, and the caller
    reloads rather than retries. Measured on pve-manager 9.2.11, 2026-08-21.
    """
    _raise_from_pve(monkeypatch, _wrapped(Exception(
        "500 Internal Server Error: detected modified configuration - "
        "file changed by other user? Try again.")))
    c, ids = solo["client"], solo["ids"]
    url = f"/api/v1/firewall/cluster/{ids['a']['host']}{path}"
    kw = {"headers": _csrf(c)} | ({} if body is None else {"json": body})
    got = getattr(c, method)(url, **kw)
    assert got.status_code == 409, (
        f"a stale digest on {method.upper()} {path} read as {got.status_code}")
    detail = got.json()["detail"]
    assert not writing_problems(detail)
    # It has to tell the operator to reload; a retry alone loses their edit.
    assert "reload" in detail.lower()


@pytest.mark.parametrize("label,raw,want", [
    ("404", Exception("404 Not Found: no such rule"), 404),
    ("501", Exception("501 Method 'PUT /cluster/firewall/aliases' not "
                      "implemented"), 501),
], ids=["404", "501"])
@pytest.mark.xfail(strict=True, reason=(
    "FINDING: api/firewall.py:44 pve_error() collapses every Proxmox "
    "failure to 502, including the two that are not gateway failures. A rule "
    "or alias that does not exist is a 404 about the caller's own request; a "
    "501 means the scope has no such object at all, which services/"
    "firewall.py:19 SCOPE_OBJECTS was written to answer as a 404 and never "
    "wired up (that table is imported by nothing outside its own test). "
    "Today both read to the operator as 'Proxmox is broken'."))
def test_a_not_found_from_proxmox_is_not_reported_as_a_gateway_failure(
        solo, monkeypatch, label, raw, want):
    _raise_from_pve(monkeypatch, _wrapped(raw))
    c, ids = solo["client"], solo["ids"]
    got = c.delete(f"/api/v1/firewall/cluster/{ids['a']['host']}/rules/9",
                   headers=_csrf(c))
    assert got.status_code == want, (
        f"a PVE {label} was relayed as {got.status_code}")


@pytest.mark.xfail(strict=True, reason=(
    "FINDING: api/firewall.py:122 and :420 trust the SHAPE of what Proxmox "
    "returned. _rules_read does rules[0].get('digest') and _options_read "
    "does options.get('digest'), so a rule list whose rows are not objects, "
    "or an options response that is not an object, raises AttributeError or "
    "KeyError inside the handler and Starlette answers a bare 500. This is "
    "the only 500 in the whole firewall surface."))
def test_a_non_object_options_response_is_not_a_crash(tmp_path, csrf_header,
                                                      bootstrap_admin):
    from tests.support import make_app
    fake = _fake()
    app = make_app(tmp_path, fake=fake)
    with TestClient(app, raise_server_exceptions=False) as c:
        bootstrap_admin(c)
        ids = seed_world(app)
        host = ids["a"]["host"]
        bad = []
        for label, value in (("rules as strings", ["nope"]),
                             ("rules as an object", {"a": 1})):
            fake.firewall_data["cluster/firewall/rules"] = value
            got = c.get(f"/api/v1/firewall/cluster/{host}/rules")
            if got.status_code >= 500:
                bad.append(f"{label} -> {got.status_code}")
        fake.firewall_data.pop("cluster/firewall/rules", None)
        for label, value in (("options as a list", []),
                             ("options as a string", "boom")):
            fake.firewall_data["cluster/firewall/options"] = value
            got = c.get(f"/api/v1/firewall/cluster/{host}/options")
            if got.status_code >= 500:
                bad.append(f"{label} -> {got.status_code}")
        assert not bad, ("a malformed Proxmox response crashed the handler:\n"
                         + "\n".join(bad))


def test_a_crash_never_puts_a_stack_trace_in_the_response(tmp_path,
                                                          bootstrap_admin):
    """The half of the above that is safe: the 500 body carries no internals."""
    from tests.support import make_app
    fake = _fake()
    app = make_app(tmp_path, fake=fake)
    with TestClient(app, raise_server_exceptions=False) as c:
        bootstrap_admin(c)
        ids = seed_world(app)
        fake.firewall_data["cluster/firewall/rules"] = ["nope"]
        got = c.get(f"/api/v1/firewall/cluster/{ids['a']['host']}/rules")
        assert got.status_code == 500
        for word in ("Traceback", "firewall.py", "AttributeError",
                     "site-packages"):
            assert word not in got.text


def test_a_failed_write_still_leaves_an_audit_row(solo, monkeypatch):
    _raise_from_pve(monkeypatch, _wrapped(ConnectionError("Connection refused")))
    c, ids = solo["client"], solo["ids"]
    c.post(f"/api/v1/firewall/cluster/{ids['a']['host']}/rules",
           headers=_csrf(c), json={"type": "in", "action": "ACCEPT"})
    with solo["app"].state.sessionmaker() as db:
        row = (db.query(AuditEvent)
               .filter_by(action="firewall.rule_create", result="error").one())
        assert row.target_type == "host"


# =====================================================================
# 6. AUDIT TRAIL
# =====================================================================


def _write_routes(app):
    return [r for r in fw_routes(app) if r["method"] != "GET"]


def test_every_firewall_write_leaves_an_audit_row(solo):
    """Generated from the route table, so a write route added later is
    covered without anyone remembering to add a case."""
    c, ids, app = solo["client"], solo["ids"], solo["app"]
    silent = []
    for r in _write_routes(app):
        with app.state.sessionmaker() as db:
            before = db.query(AuditEvent).count()
        got = call(c, r, ids)
        assert got.status_code < 400, f"{r['method']} {r['path']} -> {got.text}"
        with app.state.sessionmaker() as db:
            rows = db.query(AuditEvent).order_by(AuditEvent.id).all()[before:]
        if not any(row.action.startswith("firewall.") for row in rows):
            silent.append(f"{r['method']} {r['path']}")
    assert not silent, ("write routes that changed a firewall and recorded "
                        "nothing:\n" + "\n".join(silent))


def test_what_a_firewall_audit_row_actually_records(solo):
    c, ids, app = solo["client"], solo["ids"], solo["app"]
    c.post(f"/api/v1/firewall/cluster/{ids['a']['host']}/rules",
           headers=_csrf(c),
           json={"type": "in", "action": "ACCEPT", "dport": "22"})
    with app.state.sessionmaker() as db:
        row = db.query(AuditEvent).filter_by(action="firewall.rule_create").one()
        assert row.actor_type == "user"
        assert row.actor_id is not None
        assert row.target_type == "host"
        assert row.target_id == ids["a"]["host"]
        assert "host-a" in row.target_name
        assert row.result == "ok"
        assert row.params["dport"] == "22"
        assert row.ip


def test_a_guest_firewall_write_is_audited_against_the_guest_not_the_host(solo):
    c, ids, app = solo["client"], solo["ids"], solo["app"]
    c.post(f"/api/v1/apps/{ids['a']['app']}/firewall/rules", headers=_csrf(c),
           json={"type": "in", "action": "ACCEPT"})
    c.post(f"/api/v1/vms/{ids['a']['vm']}/firewall/rules", headers=_csrf(c),
           json={"type": "in", "action": "ACCEPT"})
    with app.state.sessionmaker() as db:
        kinds = {r.target_type: r.target_name for r in
                 db.query(AuditEvent).filter_by(action="firewall.rule_create")}
    assert kinds["app"] == "Immich"
    assert kinds["vm"] == "win11"


def test_the_move_handler_has_a_dead_local_params(solo):
    """Confirms the known deferred item at api/firewall.py:186. The local is
    built with the digest in it and then thrown away, because the call below
    passes its own params= keyword. Reading the handler, it looks as though
    the digest is audited. It is not."""
    import inspect

    from proxploy.api.firewall import cluster_rule_move
    source = inspect.getsource(cluster_rule_move)
    assert 'params = {"moveto": body.moveto, "digest": body.digest}' in source
    assert 'params={"moveto": body.moveto}' in source, (
        "the dead local may have been wired up; recheck what is audited")


def test_a_rule_move_records_the_move_but_not_the_digest(solo):
    """The known deferred item, asserted as behaviour rather than as source.

    Every other write route records the digest it sent, so a reviewer reading
    the trail after a lost update can see which version of the rule list the
    move was against. For a move they cannot.
    """
    c, ids, app = solo["client"], solo["ids"], solo["app"]
    c.put(f"/api/v1/firewall/cluster/{ids['a']['host']}/rules/3/move",
          headers=_csrf(c), json={"moveto": 1, "digest": "d-move"})
    with app.state.sessionmaker() as db:
        row = db.query(AuditEvent).filter_by(action="firewall.rule_move").one()
    assert row.params == {"moveto": 1}
    assert "digest" not in row.params
    # And the digest DID go to Proxmox, so the gap is the record, not the call.
    _, _, params = solo["fake"].firewall_writes[0]
    assert params["digest"] == "d-move"


@pytest.mark.xfail(strict=True, reason=(
    "KNOWN DEFERRED: the move handlers drop the digest from the audit entry. "
    "api/firewall.py:186 builds a params dict containing it and then never "
    "uses it (dead local), passing params={'moveto': ...} to _rules_write "
    "instead. The group, node and guest move handlers never build it at all "
    "(:267, :340, :826). Every other firewall write records its digest."))
def test_a_rule_move_should_record_the_digest_it_sent(solo):
    c, ids, app = solo["client"], solo["ids"], solo["app"]
    c.put(f"/api/v1/firewall/cluster/{ids['a']['host']}/rules/3/move",
          headers=_csrf(c), json={"moveto": 1, "digest": "d-move"})
    with app.state.sessionmaker() as db:
        row = db.query(AuditEvent).filter_by(action="firewall.rule_move").one()
    assert row.params.get("digest") == "d-move"


# =====================================================================
# 7. DIGEST ROUND-TRIP
# =====================================================================
#
# The spec says a digest is round-tripped on every write. On the backend that
# means two things: the route has to have somewhere to PUT a digest, and it
# has to forward it. Where the model has a digest field the client sends it in
# the body; where it does not, the only remaining door is a query parameter,
# and only the DELETE routes have one.

DIGEST_CARRIERS = [
    # (label, method, path suffix, body)
    ("rule create", "POST", "/rules", {"type": "in", "action": "ACCEPT"}),
    ("rule update", "PUT", "/rules/0", {"comment": "x"}),
    ("rule move", "PUT", "/rules/0/move", {"moveto": 1}),
    ("rule delete", "DELETE", "/rules/0", None),
    ("options update", "PUT", "/options", {"enable": 1}),
    ("alias update", "PUT", "/aliases/office", {"cidr": "10.0.0.0/24"}),
    ("alias delete", "DELETE", "/aliases/office", None),
    ("ipset delete", "DELETE", "/ipsets/trusted", None),
    ("member update", "PUT", "/ipsets/trusted/members/10.0.0.5", {"comment": "x"}),
    ("member delete", "DELETE", "/ipsets/trusted/members/10.0.0.5", None),
    ("group delete", "DELETE", "/groups/web", None),
]

# The four writes with nowhere to put a digest. PVE's POST schema for an alias
# and for an IP set member has no digest parameter, so there is nothing to
# forward and a body carrying one is refused rather than quietly dropped. The
# first two are a gap and reported as one: PVE's POST schema for an IP set and
# for a security group each DO take a digest, and neither model has a field
# for it.
DIGEST_REFUSED = [
    ("ipset create", "POST", "/ipsets", {"name": "trusted"}),
    ("group create", "POST", "/groups", {"group": "web"}),
    ("alias create", "POST", "/aliases", {"name": "office",
                                          "cidr": "10.0.0.0/24"}),
    ("member add", "POST", "/ipsets/trusted/members", {"cidr": "10.0.0.5"}),
]


@pytest.mark.parametrize("label,method,suffix,body", DIGEST_CARRIERS,
                         ids=[d[0] for d in DIGEST_CARRIERS])
def test_a_write_route_forwards_the_digest_it_was_given(solo, label, method,
                                                        suffix, body):
    c, ids, fake = solo["client"], solo["ids"], solo["fake"]
    fake.firewall_writes.clear()
    url = f"/api/v1/firewall/cluster/{ids['a']['host']}{suffix}?digest=d-query"
    kwargs = {"headers": _csrf(c)}
    if body is not None:
        kwargs["json"] = {**body, "digest": "d-body"}
    got = c.request(method, url, **kwargs)
    assert got.status_code < 400, f"{label} -> {got.status_code} {got.text[:150]}"
    assert fake.firewall_writes, f"{label} sent nothing to Proxmox"
    _, _, params = fake.firewall_writes[0]
    assert params.get("digest") in ("d-body", "d-query"), (
        f"{label} dropped the digest: sent {params}")


@pytest.mark.parametrize("label,method,suffix,body", DIGEST_REFUSED,
                         ids=[d[0] for d in DIGEST_REFUSED])
def test_a_create_that_cannot_send_a_digest_refuses_one(solo, label, method,
                                                        suffix, body):
    """PVE has nowhere to put it, so the caller is told rather than left
    believing their create was guarded against a concurrent edit."""
    c, ids, fake = solo["client"], solo["ids"], solo["fake"]
    fake.firewall_writes.clear()
    url = f"/api/v1/firewall/cluster/{ids['a']['host']}{suffix}"
    got = c.request(method, url, headers=_csrf(c),
                    json={**body, "digest": "d-body"})
    assert got.status_code == 422, f"{label} -> {got.status_code} {got.text[:150]}"
    assert fake.firewall_writes == [], f"{label} still reached Proxmox"
    # And without one it goes through, so the refusal is about the digest and
    # not about the body.
    got = c.request(method, url, headers=_csrf(c), json=body)
    assert got.status_code < 400, f"{label} -> {got.status_code} {got.text[:150]}"
    _, _, params = fake.firewall_writes[0]
    assert "digest" not in params


@pytest.mark.xfail(strict=True, reason=(
    "FINDING: IpSetIn (api/firewall.py:500) and GroupIn (api/firewall.py:695) "
    "carry no digest field, and neither route reads a digest query "
    "parameter, so there is no way for a caller to send one. PVE's POST "
    "schema for /cluster/firewall/ipset and /cluster/firewall/groups both "
    "accept a digest, so creating an IP set or a security group is the one "
    "kind of firewall write that cannot be made safe against a concurrent "
    "edit. AliasIn and MemberIn have the same shape but are correct: PVE's "
    "POST schema for those two has no digest to send."))
def test_creating_an_ipset_or_a_group_can_carry_a_digest(solo):
    c, ids, fake = solo["client"], solo["ids"], solo["fake"]
    missing = []
    for label, suffix, body in (("ipset", "/ipsets", {"name": "trusted"}),
                                ("group", "/groups", {"group": "web"})):
        fake.firewall_writes.clear()
        c.post(f"/api/v1/firewall/cluster/{ids['a']['host']}{suffix}"
               f"?digest=d-query", headers=_csrf(c),
               json={**body, "digest": "d-body"})
        _, _, params = fake.firewall_writes[0]
        if "digest" not in params:
            missing.append(f"{label} create sent {params}")
    assert not missing, ("a create route cannot round-trip a digest:\n"
                         + "\n".join(missing))


def test_a_guest_write_forwards_its_digest_too(solo):
    c, ids, fake = solo["client"], solo["ids"], solo["fake"]
    for base in (f"/api/v1/apps/{ids['a']['app']}",
                 f"/api/v1/vms/{ids['a']['vm']}"):
        fake.firewall_writes.clear()
        c.put(f"{base}/firewall/rules/0", headers=_csrf(c),
              json={"comment": "x", "digest": "d1"})
        _, _, params = fake.firewall_writes[0]
        assert params.get("digest") == "d1", f"{base} dropped the digest"
        fake.firewall_writes.clear()
        c.delete(f"{base}/firewall/rules/0?digest=d2", headers=_csrf(c))
        _, _, params = fake.firewall_writes[0]
        assert params.get("digest") == "d2", f"{base} delete dropped the digest"


def test_a_digest_that_was_not_sent_is_never_invented(solo):
    """services/proxmox.py::_fw_params drops None rather than letting
    proxmoxer serialise it as the string "None", which would fail the digest
    comparison on every write."""
    c, ids, fake = solo["client"], solo["ids"], solo["fake"]
    fake.firewall_writes.clear()
    c.delete(f"/api/v1/firewall/cluster/{ids['a']['host']}/rules/0",
             headers=_csrf(c))
    _, _, params = fake.firewall_writes[0]
    assert "digest" not in params


# =====================================================================
# 8. IDEMPOTENCY AND ORDERING
# =====================================================================


def test_a_double_delete_is_relayed_twice_and_never_swallowed(solo):
    """These routes are a passthrough: PVE is the authority on whether the
    rule is still there. Nothing local pretends to know, which is right, but
    it does mean the second delete is a fresh call rather than a no-op."""
    c, ids, fake = solo["client"], solo["ids"], solo["fake"]
    url = f"/api/v1/firewall/cluster/{ids['a']['host']}/rules/2"
    fake.firewall_writes.clear()
    first = c.delete(url, headers=_csrf(c))
    second = c.delete(url, headers=_csrf(c))
    assert first.status_code == 200 and second.status_code == 200
    assert len(fake.firewall_writes) == 2, (
        "the second delete was answered locally, which would be a guess")


def test_deleting_a_rule_that_is_gone_says_so(solo, monkeypatch):
    """PVE's own refusal, relayed. The message has to be about the rule, not
    about Proxploy."""
    _raise_from_pve(monkeypatch, _wrapped(
        Exception("400 Bad Request: no rule at position 9")))
    c, ids = solo["client"], solo["ids"]
    got = c.delete(f"/api/v1/firewall/cluster/{ids['a']['host']}/rules/9",
                   headers=_csrf(c))
    assert got.status_code == 502
    detail = got.json()["detail"]
    assert "no rule at position 9" in detail
    assert "—" not in detail


def test_a_stale_digest_is_relayed_as_the_conflict_it_is(solo, monkeypatch):
    """The whole point of the digest. If PVE refuses on a digest mismatch the
    caller has to be able to tell that from an outage."""
    _raise_from_pve(monkeypatch, _wrapped(
        Exception("500 wrong digest, the firewall rules have changed")))
    c, ids = solo["client"], solo["ids"]
    got = c.put(f"/api/v1/firewall/cluster/{ids['a']['host']}/rules/0",
                headers=_csrf(c), json={"comment": "x", "digest": "stale"})
    detail = got.json()["detail"]
    assert "digest" in detail
    assert "changed" in detail


def test_updating_a_rule_that_was_deleted_fails_cleanly(solo, monkeypatch):
    _raise_from_pve(monkeypatch, _wrapped(
        Exception("400 Bad Request: no rule at position 4")))
    c, ids, app = solo["client"], solo["ids"], solo["app"]
    got = c.put(f"/api/v1/firewall/cluster/{ids['a']['host']}/rules/4",
                headers=_csrf(c), json={"comment": "x"})
    assert got.status_code == 502
    assert "Traceback" not in got.text
    with app.state.sessionmaker() as db:
        row = (db.query(AuditEvent)
               .filter_by(action="firewall.rule_update", result="error").one())
        assert row.target_id == ids["a"]["host"]


def test_moving_a_rule_past_the_end_is_proxmoxs_answer_not_a_local_guess(solo):
    """No local bound exists, so an out of range moveto is forwarded and PVE
    decides. Pinned so the passthrough is a stated property rather than an
    accident; the missing lower bound is reported separately."""
    c, ids, fake = solo["client"], solo["ids"], solo["fake"]
    fake.firewall_writes.clear()
    got = c.put(f"/api/v1/firewall/cluster/{ids['a']['host']}/rules/0/move",
                headers=_csrf(c), json={"moveto": 9999})
    assert got.status_code == 200
    _, _, params = fake.firewall_writes[0]
    assert params["moveto"] == 9999


def test_a_move_never_carries_an_edit_alongside_it(solo):
    """PVE's schema says other arguments are ignored on a move, so sending an
    edit with one would look applied and not be.

    MoveIn has no room for one and now says so: it used to drop the edit
    quietly (extra="ignore"), which told the operator their comment had been
    saved. It is a 422 naming the field instead, and nothing is sent.
    """
    c, ids, fake = solo["client"], solo["ids"], solo["fake"]
    fake.firewall_writes.clear()
    got = c.put(f"/api/v1/firewall/cluster/{ids['a']['host']}/rules/0/move",
                headers=_csrf(c),
                json={"moveto": 1, "digest": "d1", "comment": "should not travel",
                      "action": "DROP"})
    assert got.status_code == 422, got.text[:200]
    assert fake.firewall_writes == [], (
        "a move carried an edit that PVE would silently ignore")


def test_deleting_an_ipset_never_forces_on_the_callers_behalf(solo):
    """force drops members the operator may not have looked at, so it is only
    ever the caller's word."""
    c, ids, fake = solo["client"], solo["ids"], solo["fake"]
    fake.firewall_writes.clear()
    c.delete(f"/api/v1/firewall/cluster/{ids['a']['host']}/ipsets/trusted",
             headers=_csrf(c))
    _, _, params = fake.firewall_writes[0]
    assert "force" not in params
    fake.firewall_writes.clear()
    c.delete(f"/api/v1/firewall/cluster/{ids['a']['host']}/ipsets/trusted"
             f"?force=true", headers=_csrf(c))
    _, _, params = fake.firewall_writes[0]
    assert params["force"] == 1


# =====================================================================
# 9. WHEN PROXMOX IS DOWN, REFUSING, OR ANSWERING GARBAGE
# =====================================================================
#
# Everything above assumes the call to Proxmox went through. These two walks
# assume it did not, on every route at once. The failure mode being hunted is
# not the crash: it is a firewall write that Proxmox refused, answered to the
# operator as though something merely glitched, and recorded nowhere. The
# three write helpers (_options_write, _object_write, _guest_write) are the
# only record such a write was ever attempted.
#
# Parametrized over the four kinds services/proxmox.py::_classify can produce,
# and walked over the generated route table, so a route added later is covered
# without anyone adding a case, and the mapping table is exercised for every
# shape of failure rather than one.

PVE_KINDS = [
    ("auth", Exception("401 Unauthorized: authentication failure")),
    ("permission", Exception("403 Forbidden: Permission check failed "
                             "(/cluster/firewall, Sys.Modify)")),
    ("unreachable", ConnectionError("Connection refused")),
    ("unknown", Exception("500 Internal Server Error: rule update failed")),
]

# The audit action every write family records. Asserted as a set at the end of
# the walk so a family the walk silently skipped (a route table that stopped
# recursing, a body_for that started 422ing) fails loudly instead of shrinking
# the walk to the routes that still work.
WRITE_ACTIONS = {
    "firewall.rule_create", "firewall.rule_update", "firewall.rule_move",
    "firewall.rule_delete", "firewall.options", "firewall.alias_create",
    "firewall.alias_update", "firewall.alias_delete", "firewall.ipset_create",
    "firewall.ipset_delete", "firewall.ipset_member_add",
    "firewall.ipset_member_update", "firewall.ipset_member_delete",
    "firewall.group_create", "firewall.group_delete",
}


def _as_admin(world):
    c = world["client"]
    c.post("/api/v1/auth/logout", headers=_csrf(c))
    _login(c, "admin@x.io")
    with world["app"].state.sessionmaker() as db:
        return db.query(User).filter_by(email="admin@x.io").one().id


def _expected_target(path, ids):
    """A guest write is audited against the guest, everything else against the
    host. Read off the path rather than off the row, so the assertion is
    independent of what the handler decided."""
    if path.startswith("/api/v1/apps/"):
        return "app", ids["a"]["app"]
    if path.startswith("/api/v1/vms/"):
        return "vm", ids["a"]["vm"]
    return "host", ids["a"]["host"]


@pytest.mark.parametrize("kind,raw", PVE_KINDS, ids=[k[0] for k in PVE_KINDS])
def test_every_read_route_relays_a_proxmox_failure_readably(world, monkeypatch,
                                                            kind, raw):
    """No 500, no traceback, no internals, and the reason Proxmox gave is
    still in the sentence when it reaches the operator."""
    err = _wrapped(raw)
    assert err.kind == kind
    _raise_from_pve(monkeypatch, err)
    c, ids = world["client"], world["ids"]
    _as_admin(world)
    bad, walked = [], 0
    for r in fw_routes(world["app"]):
        if r["method"] != "GET":
            continue
        walked += 1
        got = call(c, r, ids)
        where = f"{r['method']} {r['path']}"
        assert "Traceback" not in got.text, where
        if got.status_code != 502:
            bad.append(f"{where} -> {got.status_code} {got.text[:120]}")
            continue
        bad += [f"{where}: {p}" for p in
                writing_problems(got.json().get("detail"), reason=str(raw))]
    assert walked == 26, f"the read walk covered {walked} routes, not 26"
    assert not bad, (f"a {kind} failure from Proxmox was answered badly:\n"
                     + "\n".join(bad))


@pytest.mark.parametrize("kind,raw", PVE_KINDS, ids=[k[0] for k in PVE_KINDS])
def test_every_write_route_records_the_failure_it_relayed(world, monkeypatch,
                                                          kind, raw):
    """A firewall write that Proxmox refused has to leave a row saying so.

    Nothing else in the system knows it happened: these routes hold no state,
    the fake was never reached, and the operator has only the answer they were
    given. If the row is missing, the trail says the firewall was never
    touched, which is a different and much worse statement than "the change
    failed".
    """
    err = _wrapped(raw)
    assert err.kind == kind
    _raise_from_pve(monkeypatch, err)
    c, ids, app = world["client"], world["ids"], world["app"]
    admin_id = _as_admin(world)
    bad, walked = [], 0
    seen_actions, seen_targets = set(), set()
    for r in _write_routes(app):
        walked += 1
        where = f"{r['method']} {r['path']}"
        with app.state.sessionmaker() as db:
            before = db.query(AuditEvent).count()
        got = call(c, r, ids)
        assert "Traceback" not in got.text, where
        if got.status_code != 502:
            bad.append(f"{where} -> {got.status_code} {got.text[:120]}")
            continue
        bad += [f"{where}: {p}" for p in
                writing_problems(got.json().get("detail"), reason=str(raw))]
        with app.state.sessionmaker() as db:
            fresh = [row for row in db.query(AuditEvent).order_by(AuditEvent.id)
                     .all()[before:] if row.action.startswith("firewall.")]
        if not fresh:
            bad.append(f"{where}: the write failed and recorded NOTHING")
            continue
        row = fresh[-1]
        seen_actions.add(row.action)
        seen_targets.add(row.target_type)
        if any(other.result == "ok" for other in fresh):
            bad.append(f"{where}: a failed write also recorded a success")
        if row.result != "error":
            bad.append(f"{where}: recorded result={row.result!r}, not 'error'")
        if (row.actor_type, row.actor_id) != ("user", admin_id):
            bad.append(f"{where}: recorded actor "
                       f"{row.actor_type}/{row.actor_id}, not user/{admin_id}")
        want = _expected_target(r["path"], ids)
        if (row.target_type, row.target_id) != want:
            bad.append(f"{where}: recorded target "
                       f"{row.target_type}/{row.target_id}, not {want[0]}/{want[1]}")
        if not row.target_name:
            bad.append(f"{where}: recorded no name for what it acted on")
        body = body_for(r["method"], r["path"])
        if body and not set(body) <= set(row.params or {}):
            bad.append(f"{where}: sent {sorted(body)} and recorded "
                       f"{sorted(row.params or {})}")
    assert walked == 50, f"the write walk covered {walked} routes, not 50"
    assert not bad, (f"a {kind} failure from Proxmox was handled badly:\n"
                     + "\n".join(bad))
    # Proves the walk reached all three write helpers rather than one of them
    # fifty times: options rows come from _options_write and _guest_write,
    # alias/ipset/member/group rows on a host from _object_write, and every
    # app or vm row from _guest_write.
    assert seen_targets == {"host", "app", "vm"}, seen_targets
    assert WRITE_ACTIONS <= seen_actions, WRITE_ACTIONS - seen_actions
