"""Doc 10 Phase 8 DoD: "a CI script drives the product entirely through
token-authed REST." This module runs in CI with the normal suite — so it IS
that CI script. After a one-time cookie bootstrap (owner signup + API key
creation are the documented cookie-first steps, doc 04/08 — there is no
token yet to make a token), every remaining step below is driven by a
SECOND `TestClient` that never logs in and carries `Authorization: Bearer`
only. Cookies are asserted empty immediately before every call on that
client, proving the header alone authenticates — not a stray session or
CSRF cookie left over from somewhere else.

Task 12 landed `Authorization: Bearer ppk_...` resolution in
`api/deps.py::get_current_user` and the CSRF-middleware exemption for any
request carrying an Authorization header (`middleware.py:20`). This test is
the end-to-end proof that the whole product — hosts, apps, jobs, schedules,
alert rules, audit, and self-revocation — actually stands on that seam, not
just the api-keys router itself (which `test_apikeys.py` already covers in
isolation).
"""
import time

from fastapi.testclient import TestClient

from proxploy.jobs import TERMINAL
from tests.fakes.pve import FakePVE
from tests.support import make_app

HOST = {"name": "pve-01", "address": "https://10.0.0.5:8006",
        "token_id": "proxploy@pve!mon", "token_secret": "s3cret"}


def _bearer(client, method, path, headers, **kw):
    """Fire one call proving the header alone authenticates: assert nothing
    is presented in the cookie jar right before the request, then clear
    whatever the response's CSRF-cookie-on-every-response middleware
    (`middleware.py:27`) just stashed, so the NEXT call starts from the same
    proven-empty state."""
    assert not client.cookies, "a cookie was presented on a bearer-only call"
    r = getattr(client, method)(path, headers=headers, **kw)
    assert r.status_code < 500, r.text
    client.cookies.clear()
    return r


def test_ci_drives_the_product_end_to_end_over_bearer_only(
        tmp_path, csrf_header, bootstrap_admin):
    fake = FakePVE()
    app = make_app(tmp_path, fake=fake)

    with TestClient(app) as cookie_client, TestClient(app) as bearer:
        # --- one-time cookie bootstrap: owner signup + API key mint ---
        bootstrap_admin(cookie_client)
        created = cookie_client.post(
            "/api/v1/api-keys", json={"name": "ci"},
            headers=csrf_header(cookie_client)).json()
        raw, key_id = created["key"], created["id"]
        h = {"Authorization": f"Bearer {raw}"}

        # Never logged in on `bearer` — no cookie has ever been set on it.
        assert not bearer.cookies

        # 1. POST /hosts -> 201; GET /hosts shows it connected.
        r = _bearer(bearer, "post", "/api/v1/hosts", h, json=HOST)
        assert r.status_code == 201, r.text
        host_id = r.json()["id"]
        assert r.json()["status"] == "connected"

        r = _bearer(bearer, "get", "/api/v1/hosts", h)
        assert r.status_code == 200
        assert any(row["id"] == host_id and row["status"] == "connected"
                   for row in r.json())

        # 2. POST /apps/adopt for a CT the fake reports -> identity lands
        # with no SSH needed (adopt never touches the wire; it is the same
        # "trust the operator's word for what's already on the node"
        # identity write an install performs after the fact).
        r = _bearer(bearer, "post", "/api/v1/apps/adopt", h, json={"items": [
            {"host_id": host_id, "ctid": 150, "name": "Immich",
             "catalog_slug": "immich"}]})
        assert r.status_code == 200, r.text  # adopt has no status_code override
        app_id = r.json()["adopted"][0]

        # 3. POST /apps/{id}/start -> 202; poll GET /jobs/{id} to terminal,
        # staying strictly REST (no app.state.jobs.wait — that would reach
        # behind the API, which is exactly what this test is proving is
        # unnecessary).
        r = _bearer(bearer, "post", f"/api/v1/apps/{app_id}/start", h)
        assert r.status_code == 202, r.text
        job_id = r.json()["job"]["id"]

        deadline = time.monotonic() + 10
        status = None
        while status not in TERMINAL and time.monotonic() < deadline:
            status = _bearer(bearer, "get", f"/api/v1/jobs/{job_id}", h).json()["status"]
            if status not in TERMINAL:
                time.sleep(0.05)
        assert status == "succeeded", f"job never succeeded, last status={status!r}"

        # 4. POST /schedules (a backup.sync nightly) -> 201; GET /schedules lists it.
        r = _bearer(bearer, "post", "/api/v1/schedules", h, json={
            "name": "Nightly backup sync", "job_kind": "backup.sync",
            "cron": "0 3 * * *"})
        assert r.status_code == 201, r.text
        schedule_id = r.json()["id"]

        r = _bearer(bearer, "get", "/api/v1/schedules", h)
        assert any(s["id"] == schedule_id for s in r.json())

        # 5. POST /alert-rules -> 201; GET /alerts -> 200.
        r = _bearer(bearer, "post", "/api/v1/alert-rules", h, json={
            "name": "High CPU", "metric": "cpu_pct", "threshold": 90})
        assert r.status_code == 201, r.text

        r = _bearer(bearer, "get", "/api/v1/alerts", h)
        assert r.status_code == 200

        # 6. GET /audit shows the actions above.
        r = _bearer(bearer, "get", "/api/v1/audit", h)
        assert r.status_code == 200
        actions = {row["action"] for row in r.json()}
        assert {"host.create", "apps.adopt", "app.start",
                "schedule.create", "alert.rule.create"} <= actions

        # 7. DELETE /api-keys/{id} (bearer revoking itself) -> 204, and the
        # very next bearer call -> 401.
        r = _bearer(bearer, "delete", f"/api/v1/api-keys/{key_id}", h)
        assert r.status_code == 204, r.text

        r = _bearer(bearer, "get", "/api/v1/hosts", h)
        assert r.status_code == 401
