def test_onboarding_state_progression(client, csrf_header, bootstrap_admin):
    r = client.get("/api/v1/meta/onboarding")
    assert r.json() == {"admin_exists": False, "host_added": False, "complete": False}

    bootstrap_admin(client)
    assert client.get("/api/v1/meta/onboarding").json()["admin_exists"] is True

    r = client.patch("/api/v1/settings", json={"onboarding.complete": True},
                     headers=csrf_header(client))
    assert r.status_code == 200
    assert client.get("/api/v1/meta/onboarding").json()["complete"] is True


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
