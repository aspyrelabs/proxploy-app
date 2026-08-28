"""One test per lever, exercising the DENIED side of the gate.

Written when the tiers were armed (PXP-21, 2026-08-28). Until then
`all_entitled: true` meant every one of these branches had never executed
anywhere: not in a test, not on a dev box, not in production. "The flag flips"
was the only thing under test, and a gate that returns the wrong status, leaks
which tier you would need, or half-applies a write is not a working gate.

Each test asserts three things, because each is a different way to be broken:

  status    the code a client can actually route on. 403 for a denial the
            caller is allowed to know about, and deliberately NOT 403 in the
            two places where the status itself would leak state to someone who
            has not authenticated (bearer auth, OIDC discovery).
  message   names the tier that grants the feature. "entitlement_required:
            hosts.multi" tells an operator what broke and nothing about what to
            do about it, so deps.entitlement_error adds required_tier and a
            sentence, and these pin that it survives.
  no writes nothing partially applied. A gate that raises after the row is
            added is worse than no gate: the feature is refused and the state
            change happens anyway.

A lever missing from LEVERS below is a lever whose denied branch is untested,
so test_every_lever_is_covered_here fails on it.
"""
import pytest
from fastapi.testclient import TestClient

from proxploy.models import ApiKey, Host, Schedule, Team
from tests.support import make_app

# The levers: tier-varying AND enforced. Kept as data so the coverage test
# below can fail when someone adds a lever and no denied-branch test with it.
LEVERS = {"hosts.multi", "store.auto_update", "migrate.cross_host",
          "migrate.preflight", "auth.oidc", "teams.rbac", "api.tokens"}


@pytest.fixture
def app_client(tmp_path, bootstrap_admin):
    """Owner session on a free-tier install, which is now the default: no
    licence means Homelab, so every lever below is already off."""
    app = make_app(tmp_path)
    with TestClient(app) as c:
        bootstrap_admin(c)
        yield c


def assert_denied(r, feature, tier):
    """The 403 contract, in one place: machine-readable for the frontend,
    legible for whoever reads it in a toast."""
    assert r.status_code == 403, (r.status_code, r.text)
    body = r.json()
    detail = body.get("detail", body)
    assert detail["error"] == "entitlement_required"
    assert detail["feature"] == feature
    assert detail["required_tier"] == tier
    assert tier.capitalize() in detail["message"], detail["message"]


def count(client, model):
    with client.app.state.sessionmaker() as db:
        return db.query(model).count()


def test_hosts_multi_refuses_the_second_host_and_writes_nothing(
        app_client, csrf_header):
    """The first host is always allowed; the gate is on the second. Seeded
    directly because enrolling a real one needs a live node, and what is under
    test is the refusal, not enrolment."""
    with app_client.app.state.sessionmaker() as db:
        db.add(Host(name="pve1", address="10.0.0.1"))
        db.commit()

    r = app_client.post("/api/v1/hosts",
                        json={"name": "pve2", "address": "10.0.0.2",
                              "token_id": "root@pam!t", "token_secret": "s"},
                        headers=csrf_header(app_client))
    assert_denied(r, "hosts.multi", "pro")
    assert count(app_client, Host) == 1


def test_store_auto_update_refuses_the_schedule_and_writes_nothing(
        app_client, csrf_header):
    from proxploy.api.schedules import AUTO_UPDATE_KIND

    before = count(app_client, Schedule)
    r = app_client.post("/api/v1/schedules",
                        json={"name": "nightly", "cron": "0 3 * * *",
                              "timezone": "UTC", "job_kind": AUTO_UPDATE_KIND},
                        headers=csrf_header(app_client))
    assert_denied(r, "store.auto_update", "pro")
    assert count(app_client, Schedule) == before


def test_migrate_preflight_is_refused(app_client, csrf_header):
    r = app_client.post("/api/v1/apps/1/migrate/preflight",
                        json={"target_host_id": 2},
                        headers=csrf_header(app_client))
    assert_denied(r, "migrate.preflight", "pro")


def test_migrate_cross_host_is_refused(app_client, csrf_header):
    r = app_client.post("/api/v1/apps/1/migrate",
                        json={"target_host_id": 2},
                        headers=csrf_header(app_client))
    assert_denied(r, "migrate.cross_host", "pro")


def test_teams_rbac_refuses_team_creation_and_writes_nothing(
        app_client, csrf_header):
    before = count(app_client, Team)
    r = app_client.post("/api/v1/teams", json={"name": "Ops"},
                        headers=csrf_header(app_client))
    assert_denied(r, "teams.rbac", "team")
    assert count(app_client, Team) == before


def test_api_tokens_refuses_key_creation_and_writes_nothing(
        app_client, csrf_header):
    before = count(app_client, ApiKey)
    r = app_client.post("/api/v1/api-keys", json={"name": "ci"},
                        headers=csrf_header(app_client))
    assert_denied(r, "api.tokens", "team")
    assert count(app_client, ApiKey) == before


def test_api_tokens_bearer_auth_401s_without_naming_the_tier(app_client):
    """Deliberately NOT the 403 above. This one is reached by an anonymous
    caller holding a string, and a 403 naming api.tokens would tell them the
    install has the feature switched off, which is state they have not
    authenticated for. Same 401 as any bad key."""
    app_client.cookies.clear()
    r = app_client.get("/api/v1/hosts",
                       headers={"Authorization": "Bearer ppk_anything"})
    assert r.status_code == 401
    assert "api.tokens" not in r.text and "entitlement" not in r.text


def test_auth_oidc_404s_without_naming_the_tier(app_client):
    """Also deliberately not a 403: /auth/oidc/login is how an anonymous caller
    gets a session in the first place, so it must not distinguish "this install
    has no OIDC configured" from "this install's plan does not include it"."""
    app_client.cookies.clear()
    r = app_client.get("/api/v1/auth/oidc/login", follow_redirects=False)
    assert r.status_code == 404
    body = r.json()
    assert body.get("detail", body)["error"] == "oidc_not_configured"
    assert "auth.oidc" not in r.text and "required_tier" not in r.text


def test_every_lever_is_covered_here():
    """A lever is a flag that varies by tier and is enforced. Adding one
    without a denied-branch test is how the untested-branch problem comes
    back, so recompute the set and fail on anything missing.

    Skips when the sibling checkout is absent: the tier maps live in
    proxploy-api, and there is no second copy of them here to read.
    """
    import pathlib

    import yaml

    from proxploy.entitlements.registry import FLAG_KEYS

    p = (pathlib.Path(__file__).resolve().parents[3]
         / "proxploy-api/proxploy_api/tiers.yaml")
    if not p.exists():
        pytest.skip(f"proxploy-api checkout not present at {p}")
    tiers = yaml.safe_load(p.read_text())["tiers"]
    src = "".join(q.read_text()
                  for q in (pathlib.Path(__file__).resolve().parents[1]
                            / "proxploy").rglob("*.py")
                  if q.name != "registry.py")
    fe = pathlib.Path(__file__).resolve().parents[2] / "frontend/src"
    fe_src = "".join(q.read_text() for q in fe.rglob("*")
                     if q.suffix in {".ts", ".tsx"} and "tests" not in str(q))

    def enforced(k):
        return any(f'"{k}"' in b or f"'{k}'" in b or f"`{k}`" in b
                   for b in (src, fe_src))

    varying = {k for k in FLAG_KEYS
               if len({tiers[t][k] for t in ("homelab", "pro", "team")}) > 1}
    # A tier split with nothing enforcing it is a phantom: the pricing page can
    # sell it and the product cannot withhold it. api.rest, rbac.roles and
    # audit.retention were all three of these until 2026-08-28. Splitting a key
    # is now half the work; the gate is the other half.
    phantoms = {k for k in varying if not enforced(k)}
    assert not phantoms, (
        f"tier split with no gate behind it: {sorted(phantoms)}. Either wire "
        f"the gate or drop the split in proxploy-api's tiers.yaml.")
    levers = varying - phantoms
    assert levers == LEVERS, (
        f"levers with no denied-branch test: {sorted(levers - LEVERS)}; "
        f"listed here but no longer a lever: {sorted(LEVERS - levers)}")
