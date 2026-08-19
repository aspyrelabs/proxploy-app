"""PXP-31: activating a license after boot must start the entitlement
refresh loop immediately, not wait for the next restart. Before the fix,
main.py only created the refresh task once at boot, guarded by whether a
license was already on file at that moment.

Also pins that starting it twice is a no-op: activating a license twice
(e.g. a same-install reactivation) must not spawn a second background task.
"""
from tests.test_license_flow import StubLicenseClient, _fixture_app, _fx_path


def test_activating_after_boot_starts_the_loop_once(tmp_path, csrf_header, bootstrap_admin):
    from fastapi.testclient import TestClient

    stub = StubLicenseClient(_fx_path())
    app = _fixture_app(tmp_path, stub)
    with TestClient(app) as client:
        bootstrap_admin(client)

        # No license on file at boot: the lifespan must not have started the loop.
        assert getattr(app.state, "refresh_task", None) is None

        r = client.post("/api/v1/entitlements/license",
                        json={"license_key": "PPL-TEST"}, headers=csrf_header(client))
        assert r.status_code == 200

        task = getattr(app.state, "refresh_task", None)
        assert task is not None and not task.done(), (
            "activating a license after boot must start the refresh loop"
        )

        # Reactivating the same install must not spawn a second task.
        r = client.post("/api/v1/entitlements/license",
                        json={"license_key": "PPL-TEST"}, headers=csrf_header(client))
        assert r.status_code == 200
        assert getattr(app.state, "refresh_task", None) is task, (
            "starting the loop twice must be idempotent, not spawn a second task"
        )

        task.cancel()
