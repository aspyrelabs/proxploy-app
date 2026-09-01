import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def no_real_tls_probe(monkeypatch):
    """api/hosts.py fetches a node's certificate over a real socket (enrolment
    pins it, POST /{id}/test reports it, GET /{id}/peers shows it per peer).
    Every address in these tests is an RFC1918 literal nothing answers on, so
    the real helper would spend its full 10 second timeout per call.

    Failing fast is the "could not be fetched" path all three already survive,
    so the default here is exactly the behaviour tests had before pinning
    existed: no pin. A test about fingerprints replaces this with its own stub,
    and stubs proxploy.services.proxmox's binding too when it wants
    ProxmoxClient._connect to enforce the pin.
    """
    def _no_probe(host, port=8006):
        raise OSError(f"no TLS probe for {host}:{port} in tests")

    monkeypatch.setattr("proxploy.api.hosts.tls_fingerprint_sha256", _no_probe)


@pytest.fixture
def client(tmp_path):
    from proxploy.api.auth import limiter
    from proxploy.config import Settings
    from proxploy.main import create_app

    limiter.reset()

    s = Settings(
        db_url=f"sqlite:///{tmp_path}/proxploy.db",
        data_dir=tmp_path,
        master_key_file=tmp_path / "master.key",
        release_channel_url=f"file://{tmp_path}/no-release-channel",
        update_check_on_boot=False,
    )
    app = create_app(s)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def csrf_header():
    def _get(client):
        if "pp_csrf" not in client.cookies:
            client.get("/api/v1/meta/health")
        return {"X-CSRF-Token": client.cookies["pp_csrf"]}
    return _get


@pytest.fixture
def bootstrap_admin(csrf_header):
    def _make(client, email="admin@example.com", password="Correct-Horse-Battery-9"):
        client.post("/api/v1/users", json={"email": email, "password": password,
                                           "display_name": "Admin"},
                    headers=csrf_header(client))
        client.post("/api/v1/auth/login", json={"email": email, "password": password},
                    headers=csrf_header(client))
        return client
    return _make


@pytest.fixture
def session(tmp_path):
    """A bare DB session with the schema in place, for services that take a
    session rather than an app. Enters TestClient because the schema is
    created by the app's lifespan, not by make_app itself."""
    from fastapi.testclient import TestClient

    from tests.support import make_app

    app = make_app(tmp_path)
    with TestClient(app), app.state.sessionmaker() as db:
        # Services that notify need the app handle too; Session.info is
        # SQLAlchemy's own place to hang per-session context.
        db.info["app"] = app
        yield db


@pytest.fixture(autouse=True)
def _no_settle_pause(monkeypatch):
    """services/lifecycle.py's SETTLE_DELAY_S is two seconds of deliberate
    waiting per lifecycle action. Real in production, dead weight in a suite
    that runs hundreds of them: it took test_lifecycle_jobs.py from 4s to 31s
    on its own. The one test that is ABOUT the pause sets its own value, which
    still works because it patches the same attribute after this does.
    """
    import proxploy.services.lifecycle as lifecycle
    monkeypatch.setattr(lifecycle, "SETTLE_DELAY_S", 0.0)
