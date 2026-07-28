import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path):
    from proxploy.config import Settings
    from proxploy.main import create_app

    s = Settings(
        db_url=f"sqlite:///{tmp_path}/proxploy.db",
        data_dir=tmp_path,
        master_key_file=tmp_path / "master.key",
    )
    app = create_app(s)
    with TestClient(app) as c:
        yield c
