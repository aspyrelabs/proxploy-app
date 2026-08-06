import json


class StubLicenseClient:
    def __init__(self, fixture_path):
        fx = json.loads(fixture_path.read_text())
        self._fx = fx
        self.activations = []
        self.refreshes = []

    def _mint(self):
        import jwt

        from proxploy.models import utcnow
        claims = dict(self._fx["claims"])
        now = int(utcnow().timestamp())
        claims.update(iat=now, exp=now + 72 * 3600, grace_until=now + 30 * 86400)
        return jwt.encode(claims, self._fx["private_key_pem"], algorithm="EdDSA",
                          headers={"kid": self._fx["kid"]})

    def activate(self, license_key, install_id):
        self.activations.append((license_key, install_id))
        return {"token": self._mint(), "refresh_credential": "cred-123"}

    def refresh(self, refresh_credential, install_id):
        assert refresh_credential == "cred-123"
        self.refreshes.append(install_id)
        return {"token": self._mint()}


def test_license_set_refresh_remove(tmp_path, csrf_header, bootstrap_admin):
    from pathlib import Path

    from fastapi.testclient import TestClient

    from proxploy.api.auth import limiter
    from proxploy.config import Settings
    from proxploy.main import create_app

    fx_path = Path(__file__).parent / "contract" / "entitlement_token.fixture.json"
    fx = json.loads(fx_path.read_text())
    stub = StubLicenseClient(fx_path)
    limiter.reset()
    s = Settings(db_url=f"sqlite:///{tmp_path}/lic.db", data_dir=tmp_path,
                 master_key_file=tmp_path / "master.key")
    app = create_app(s, public_keys={fx["kid"]: fx["public_key_pem"]},
                     license_client=stub)
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
        # refresh must send the same install_id activate used — Task 3 made
        # it required on the API side.
        assert stub.refreshes == [stub.activations[0][1]]

        assert client.delete("/api/v1/entitlements/license",
                             headers=csrf_header(client)).status_code == 200
        ent = client.get("/api/v1/entitlements").json()
        assert ent["tier"] == "builtin" and len(ent["features"]) == 81


def test_client_revoke_sends_credential_and_install_id(monkeypatch):
    """LicenseClient.revoke() is new (Task 8) — pin its request shape against
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
