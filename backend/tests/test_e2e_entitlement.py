"""DoD (doc 10 Phase 1): Entitlements.enabled() verifies a token signed by the
dormant proxploy-api, and falls back to the built-in map offline.

The only test in this repo that runs a real proxploy-api process, so it is the
only one that catches a contract break between the two services. That makes it
worth the Postgres container it needs: proxploy-api dropped its SQLite fallback
in f134e77 and speaks nothing else.
"""
import base64
import json
import os
import shutil
import socket
import subprocess
import time
import uuid
from pathlib import Path

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

API_REPO = Path(os.environ.get("PROXPLOY_API_REPO",
                Path(__file__).resolve().parents[3] / "proxploy-api"))

pytestmark = pytest.mark.e2e


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def api_dsn():
    """Postgres for the proxploy-api under test.

    Mirrors proxploy-api's own conftest, including the reason it starts a
    container rather than skipping: a skip here would mean the one test that
    proves the two services still agree quietly proves nothing.
    PROXPLOY_API_TEST_DSN wins when set, which is how CI hands us its
    `services:` container.
    """
    dsn = os.environ.get("PROXPLOY_API_TEST_DSN")
    if dsn:
        yield dsn
        return

    if not shutil.which("docker"):
        pytest.skip("no PROXPLOY_API_TEST_DSN and no docker to start Postgres")

    port = _free_port()
    name = f"proxploy-e2e-{uuid.uuid4().hex[:8]}"
    subprocess.run(
        ["docker", "run", "-d", "--rm", "--name", name,
         "-e", "POSTGRES_PASSWORD=proxploy", "-e", "POSTGRES_USER=proxploy",
         "-e", "POSTGRES_DB=proxploy_api",
         "-p", f"127.0.0.1:{port}:5432", "postgres:16"],
        check=True, capture_output=True)
    try:
        deadline = time.time() + 60
        while True:
            if subprocess.run(["docker", "exec", name, "pg_isready", "-U", "proxploy"],
                              capture_output=True).returncode == 0:
                break
            if time.time() > deadline:
                raise RuntimeError("postgres:16 did not become ready in 60s")
            time.sleep(1)
        yield f"postgresql+psycopg://proxploy:proxploy@127.0.0.1:{port}/proxploy_api"
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)


def _keypair() -> tuple[str, str]:
    """The private half as the one-line base64 body, the public half as PEM.

    Generated here rather than by shelling out to the api's
    scripts/gen_signing_key.py: that script deliberately prints both halves to
    stdout with no --out flag (it must never write a live key to disk), so
    calling it would mean scraping key material out of prose.
    """
    priv = Ed25519PrivateKey.generate()
    der = priv.private_bytes(serialization.Encoding.DER,
                             serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption())
    pub = priv.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    return base64.b64encode(der).decode(), pub


def _root_keypair() -> tuple[str, str]:
    """Both halves as PEM: the private one signs the certificate below, the
    public one is what the app is told to trust as a root."""
    priv = Ed25519PrivateKey.generate()
    return (priv.private_bytes(serialization.Encoding.PEM,
                               serialization.PrivateFormat.PKCS8,
                               serialization.NoEncryption()).decode(),
            priv.public_key().public_bytes(
                serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo).decode())


def _mint_cert(root_private_pem: str, root_kid: str, leaf_kid: str,
               leaf_public_pem: str) -> str:
    """Stand in for scripts/mint_leaf_cert.py, which reads the root key from
    stdin on an offline box and is not callable from a test. The claim shape
    is proxploy-api's sign_cert output, pinned by both repos' contract tests.
    """
    pub = base64.b64encode(
        serialization.load_pem_public_key(leaf_public_pem.encode()).public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo)).decode()
    now = int(time.time())
    return jwt.encode({"kid": leaf_kid, "pub": pub, "iat": now, "nbf": now,
                       "exp": now + 180 * 86400},
                      root_private_pem, algorithm="EdDSA",
                      headers={"kid": root_kid})


@pytest.mark.skipif(not API_REPO.exists(), reason="proxploy-api checkout not found")
def test_roundtrip_against_real_dormant_api(tmp_path, api_dsn, csrf_header,
                                            bootstrap_admin):
    py = API_REPO / ".venv/bin/python"
    if not py.exists():
        pytest.skip(f"no proxploy-api venv at {py}")

    signing_key, pub_pem = _keypair()
    root_private_pem, root_public_pem = _root_keypair()
    env = os.environ | {
        "PROXPLOY_API_DB_URL": api_dsn,
        # The key material itself, not a path: renamed from
        # PROXPLOY_API_SIGNING_KEY_FILE in the same change that moved it out of
        # a file. The old name is not an error, it is invisible, so a stale
        # spelling here would leave the service up and unable to sign.
        "PROXPLOY_API_SIGNING_KEY": signing_key,
        # PXP-14 Option C: there is no PROXPLOY_API_KID any more. The kid comes
        # from the certificate, which is the only thing that binds this leaf
        # key to a root the app trusts. Without it the API starts and reports
        # health "degraded: no signing certificate configured", so this is
        # also the assertion that the two repos still agree on the env name.
        "PROXPLOY_API_SIGNING_CERT": _mint_cert(root_private_pem, "e2e-root",
                                                "e2e-kid", pub_pem),
    }
    license_key = subprocess.run(
        [py, str(API_REPO / "scripts/create_license.py"), "--tier", "pro",
         "--db-url", api_dsn],
        check=True, capture_output=True, text=True, env=env).stdout.strip()

    port = _free_port()
    proc = subprocess.Popen(
        [py, "-m", "uvicorn", "--factory", "proxploy_api.main:create_app",
         "--port", str(port)], cwd=API_REPO, env=env)
    try:
        for _ in range(50):
            if proc.poll() is not None:
                pytest.fail(f"proxploy-api exited with {proc.returncode}")
            try:
                r = httpx.get(f"http://127.0.0.1:{port}/v1/health")
                # 503 means it is up but degraded, and the only thing that can
                # be degraded here is the signing key: assert on it rather than
                # letting the loop time out with "did not start", which would
                # point at the wrong problem entirely.
                assert r.status_code == 200, f"api degraded: {r.json()}"
                break
            except httpx.HTTPError:
                time.sleep(0.2)
        else:
            pytest.fail("proxploy-api did not start")

        roots_file = tmp_path / "roots.json"
        roots_file.write_text(json.dumps({"e2e-root": root_public_pem}))

        from fastapi.testclient import TestClient

        from proxploy.api.auth import limiter
        from proxploy.config import Settings
        from proxploy.main import create_app

        limiter.reset()
        s = Settings(db_url=f"sqlite:///{tmp_path}/app.db", data_dir=tmp_path,
                     master_key_file=tmp_path / "master.key",
                     api_base_url=f"http://127.0.0.1:{port}",
                     ent_extra_roots_file=roots_file)
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
