import json


class StubLicenseClient:
    """Mints a token + a cert from the shared contract fixture's TEST-ONLY
    root, mirroring what proxploy-api's dormant license service will hand
    back."""
    def __init__(self, fixture_path, *, refresh_returns_cert=True):
        fx = json.loads(fixture_path.read_text())
        self._fx = fx
        self._refresh_returns_cert = refresh_returns_cert
        self.activate_calls = []
        self.refreshes = []
        self.transfers = []
        self.releases = []

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

    def activate(self, license_key, install_id, fingerprint=None):
        # Recorded, not ignored: a stub that quietly drops the identity the
        # real service uses to enforce seats would let the app stop sending
        # it with every test still green.
        self.activate_calls.append((license_key, install_id, fingerprint))
        return {"token": self._mint_token(), "cert": self._mint_cert(),
                "refresh_credential": "cred-123"}

    def transfer(self, license_key, install_id, recovery_code, fingerprint=None):
        self.transfers.append((license_key, install_id, recovery_code, fingerprint))
        return {"token": self._mint_token(), "cert": self._mint_cert(),
                "refresh_credential": "cred-after-transfer"}

    def release(self, refresh_credential, install_id):
        self.releases.append((refresh_credential, install_id))
        return {"released": True}

    def activations(self, refresh_credential, install_id):
        return {"activations": []}

    def refresh(self, refresh_credential, install_id, fingerprint=None,
                heartbeat_seq=None):
        assert refresh_credential in ("cred-123", "cred-after-transfer")
        self.refreshes.append((install_id, fingerprint, heartbeat_seq))
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
        assert stub.activate_calls[0][0] == "PPL-TEST"

        ent = client.get("/api/v1/entitlements").json()
        assert ent["tier"] == "pro" and ent["grace"]["in_grace"] is False
        assert ent["features"]["auth.oidc"] is False   # token map is authoritative

        assert client.post("/api/v1/entitlements/refresh",
                           headers=csrf_header(client)).status_code == 200
        # refresh must send the same install_id activate used: Task 3 made
        # it required on the API side.
        assert [r[0] for r in stub.refreshes] == [stub.activate_calls[0][1]]

        assert client.delete("/api/v1/entitlements/license",
                             headers=csrf_header(client)).status_code == 200
        ent = client.get("/api/v1/entitlements").json()
        assert ent["tier"] == "builtin" and len(ent["features"]) == 87


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


def test_installation_identity_survives_removing_a_license(tmp_path, bootstrap_admin,
                                                           csrf_header):
    """It used to live under `license.install_id` and be deleted with the
    licence, so a reinstall came back as a stranger and had to force-transfer
    a seat it already owned."""
    from fastapi.testclient import TestClient

    from proxploy.api.entitlements import INSTALL_ID_KEY
    from proxploy.services.settings import get_setting

    stub = StubLicenseClient(_fx_path())
    app = _fixture_app(tmp_path, stub)
    with TestClient(app) as client:
        bootstrap_admin(client)
        client.post("/api/v1/entitlements/license",
                    json={"license_key": "PPL-TEST"}, headers=csrf_header(client))
        with app.state.sessionmaker() as db:
            first = get_setting(db, INSTALL_ID_KEY)
        assert first

        client.delete("/api/v1/entitlements/license", headers=csrf_header(client))
        with app.state.sessionmaker() as db:
            assert get_setting(db, INSTALL_ID_KEY) == first

        client.post("/api/v1/entitlements/license",
                    json={"license_key": "PPL-TEST"}, headers=csrf_header(client))
        assert stub.activate_calls[1][1] == first


def test_removing_a_license_releases_the_seat(tmp_path, bootstrap_admin, csrf_header):
    """The cooperative path. Without it, every rebuild needs the recovery
    code, which is exactly the friction the release endpoint exists to
    remove."""
    from fastapi.testclient import TestClient

    stub = StubLicenseClient(_fx_path())
    app = _fixture_app(tmp_path, stub)
    with TestClient(app) as client:
        bootstrap_admin(client)
        client.post("/api/v1/entitlements/license",
                    json={"license_key": "PPL-TEST"}, headers=csrf_header(client))
        client.delete("/api/v1/entitlements/license", headers=csrf_header(client))
    assert stub.releases and stub.releases[0][0] == "cred-123"


def test_a_release_that_cannot_reach_the_service_still_removes_the_license(
        tmp_path, bootstrap_admin, csrf_header):
    """An owner removing a licence from a box that cannot reach the service
    must not be stuck with it. The seat is recovered by transfer instead."""
    from fastapi.testclient import TestClient

    from proxploy.services.license_client import LicenseApiError

    stub = StubLicenseClient(_fx_path())

    def _boom(cred, install_id):
        raise LicenseApiError("network is down")
    stub.release = _boom

    app = _fixture_app(tmp_path, stub)
    with TestClient(app) as client:
        bootstrap_admin(client)
        client.post("/api/v1/entitlements/license",
                    json={"license_key": "PPL-TEST"}, headers=csrf_header(client))
        assert client.delete("/api/v1/entitlements/license",
                             headers=csrf_header(client)).status_code == 200
        assert client.get("/api/v1/entitlements").json()["tier"] == "builtin"


def test_a_seat_conflict_reaches_the_browser_as_409_with_the_occupant(
        tmp_path, bootstrap_admin, csrf_header):
    """Not the 502 a generic licensing failure gets: this is a state the
    owner can act on, and the UI cannot offer a transfer without the
    occupant summary."""
    from fastapi.testclient import TestClient

    from proxploy.services.license_client import SeatOccupied

    stub = StubLicenseClient(_fx_path())

    def _occupied(key, install_id, fingerprint=None):
        raise SeatOccupied({"error": "license already active on another installation",
                            "occupant": {"installation_id": "inst-other",
                                         "last_seen_at": "2026-08-26T10:00:00",
                                         "activated_at": None, "stale": False}})
    stub.activate = _occupied

    app = _fixture_app(tmp_path, stub)
    with TestClient(app) as client:
        bootstrap_admin(client)
        r = client.post("/api/v1/entitlements/license",
                        json={"license_key": "PPL-TEST"}, headers=csrf_header(client))
        assert r.status_code == 409
        # problem+json merges a dict detail into the top level (main.py).
        assert r.json()["occupant"]["installation_id"] == "inst-other"


def test_transfer_sends_the_recovery_code_and_resets_the_sequence(
        tmp_path, bootstrap_admin, csrf_header):
    """The sequence must not carry over: the transferred-from install keeps
    heartbeating until its credential is refused, and inheriting its counter
    would make this install's first beat look like a replay."""
    from fastapi.testclient import TestClient

    from proxploy.api.entitlements import HEARTBEAT_SEQ_KEY
    from proxploy.services.settings import get_setting

    stub = StubLicenseClient(_fx_path())
    app = _fixture_app(tmp_path, stub)
    with TestClient(app) as client:
        bootstrap_admin(client)
        client.post("/api/v1/entitlements/license",
                    json={"license_key": "PPL-TEST"}, headers=csrf_header(client))
        client.post("/api/v1/entitlements/refresh", headers=csrf_header(client))
        with app.state.sessionmaker() as db:
            assert int(get_setting(db, HEARTBEAT_SEQ_KEY)) >= 1

        r = client.post("/api/v1/entitlements/license/transfer",
                        json={"license_key": "PPL-TEST", "recovery_code": "RC-1"},
                        headers=csrf_header(client))
        assert r.status_code == 200
        assert stub.transfers[0][2] == "RC-1"
        with app.state.sessionmaker() as db:
            assert get_setting(db, HEARTBEAT_SEQ_KEY) == "0"


def test_the_heartbeat_carries_identity_and_a_rising_sequence(tmp_path, bootstrap_admin,
                                                              csrf_header):
    """The two signals the service uses to notice one seat being used from
    two machines. If the app stops sending either, clone detection silently
    stops working with nothing else failing."""
    from fastapi.testclient import TestClient

    stub = StubLicenseClient(_fx_path())
    app = _fixture_app(tmp_path, stub)
    with TestClient(app) as client:
        bootstrap_admin(client)
        client.post("/api/v1/entitlements/license",
                    json={"license_key": "PPL-TEST"}, headers=csrf_header(client))
        for _ in range(3):
            client.post("/api/v1/entitlements/refresh", headers=csrf_header(client))

    installs = {r[0] for r in stub.refreshes}
    assert len(installs) == 1 and installs.pop()
    seqs = [r[2] for r in stub.refreshes]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs), seqs
    assert all(r[1] for r in stub.refreshes), "fingerprint must be sent every beat"
