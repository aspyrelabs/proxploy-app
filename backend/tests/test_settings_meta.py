def test_onboarding_state_progression(client, csrf_header, bootstrap_admin):
    r = client.get("/api/v1/meta/onboarding")
    # Signed out, this route answers with the three booleans the login page
    # and step 1 of the wizard need, and nothing about the infrastructure.
    assert r.json() == {"admin_exists": False, "complete": False,
                        "oidc": False}  # Task 11: unconfigured OIDC -> False

    bootstrap_admin(client)
    assert client.get("/api/v1/meta/onboarding").json()["admin_exists"] is True

    r = client.patch("/api/v1/settings", json={"onboarding.complete": True},
                     headers=csrf_header(client))
    assert r.status_code == 200
    assert client.get("/api/v1/meta/onboarding").json()["complete"] is True


def test_onboarding_tells_a_stranger_nothing_about_the_hosts(client, csrf_header,
                                                             bootstrap_admin):
    """This route is public, so it must not describe the infrastructure.

    `host_added` and `ssh_pending` told anyone who could reach the port that
    this install manages Proxmox hosts and that a root SSH key is enrolled
    but not yet working. The wizard only needs them from step 2, by which
    point step 1 has signed the admin in, so they are for signed-in callers.
    """
    bootstrap_admin(client)
    signed_in = client.get("/api/v1/meta/onboarding").json()
    assert signed_in["host_added"] is False and signed_in["ssh_pending"] is False

    assert client.post("/api/v1/auth/logout", headers=csrf_header(client)).status_code == 200
    anon = client.get("/api/v1/meta/onboarding")
    assert anon.status_code == 200  # still public: the wizard starts here
    assert "host_added" not in anon.json() and "ssh_pending" not in anon.json()
    # The pre-login fields survive, or a fresh install could not be set up.
    assert anon.json()["admin_exists"] is True
    assert anon.json()["complete"] is False


def test_onboarding_reports_ssh_pending_until_verified(tmp_path, csrf_header, bootstrap_admin):
    """The wizard derives its step from this; an unverified key means the
    authorize step still has something to ask for."""
    from fastapi.testclient import TestClient

    from proxploy.config import Settings
    from proxploy.main import create_app
    from tests.fakes.pve import FakePVE, make_fake_factory
    from tests.fakes.ssh import FakeSSHConnection, make_fake_connect_factory

    fake = FakeSSHConnection(host_key_fingerprint="SHA256:abc",
                             stdout_lines=["ok"], stderr_lines=[], exit_status=0)
    s = Settings(db_url=f"sqlite:///{tmp_path}/sp.db", data_dir=tmp_path,
                 master_key_file=tmp_path / "master.key")
    app = create_app(s, proxmox_factory=make_fake_factory(FakePVE()),
                     ssh_factory=make_fake_connect_factory(fake))
    with TestClient(app) as c:
        bootstrap_admin(c)
        r = c.post("/api/v1/hosts", headers=csrf_header(c), json={
            "name": "pve-01", "address": "https://10.0.0.5:8006",
            "token_id": "proxploy@pve!t", "token_secret": "s",
            "verify_tls": False, "ssh_enroll": True, "ssh_consent": True})
        assert r.status_code == 201, r.text
        hid = r.json()["id"]

        assert c.get("/api/v1/meta/onboarding").json()["ssh_pending"] is True

        r = c.post(f"/api/v1/hosts/{hid}/ssh/verify", headers=csrf_header(c))
        assert r.status_code == 200, r.text

        assert c.get("/api/v1/meta/onboarding").json()["ssh_pending"] is False


def test_settings_crud_hides_enc_and_audits(client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    client.patch("/api/v1/settings", json={"catalog.source": "community-scripts"},
                 headers=csrf_header(client))
    body = client.get("/api/v1/settings").json()
    assert body["catalog.source"] == "community-scripts"
    assert not any(k.endswith(".enc") for k in body)

    r = client.patch("/api/v1/settings", json={"license.refresh_credential.enc": "x"},
                     headers=csrf_header(client))
    assert r.status_code == 422

    audit = client.get("/api/v1/audit", params={"action": "settings.update"}).json()
    assert audit and "catalog.source" in audit[0]["params"]["keys"]


def test_meta_version(client, csrf_header, bootstrap_admin):
    assert client.get("/api/v1/meta/version").status_code == 401
    bootstrap_admin(client)
    body = client.get("/api/v1/meta/version").json()
    assert body["version"] and body["db_backend"] == "sqlite"
    # Crash reporting ships off and stays off unless an operator sets a DSN.
    assert body["reporting"] == "off"


def test_a_malformed_dsn_does_not_stop_the_app_from_starting(tmp_path):
    """This runs on someone else's hardware, often headless.

    Refusing to boot the whole management plane over a typo in an optional
    setting would be a far worse failure than not collecting crashes, so the
    bad DSN is reported through /meta/version instead of raised.
    """
    from proxploy.config import Settings
    from proxploy.main import create_app

    app = create_app(Settings(db_url=f"sqlite:///{tmp_path}/x.db", data_dir=tmp_path,
                              master_key_file=tmp_path / "master.key",
                              sentry_dsn="not-a-dsn"))
    assert app.state.reporting.startswith("error:")
