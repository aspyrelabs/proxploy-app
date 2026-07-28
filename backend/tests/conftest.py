import pytest
from fastapi.testclient import TestClient


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
    def _make(client, email="admin@example.com", password="correct-horse-battery"):
        client.post("/api/v1/users", json={"email": email, "password": password,
                                           "display_name": "Admin"},
                    headers=csrf_header(client))
        client.post("/api/v1/auth/login", json={"email": email, "password": password},
                    headers=csrf_header(client))
        return client
    return _make
