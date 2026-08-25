"""A CT Proxploy restored is Proxploy's, and does not ask to be adopted.

Reported on hardware 2026-08-25: an app was deleted, restored from its own
backup, and came back asking to be adopted. Restore-as-new takes a FRESH vmid
from cluster_nextid(), and a CT is only "tracked" when an App row exists for
(host_id, ctid), so nothing linked the restored container to the app it had
been. It is the one case where Proxploy knows perfectly well where the
container came from, because it put it there.
"""
import json

from fastapi.testclient import TestClient

from proxploy.models import App, Backup, CatalogEntry, Host, HostCredential
from tests.support import make_app


def _seed(tmp_app, *, guest_name="anytype-server", guest_type="ct"):
    with tmp_app.state.sessionmaker() as db:
        host = Host(name="host-01", address="https://10.0.0.7:8006",
                    node_name="pve1", status="connected")
        db.add(host)
        db.commit()
        blob, ver = tmp_app.state.secretstore.encrypt(json.dumps(
            {"token_id": "proxploy@pve!lc", "token_secret": "s"}).encode())
        for cap in ("backup", "lifecycle"):
            db.add(HostCredential(host_id=host.id, kind=f"api_token:{cap}",
                                  encrypted_blob=blob, key_version=ver))
        # The slug a container installed from the store actually carries: the
        # match is an exact normalised-name one, so "anytype-server" resolves
        # the "anytype-server" entry and would NOT resolve an "anytype" one.
        db.add(CatalogEntry(slug="anytype-server", name="Anytype Server",
                            category="productivity", port=8080))
        b = Backup(host_id=host.id, storage="nfs-bk", guest_type=guest_type,
                   guest_vmid=110, guest_name=guest_name,
                   volid=f"nfs-bk:backup/vzdump-lxc-110-x.tar.zst")
        db.add(b)
        db.commit()
        return host.id, b.id


def test_a_restored_container_is_adopted_and_keeps_its_catalog_entry(tmp_path):
    from proxploy.services.backupjobs import adopt_restored
    app = make_app(tmp_path)
    with TestClient(app):
        host_id, backup_id = _seed(app)
        adopt_restored(app, backup_id, new_vmid=131)

        with app.state.sessionmaker() as db:
            row = db.query(App).filter_by(host_id=host_id, ctid=131).one()
            assert row.name == "anytype-server"
            # The name resolves to the catalog entry, so what the app WAS comes
            # back with it, not just that it exists.
            assert row.catalog_slug == "anytype-server"
            assert row.category == "productivity"
            assert row.web_port == 8080
            assert row.adopted is True


def test_a_near_miss_name_matches_nothing_rather_than_guessing(tmp_path):
    """The match is exact on the normalised name, deliberately: a container
    called "anytype-server-old" is not the store's anytype-server, and a fuzzy
    match here would quietly attach the wrong catalog entry to a restored app.
    It adopts with no slug instead, which is recoverable; a wrong slug is not
    obviously wrong to anyone reading it."""
    from proxploy.services.backupjobs import adopt_restored
    app = make_app(tmp_path)
    with TestClient(app):
        host_id, backup_id = _seed(app, guest_name="anytype-server-old")
        adopt_restored(app, backup_id, new_vmid=135)

        with app.state.sessionmaker() as db:
            row = db.query(App).filter_by(host_id=host_id, ctid=135).one()
            assert row.catalog_slug is None


def test_a_container_the_catalog_does_not_know_is_still_adopted(tmp_path):
    """A hand-built CT adopts with no slug, which is exactly what adopting it
    by hand would have done. Not knowing what it is must not mean leaving it to
    ask."""
    from proxploy.services.backupjobs import adopt_restored
    app = make_app(tmp_path)
    with TestClient(app):
        host_id, backup_id = _seed(app, guest_name="my-own-thing")
        adopt_restored(app, backup_id, new_vmid=132)

        with app.state.sessionmaker() as db:
            row = db.query(App).filter_by(host_id=host_id, ctid=132).one()
            assert row.name == "my-own-thing"
            assert row.catalog_slug is None
            assert row.category is None


def test_a_restored_vm_adopts_nothing(tmp_path):
    """VMs are mirrored as Vm rows by the poller and have no adoption at all,
    so there is nothing here to do for one."""
    from proxploy.services.backupjobs import adopt_restored
    app = make_app(tmp_path)
    with TestClient(app):
        host_id, backup_id = _seed(app, guest_name="win11", guest_type="vm")
        adopt_restored(app, backup_id, new_vmid=133)

        with app.state.sessionmaker() as db:
            assert db.query(App).filter_by(host_id=host_id, ctid=133).count() == 0


def test_adopting_the_same_ctid_twice_does_not_make_a_second_row(tmp_path):
    """ux_apps_host_ctid would refuse it, and a restore must not fail on a
    conflict it can just leave alone."""
    from proxploy.services.backupjobs import adopt_restored
    app = make_app(tmp_path)
    with TestClient(app):
        host_id, backup_id = _seed(app)
        adopt_restored(app, backup_id, new_vmid=134)
        adopt_restored(app, backup_id, new_vmid=134)

        with app.state.sessionmaker() as db:
            assert db.query(App).filter_by(host_id=host_id, ctid=134).count() == 1


def test_an_in_place_restore_is_left_alone(tmp_path):
    """The App row is still there for an in-place restore: the guest was
    overwritten, not replaced, so there is nothing to adopt."""
    from proxploy.services.backupjobs import adopt_restored
    app = make_app(tmp_path)
    with TestClient(app):
        host_id, backup_id = _seed(app)
        with app.state.sessionmaker() as db:
            db.add(App(host_id=host_id, ctid=110, name="anytype-server",
                       slug="anytype-110", catalog_slug="anytype"))
            db.commit()
        adopt_restored(app, backup_id, new_vmid=110)

        with app.state.sessionmaker() as db:
            rows = db.query(App).filter_by(host_id=host_id, ctid=110).all()
            assert len(rows) == 1
            assert rows[0].slug == "anytype-110"   # untouched
