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


def test_install_409s_when_that_host_ctid_is_already_tracked(client, csrf_header, bootstrap_admin):
    """I6: without this pre-flight the script ran to completion on the real
    node and only then hit IntegrityError inside the job handler, leaving an
    untracked container behind."""
    bootstrap_admin(client)
    from proxploy.models import App
    from tests.support import seed_host_row
    with client.app.state.sessionmaker() as db:
        db.add(CatalogEntry(slug="redis", name="Redis", installable=True,
                            upstream_sha="a" * 40, script_path="ct/redis.sh"))
        host = seed_host_row(db)
        db.add(HostCredential(host_id=host.id, kind="ssh_key", encrypted_blob=b"x",
                              key_version=1, public_meta="ssh-ed25519 AAAA"))
        db.add(App(host_id=host.id, ctid=150, name="Redis", slug="redis-1-150",
                   catalog_slug="redis", web_protocol="http", web_path="/", adopted=True))
        db.commit()
        host_id = host.id

    r = client.post("/api/v1/catalog/redis/install",
                    json={"host_id": host_id, "name": "Redis", "ctid": 150, "consent": True},
                    headers=csrf_header(client))
    assert r.status_code == 409
    assert "already tracked" in r.json()["detail"]
    # ...and no job was enqueued for it
    assert client.get("/api/v1/jobs").json() == [] or all(
        j["kind"] != "app.install" for j in client.get("/api/v1/jobs").json())
