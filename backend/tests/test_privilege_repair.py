import json as jsonlib

from proxploy.services.pveum import CAPABILITIES, merge_role_privs, repair_commands


def test_merge_role_privs_keeps_a_hand_added_privilege():
    union = merge_role_privs({"VM.Console", "CustomOperatorPriv"}, ["Sys.Console"])
    assert union == ("CustomOperatorPriv", "Sys.Console", "VM.Console")


def test_repair_commands_writes_the_union_not_only_the_missing_ones():
    plan = {"ProxployConsole": ["Sys.Console"]}
    existing = {"ProxployConsole": {"VM.Console", "CustomOperatorPriv"}}
    commands = repair_commands(plan, existing)
    assert commands == [
        "pveum role modify ProxployConsole -privs "
        "'CustomOperatorPriv,Sys.Console,VM.Console'"]


def test_repair_commands_skips_a_healthy_role():
    assert repair_commands({"ProxployConsole": []}, {}) == []
    assert repair_commands({}, {}) == []


def test_repair_commands_never_strips_when_the_existing_privileges_could_not_be_read():
    plan = {"ProxployConsole": ["Sys.Console"]}
    existing = {"ProxployConsole": None}
    assert repair_commands(plan, existing) == []


def test_role_privileges_reads_the_roles_own_comma_joined_privs():
    from proxploy.services.proxmox import ProxmoxClient
    from tests.fakes.pve import FakePVE, make_fake_factory

    fake = FakePVE()
    fake.roles_by_id["ProxployConsole"] = "VM.Console,Sys.Console"
    client = ProxmoxClient("https://10.0.0.7:8006", "proxploy@pve!mon", "s3cret",
                           factory=make_fake_factory(fake))
    assert client.role_privileges("ProxployConsole") == {"VM.Console", "Sys.Console"}


def test_role_privileges_returns_none_when_the_read_fails_not_an_empty_set():
    from proxploy.services.proxmox import ProxmoxClient
    from tests.fakes.pve import FakePVE, make_fake_factory

    fake = FakePVE()
    fake.role_read_fail.add("ProxployConsole")
    client = ProxmoxClient("https://10.0.0.7:8006", "proxploy@pve!mon", "s3cret",
                           factory=make_fake_factory(fake))
    assert client.role_privileges("ProxployConsole") is None


def test_role_privileges_returns_none_for_a_role_that_does_not_exist_yet():
    from proxploy.services.proxmox import ProxmoxClient
    from tests.fakes.pve import FakePVE, make_fake_factory

    fake = FakePVE()
    client = ProxmoxClient("https://10.0.0.7:8006", "proxploy@pve!mon", "s3cret",
                           factory=make_fake_factory(fake))
    assert client.role_privileges("ProxployConsole") is None


def _host_with_tokens(app, caps):
    from proxploy.models import Host, HostCredential

    with app.state.sessionmaker() as db:
        host = Host(name="host-01", address="https://10.0.0.7:8006",
                   node_name="pve1", status="connected", pve_version="9.2.10")
        db.add(host)
        db.commit()
        for cap in caps:
            blob, ver = app.state.secretstore.encrypt(jsonlib.dumps(
                {"token_id": f"proxploy@pve!{cap}",
                 "token_secret": "s3cret"}).encode())
            db.add(HostCredential(host_id=host.id, kind=f"api_token:{cap}",
                                  encrypted_blob=blob, key_version=ver,
                                  public_meta=f"proxploy@pve!{cap}"))
        db.commit()
        return host.id


def _add_ssh_key(app, host_id):
    import asyncssh
    from proxploy.models import HostCredential

    pem = asyncssh.generate_private_key("ssh-ed25519").export_private_key()
    blob, ver = app.state.secretstore.encrypt(pem)
    with app.state.sessionmaker() as db:
        db.add(HostCredential(host_id=host_id, kind="ssh_key",
                              encrypted_blob=blob, key_version=ver))
        db.commit()


MONITORING_GRANTED = {p: 1 for p in CAPABILITIES["monitoring"].privileges}


def test_privilege_repair_plan_is_empty_for_a_healthy_host(tmp_path):
    from fastapi.testclient import TestClient
    from proxploy.models import Host
    from proxploy.services.hostclient import privilege_repair_plan
    from tests.fakes.pve import FakePVE
    from tests.support import make_app

    fake = FakePVE(permissions={"/": MONITORING_GRANTED})
    app = make_app(tmp_path, fake=fake)
    with TestClient(app):
        host_id = _host_with_tokens(app, ("monitoring",))
        with app.state.sessionmaker() as db:
            host = db.get(Host, host_id)
            assert privilege_repair_plan(app, db, host) == {}


def test_privilege_repair_plan_names_the_role_for_a_missing_console_privilege(tmp_path):
    from fastapi.testclient import TestClient
    from proxploy.models import Host
    from proxploy.services.hostclient import privilege_repair_plan
    from tests.fakes.pve import FakePVE
    from tests.support import make_app

    perms = {"/": {**MONITORING_GRANTED, "VM.Console": 1}}
    fake = FakePVE(permissions=perms)
    app = make_app(tmp_path, fake=fake)
    with TestClient(app):
        host_id = _host_with_tokens(app, ("monitoring", "console"))
        with app.state.sessionmaker() as db:
            host = db.get(Host, host_id)
            plan = privilege_repair_plan(app, db, host)
    assert plan == {"ProxployConsole": ["Sys.Console"]}


def test_get_privileges_reports_the_repair_commands(tmp_path, csrf_header, bootstrap_admin):
    from tests.fakes.pve import FakePVE
    from tests.support import make_app
    from fastapi.testclient import TestClient

    perms = {"/": {**MONITORING_GRANTED, "VM.Console": 1}}
    fake = FakePVE(permissions=perms)
    fake.roles_by_id["ProxployConsole"] = "VM.Console"
    c = TestClient(make_app(tmp_path, fake=fake))
    with c:
        bootstrap_admin(c)
        host_id = _host_with_tokens(c.app, ("monitoring", "console"))
        r = c.get(f"/api/v1/hosts/{host_id}/privileges", headers=csrf_header(c))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["missing"] == {"ProxployConsole": ["Sys.Console"]}
        assert body["can_auto_repair"] is False
        assert body["commands"] == [
            "pveum role modify ProxployConsole -privs 'Sys.Console,VM.Console'"]


def test_a_healthy_host_produces_an_empty_plan_and_the_repair_runs_no_ssh(
        tmp_path, csrf_header, bootstrap_admin):
    fake_pve = _fake_pve_healthy()

    async def exploding_ssh_factory(*args, **kwargs):
        raise AssertionError("must not open an SSH connection for a healthy host")

    from tests.support import make_app
    from fastapi.testclient import TestClient

    c = TestClient(make_app(tmp_path, fake=fake_pve, ssh_factory=exploding_ssh_factory))
    with c:
        bootstrap_admin(c)
        host_id = _host_with_tokens(c.app, ("monitoring",))
        r = c.get(f"/api/v1/hosts/{host_id}/privileges", headers=csrf_header(c))
        assert r.json() == {"host_id": host_id, "missing": {},
                            "can_auto_repair": False, "commands": []}

        r2 = c.post(f"/api/v1/hosts/{host_id}/privileges/repair",
                    headers=csrf_header(c))
        assert r2.status_code == 200, r2.text
        assert r2.json() == {"repaired": {}, "method": "none"}


def _fake_pve_healthy():
    from tests.fakes.pve import FakePVE

    return FakePVE(permissions={"/": MONITORING_GRANTED})


def test_a_host_with_no_ssh_key_gets_a_409_carrying_the_commands_not_a_500(
        tmp_path, csrf_header, bootstrap_admin):
    from tests.fakes.pve import FakePVE
    from tests.support import make_app
    from fastapi.testclient import TestClient

    perms = {"/": {**MONITORING_GRANTED, "VM.Console": 1}}
    fake = FakePVE(permissions=perms)
    fake.roles_by_id["ProxployConsole"] = "VM.Console"
    c = TestClient(make_app(tmp_path, fake=fake))
    with c:
        bootstrap_admin(c)
        host_id = _host_with_tokens(c.app, ("monitoring", "console"))
        r = c.post(f"/api/v1/hosts/{host_id}/privileges/repair",
                  headers=csrf_header(c))
        assert r.status_code == 409, r.text
        body = r.json()
        assert body["error"] == "no_ssh_key"
        assert body["commands"] == [
            "pveum role modify ProxployConsole -privs 'Sys.Console,VM.Console'"]
        assert body["detail"]

        audit = c.get("/api/v1/audit",
                      params={"action": "host.privileges_repaired"}).json()
        assert any(e["result"] == "refused" for e in audit)


def test_repair_over_ssh_writes_the_union_and_audits_each_privilege_added(
        tmp_path, csrf_header, bootstrap_admin):
    from tests.fakes.pve import FakePVE
    from tests.fakes.ssh import FakeSSHConnection, make_fake_connect_factory
    from tests.support import make_app
    from fastapi.testclient import TestClient

    perms = {"/": {**MONITORING_GRANTED, "VM.Console": 1}}
    fake_pve = FakePVE(permissions=perms)
    fake_pve.roles_by_id["ProxployConsole"] = "VM.Console,CustomOperatorPriv"
    fake_ssh = FakeSSHConnection(host_key_fingerprint="SHA256:abc", stdout_lines=[],
                                 stderr_lines=[], exit_status=0)
    ssh_factory = make_fake_connect_factory(fake_ssh)

    c = TestClient(make_app(tmp_path, fake=fake_pve, ssh_factory=ssh_factory))
    with c:
        bootstrap_admin(c)
        host_id = _host_with_tokens(c.app, ("monitoring", "console"))
        _add_ssh_key(c.app, host_id)

        r = c.post(f"/api/v1/hosts/{host_id}/privileges/repair",
                  headers=csrf_header(c))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body == {"repaired": {"ProxployConsole": ["Sys.Console"]},
                        "method": "ssh"}
        assert fake_ssh.last_command == (
            "pveum role modify ProxployConsole -privs "
            "'CustomOperatorPriv,Sys.Console,VM.Console'")

        audit = c.get("/api/v1/audit",
                      params={"action": "host.privileges_repaired"}).json()
        ok_rows = [e for e in audit if e["result"] == "ok"]
        assert len(ok_rows) == 1
        assert ok_rows[0]["params"]["repaired"] == {
            "ProxployConsole": ["Sys.Console"]}


def test_role_privileges_that_could_not_be_read_never_produces_a_stripping_command(
        tmp_path, csrf_header, bootstrap_admin):
    from tests.fakes.pve import FakePVE
    from tests.support import make_app
    from fastapi.testclient import TestClient

    perms = {"/": {**MONITORING_GRANTED, "VM.Console": 1}}
    fake = FakePVE(permissions=perms)
    fake.role_read_fail.add("ProxployConsole")
    c = TestClient(make_app(tmp_path, fake=fake))
    with c:
        bootstrap_admin(c)
        host_id = _host_with_tokens(c.app, ("monitoring", "console"))
        r = c.get(f"/api/v1/hosts/{host_id}/privileges", headers=csrf_header(c))
        body = r.json()
        assert body["missing"] == {"ProxployConsole": ["Sys.Console"]}
        assert body["commands"] == []
