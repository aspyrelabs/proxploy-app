from proxploy.models import CatalogEntry, HostCredential


def test_install_requires_consent(client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    with client.app.state.sessionmaker() as db:
        db.add(CatalogEntry(slug="redis", name="Redis", installable=True))
        db.commit()
    from tests.support import seed_host_row
    with client.app.state.sessionmaker() as db:
        host = seed_host_row(db)
        host_id = host.id

    r = client.post("/api/v1/catalog/redis/install",
                    json={"host_id": host_id, "name": "Redis", "ctid": 150, "consent": False},
                    headers=csrf_header(client))
    assert r.status_code == 400


def test_install_enqueues_an_app_install_job(client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    with client.app.state.sessionmaker() as db:
        db.add(CatalogEntry(slug="redis", name="Redis", installable=True))
        db.commit()
    from tests.support import seed_host_row
    with client.app.state.sessionmaker() as db:
        host = seed_host_row(db)
        db.add(HostCredential(host_id=host.id, kind="ssh_key",
                              encrypted_blob=b"x", key_version=1, public_meta="ssh-ed25519 AAAA"))
        db.commit()
        host_id = host.id

    r = client.post("/api/v1/catalog/redis/install",
                    json={"host_id": host_id, "name": "Redis", "ctid": 150, "consent": True},
                    headers=csrf_header(client))
    assert r.status_code == 202
    assert r.json()["job"]["kind"] == "app.install"


def test_install_refuses_a_host_without_an_enrolled_ssh_key(client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    with client.app.state.sessionmaker() as db:
        db.add(CatalogEntry(slug="redis", name="Redis", installable=True))
        db.commit()
    from tests.support import seed_host_row
    with client.app.state.sessionmaker() as db:
        host = seed_host_row(db)
        host_id = host.id

    r = client.post("/api/v1/catalog/redis/install",
                    json={"host_id": host_id, "name": "Redis", "ctid": 150, "consent": True},
                    headers=csrf_header(client))
    assert r.status_code == 400
    assert "ssh_key" in r.json()["detail"]
