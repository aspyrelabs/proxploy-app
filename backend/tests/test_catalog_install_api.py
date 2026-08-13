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


def test_install_422s_on_an_override_key_with_a_shell_metacharacter(client, csrf_header,
                                                                    bootstrap_admin):
    """Rejected at the door as bad input, not surfaced as a deep JobFailed; 
    overrides keys are inlined into the SSH command as `var_{key}=...` shell
    syntax (services/appstore.py, executor/ssh.py), so an unvalidated key is
    an untrusted-JSON -> root-shell trust boundary."""
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

    r = client.post(
        "/api/v1/catalog/redis/install",
        json={"host_id": host_id, "name": "Redis", "ctid": 150, "consent": True,
             "overrides": {"os=x; touch /tmp/pwned_key; a": "1"}},
        headers=csrf_header(client))
    assert r.status_code == 422, r.text
    assert client.get("/api/v1/jobs").json() == []  # rejected before a job was ever enqueued


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


def test_install_without_a_ctid_is_accepted_and_enqueues_a_job(client, csrf_header, bootstrap_admin):
    """Task 5: the install form's ctid is optional. Requiring one was a bug,
    the Proxmox installer assigns the next free id itself
    (`${var_ctid:-$NEXTID}`) when told nothing. `ctid` in the enqueued job's
    params must be None here, never an empty string: services/appstore.py's
    run_install turns that None into `var_ctid` being fully ABSENT from the
    environment it hands the remote script."""
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
                    json={"host_id": host_id, "name": "Redis", "consent": True},
                    headers=csrf_header(client))
    assert r.status_code == 202, r.text
    job = r.json()["job"]
    assert job["kind"] == "app.install"
    assert job["params"]["ctid"] is None


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


SHA = "d7bc6b59676456f7a8b3a20f24c3ca589d7fe2f6"


def test_install_lazily_classifies_an_unclassified_entry_before_enqueueing(
        client, csrf_header, bootstrap_admin, monkeypatch):
    """Decision 2: the second of the two moments a ct/ entry's script pair
    is fetched (the first is opening its card) is attempting an install."""
    import httpx

    bootstrap_admin(client)
    with client.app.state.sessionmaker() as db:
        db.add(CatalogEntry(slug="redis", entry_type="ct", upstream_sha=SHA,
                            script_path="ct/redis.sh", installable=None))
        db.commit()
    from tests.support import seed_host_row
    with client.app.state.sessionmaker() as db:
        host = seed_host_row(db)
        db.add(HostCredential(host_id=host.id, kind="ssh_key",
                              encrypted_blob=b"x", key_version=1, public_meta="ssh-ed25519 AAAA"))
        db.commit()
        host_id = host.id

    def fake_get(url, **kw):
        if url.endswith(f"/{SHA}/ct/redis.sh"):
            return httpx.Response(200, text='APP="Redis"\nbuild_container\n')
        if url.endswith(f"/{SHA}/install/redis-install.sh"):
            return httpx.Response(200, text='msg_info "ok"\n')
        return httpx.Response(404)
    monkeypatch.setattr("proxploy.services.catalog._fetch", fake_get)

    r = client.post("/api/v1/catalog/redis/install",
                    json={"host_id": host_id, "name": "Redis", "ctid": 150, "consent": True},
                    headers=csrf_header(client))
    assert r.status_code == 202, r.text
    assert r.json()["job"]["kind"] == "app.install"

    with client.app.state.sessionmaker() as db:
        row = db.query(CatalogEntry).filter_by(slug="redis").one()
        assert row.installable is True


def test_install_400s_when_lazy_classification_cannot_reach_upstream(
        client, csrf_header, bootstrap_admin, monkeypatch):
    """Decision 1: the store degrades silently when the scrape fails, but an
    ACTUAL install attempt that can't verify feasibility is a real, honest
    400, not a job that starts and fails deep inside SSH."""
    bootstrap_admin(client)
    with client.app.state.sessionmaker() as db:
        db.add(CatalogEntry(slug="redis", entry_type="ct", upstream_sha=SHA,
                            script_path="ct/redis.sh", installable=None))
        db.commit()
    from tests.support import seed_host_row
    with client.app.state.sessionmaker() as db:
        host = seed_host_row(db)
        db.add(HostCredential(host_id=host.id, kind="ssh_key",
                              encrypted_blob=b"x", key_version=1, public_meta="ssh-ed25519 AAAA"))
        db.commit()
        host_id = host.id

    def raises(url, **kw):
        raise TimeoutError("upstream timed out")
    monkeypatch.setattr("proxploy.services.catalog._fetch", raises)

    r = client.post("/api/v1/catalog/redis/install",
                    json={"host_id": host_id, "name": "Redis", "ctid": 150, "consent": True},
                    headers=csrf_header(client))
    assert r.status_code == 400
    assert client.get("/api/v1/jobs").json() == []


def test_install_refused_without_host_consent(client, csrf_header, bootstrap_admin):
    """A host with an enrolled ssh_key still needs one explicit tick before its
    first install: the acknowledgement lives on the host, but it has to be
    given at least once. Having a key does not substitute for it."""
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
                    json={"host_id": host_id, "name": "Redis", "ctid": 150},
                    headers=csrf_header(client))
    assert r.status_code == 400
    assert "consent" in r.json()["detail"].lower()


def test_install_succeeds_without_consent_once_the_host_has_already_acknowledged(
        client, csrf_header, bootstrap_admin):
    """The first install on a host that ticks consent records
    Host.install_consent_at; every later install on that same host reads the
    acknowledgement already there instead of asking again."""
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

    first = client.post("/api/v1/catalog/redis/install",
                        json={"host_id": host_id, "name": "Redis", "ctid": 150, "consent": True},
                        headers=csrf_header(client))
    assert first.status_code == 202, first.text

    with client.app.state.sessionmaker() as db:
        from proxploy.models import Host
        assert db.get(Host, host_id).install_consent_at is not None

    second = client.post("/api/v1/catalog/redis/install",
                         json={"host_id": host_id, "name": "Redis", "ctid": 151},
                         headers=csrf_header(client))
    assert second.status_code == 202, second.text


def test_install_404s_on_a_host_that_does_not_exist(client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    with client.app.state.sessionmaker() as db:
        db.add(CatalogEntry(slug="redis", name="Redis", installable=True))
        db.commit()

    r = client.post("/api/v1/catalog/redis/install",
                    json={"host_id": 999, "name": "Redis", "ctid": 150, "consent": True},
                    headers=csrf_header(client))
    assert r.status_code == 404


def test_migration_backfills_consent_only_for_hosts_with_an_enrolled_ssh_key(tmp_path):
    """THE BACKFILL IS A DELIBERATE DECISION, not a default value (see the
    host_install_consent migration's docstring): enrolling an ssh_key
    credential IS the grant of root execution, and those operators ticked the
    old per-install box on every install they ran, so the migration marks
    them acknowledged. Hosts without a key never granted anything, so they
    stay NULL."""
    from pathlib import Path

    from alembic import command
    from alembic.config import Config as AlembicConfig
    from sqlalchemy import create_engine, text

    import proxploy

    db_url = f"sqlite:///{tmp_path}/existing.db"
    cfg = AlembicConfig()
    cfg.set_main_option("script_location", str(Path(proxploy.__file__).parent / "migrations"))
    cfg.set_main_option("sqlalchemy.url", db_url)
    command.upgrade(cfg, "634f5b0f23f0")  # everything before this migration

    eng = create_engine(db_url)
    with eng.begin() as c:
        c.execute(text(
            "INSERT INTO hosts (name, address, verify_tls, status, created_at, updated_at) "
            "VALUES ('with-key', 'https://10.0.0.1:8006', 1, 'connected', "
            "'2026-01-01 00:00:00', '2026-01-01 00:00:00')"))
        c.execute(text(
            "INSERT INTO hosts (name, address, verify_tls, status, created_at, updated_at) "
            "VALUES ('without-key', 'https://10.0.0.2:8006', 1, 'connected', "
            "'2026-01-01 00:00:00', '2026-01-01 00:00:00')"))
        with_key_id = c.execute(text("SELECT id FROM hosts WHERE name = 'with-key'")).scalar_one()
        c.execute(text(
            "INSERT INTO host_credentials (host_id, kind, encrypted_blob, key_version, "
            "public_meta, created_at, updated_at) VALUES "
            "(:hid, 'ssh_key', :blob, 1, 'ssh-ed25519 AAAA', "
            "'2026-01-01 00:00:00', '2026-01-01 00:00:00')"),
            {"hid": with_key_id, "blob": b"\x00\x01"})
    eng.dispose()

    command.upgrade(cfg, "head")

    eng = create_engine(db_url)
    try:
        rows = dict(eng.connect().execute(
            text("SELECT name, install_consent_at FROM hosts")).all())
    finally:
        eng.dispose()
    assert rows["with-key"] is not None
    assert rows["without-key"] is None


def test_install_refuses_a_non_ct_entry(client, csrf_header, bootstrap_admin):
    """A vm/pve/addon/turnkey entry must never be installable through this
    route, even if somehow requested directly by slug."""
    bootstrap_admin(client)
    with client.app.state.sessionmaker() as db:
        db.add(CatalogEntry(slug="dockge-addon", entry_type="addon", installable=False,
                            unsupported_reason="add-on: installs into an existing container"))
        db.commit()
    from tests.support import seed_host_row
    with client.app.state.sessionmaker() as db:
        host = seed_host_row(db)
        db.add(HostCredential(host_id=host.id, kind="ssh_key",
                              encrypted_blob=b"x", key_version=1, public_meta="ssh-ed25519 AAAA"))
        db.commit()
        host_id = host.id

    r = client.post("/api/v1/catalog/dockge-addon/install",
                    json={"host_id": host_id, "name": "Dockge", "ctid": 150, "consent": True},
                    headers=csrf_header(client))
    assert r.status_code == 400
    assert "not an installable LXC app" in r.json()["detail"]
