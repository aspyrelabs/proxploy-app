"""DoD (doc 10 Phase 1): Entitlements.enabled() verifies a token signed by the
dormant proxploy-api, and falls back to the built-in map offline."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

API_REPO = Path(os.environ.get("PROXPLOY_API_REPO",
                Path(__file__).resolve().parents[3] / "proxploy-api"))

pytestmark = pytest.mark.e2e


@pytest.mark.skipif(not API_REPO.exists(), reason="proxploy-api checkout not found")
def test_roundtrip_against_real_dormant_api(tmp_path, csrf_header, bootstrap_admin):
    py = API_REPO / ".venv/bin/python"
    env = os.environ | {
        "PROXPLOY_API_DB_URL": f"sqlite:///{tmp_path}/api.db",
        "PROXPLOY_API_SIGNING_KEY_FILE": str(tmp_path / "e2e.key"),
        "PROXPLOY_API_KID": "e2e-kid",
    }
    pub_pem = subprocess.run(
        [py, str(API_REPO / "scripts/gen_signing_key.py"), "--kid", "e2e-kid",
         "--out", str(tmp_path / "e2e.key")],
        check=True, capture_output=True, text=True).stdout
    license_key = subprocess.run(
        [py, str(API_REPO / "scripts/create_license.py"), "--tier", "pro",
         "--db-url", env["PROXPLOY_API_DB_URL"]],
        check=True, capture_output=True, text=True, env=env).stdout.strip()

    proc = subprocess.Popen(
        [py, "-m", "uvicorn", "--factory", "proxploy_api.main:create_app",
         "--port", "8899"], cwd=API_REPO, env=env)
    try:
        for _ in range(50):
            try:
                if httpx.get("http://127.0.0.1:8899/v1/health").status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.2)
        else:
            pytest.fail("proxploy-api did not start")

        keys_file = tmp_path / "keys.json"
        keys_file.write_text(json.dumps({"e2e-kid": pub_pem}))

        from fastapi.testclient import TestClient

        from proxploy.api.auth import limiter
        from proxploy.config import Settings
        from proxploy.main import create_app

        limiter.reset()
        s = Settings(db_url=f"sqlite:///{tmp_path}/app.db", data_dir=tmp_path,
                     master_key_file=tmp_path / "master.key",
                     api_base_url="http://127.0.0.1:8899",
                     ent_extra_keys_file=keys_file)
        with TestClient(create_app(s)) as client:
            bootstrap_admin(client)
            r = client.post("/api/v1/entitlements/license",
                            json={"license_key": license_key},
                            headers=csrf_header(client))
            assert r.status_code == 200 and r.json()["tier"] == "pro"
            ent = client.get("/api/v1/entitlements").json()
            assert ent["tier"] == "pro" and len(ent["features"]) == 81
            assert all(ent["features"].values())  # dormant api: all entitled
    finally:
        proc.terminate()
        proc.wait(timeout=10)
