"""PXP-36: PATCH /settings only writes what the UI actually sends.

onboarding.complete (the wizard's finish step) and oidc.* (the OIDC config
key space) are allowed. Everything else 422s, including the self-guard and
license keys that a future dedicated route (PXP-33) will own instead.
"""


def test_allowed_keys_still_write(client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)

    r = client.patch("/api/v1/settings", json={"onboarding.complete": True},
                     headers=csrf_header(client))
    assert r.status_code == 200, r.text
    assert client.get("/api/v1/settings").json()["onboarding.complete"] is True

    r = client.patch("/api/v1/settings", json={"oidc.issuer": "https://idp.example"},
                     headers=csrf_header(client))
    assert r.status_code == 200, r.text
    assert client.get("/api/v1/settings").json()["oidc.issuer"] == "https://idp.example"


def test_keys_outside_the_allowlist_422(client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)

    for key, value in (("self.ctid", 150),
                       ("self.host_id", 1),
                       ("license.install_id", "abc"),
                       ("catalog.source", "community-scripts")):
        r = client.patch("/api/v1/settings", json={key: value},
                         headers=csrf_header(client))
        assert r.status_code == 422, f"{key} should be rejected, got {r.status_code}"

    # None of the rejected keys were persisted.
    body = client.get("/api/v1/settings").json()
    assert "self.ctid" not in body
    assert "self.host_id" not in body
    assert "license.install_id" not in body
    assert "catalog.source" not in body


def test_one_disallowed_key_rejects_the_whole_batch(client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)

    r = client.patch("/api/v1/settings",
                     json={"onboarding.complete": True, "self.host_id": 1},
                     headers=csrf_header(client))
    assert r.status_code == 422

    assert "onboarding.complete" not in client.get("/api/v1/settings").json()
