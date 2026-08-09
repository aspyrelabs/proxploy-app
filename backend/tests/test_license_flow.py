import json


class StubLicenseClient:
    """Mints a token + a cert from the shared contract fixture's TEST-ONLY
    root, mirroring what proxploy-api's dormant license service will hand
    back (docs/09)."""
    def __init__(self, fixture_path, *, refresh_returns_cert=True):
        fx = json.loads(fixture_path.read_text())
        self._fx = fx
        self._refresh_returns_cert = refresh_returns_cert
        self.activations = []
        self.refreshes = []

    def _mint_cert(self):
        import jwt

        from proxploy.models import utcnow

        now = utcnow()
        claims = {"kid": self._fx["leaf_kid"], "pub": self._fx["leaf_public_body"],
                  "iat": int(now.timestamp()),
                  "nbf": int(now.timestamp()) - 3600,
                  "exp": int(now.timestamp()) + 180 * 86400}
        return jwt.encode(claims, self._fx["root_private_key_pem"], algorithm="EdDSA",
                          headers={"kid": self._fx["root_kid"]})

    def _mint_token(self):
        import jwt

        from proxploy.models import utcnow
        claims = dict(self._fx["claims"])
        now = int(utcnow().timestamp())
        claims.update(iat=now, exp=now + 72 * 3600, grace_until=now + 30 * 86400)
        return jwt.encode(claims, self._fx["leaf_private_key_pem"], algorithm="EdDSA",
                          headers={"kid": self._fx["leaf_kid"]})

    def activate(self, license_key, install_id):
        self.activations.append((license_key, install_id))
        return {"token": self._mint_token(), "cert": self._mint_cert(),
                "refresh_credential": "cred-123"}

    def refresh(self, refresh_credential, install_id):
        assert refresh_credential == "cred-123"
        self.refreshes.append(install_id)
        out = {"token": self._mint_token()}
        if self._refresh_returns_cert:
            out["cert"] = self._mint_cert()
        return out


def _fixture_app(tmp_path, stub, db_name="lic.db"):
    from proxploy.api.auth import limiter
    from proxploy.config import Settings
    from proxploy.main import create_app

    fx_path = _fx_path()
    fx = json.loads(fx_path.read_text())
    limiter.reset()
    s = Settings(db_url=f"sqlite:///{tmp_path}/{db_name}", data_dir=tmp_path,
                 master_key_file=tmp_path / "master.key")
    return create_app(s, roots={fx["root_kid"]: fx["root_public_key_pem"]},
                      license_client=stub)


def _fx_path():
    from pathlib import Path

    return Path(__file__).parent / "contract" / "entitlement_token.fixture.json"


def test_license_set_refresh_remove(tmp_path, csrf_header, bootstrap_admin):
    from fastapi.testclient import TestClient

    stub = StubLicenseClient(_fx_path())
    app = _fixture_app(tmp_path, stub)
    with TestClient(app) as client:
        bootstrap_admin(client)

        r = client.post("/api/v1/entitlements/license",
                        json={"license_key": "PPL-TEST"}, headers=csrf_header(client))
        assert r.status_code == 200
        assert stub.activations[0][0] == "PPL-TEST"

        ent = client.get("/api/v1/entitlements").json()
        assert ent["tier"] == "pro" and ent["grace"]["in_grace"] is False
        assert ent["features"]["auth.oidc"] is False   # token map is authoritative

        assert client.post("/api/v1/entitlements/refresh",
                           headers=csrf_header(client)).status_code == 200
        # refresh must send the same install_id activate used: Task 3 made
        # it required on the API side.
        assert stub.refreshes == [stub.activations[0][1]]

        assert client.delete("/api/v1/entitlements/license",
                             headers=csrf_header(client)).status_code == 200
        ent = client.get("/api/v1/entitlements").json()
        assert ent["tier"] == "builtin" and len(ent["features"]) == 81


def test_a_token_the_install_cannot_verify_does_not_destroy_the_cached_one(
        tmp_path, csrf_header, bootstrap_admin):
    """Pins the ladder (PXP-14 Option C): a refresh that comes back with a
    token this install cannot verify (here, no cert at all) must 502 rather
    than silently landing, and the previously-applied tier must survive it."""
    from fastapi.testclient import TestClient

    stub = StubLicenseClient(_fx_path(), refresh_returns_cert=False)
    app = _fixture_app(tmp_path, stub)
    with TestClient(app) as client:
        bootstrap_admin(client)

        r = client.post("/api/v1/entitlements/license",
                        json={"license_key": "PPL-TEST"}, headers=csrf_header(client))
        assert r.status_code == 200
        assert r.json()["tier"] == "pro"

        r = client.post("/api/v1/entitlements/refresh", headers=csrf_header(client))
        assert r.status_code == 502
        assert "cannot verify" in r.json()["detail"]

        ent = client.get("/api/v1/entitlements").json()
        assert ent["tier"] == "pro"  # the good cached token is still in effect


def test_client_revoke_sends_credential_and_install_id(monkeypatch):
    """LicenseClient.revoke() is new (Task 8), pin its request shape against
    POST /v1/licenses/revoke, which Task 3 made require both fields."""
    import httpx

    from proxploy.services.license_client import LicenseClient

    captured = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["json"] = kwargs["json"]
        return httpx.Response(200, json={"revoked": True},
                              request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", fake_post)
    out = LicenseClient("http://licensing.example").revoke("cred-abc", "install-xyz")

    assert out == {"revoked": True}
    assert captured["url"] == "http://licensing.example/v1/licenses/revoke"
    assert captured["json"] == {"refresh_credential": "cred-abc", "install_id": "install-xyz"}
