"""PXP-33: PUT /hosts/self is the only place self.host_id gets written (PATCH
/settings' allowlist deliberately rejects it, PXP-36). Before this route
existed nothing ever wrote the key, so every selfguard read took the fail-open
branch regardless of what was actually enrolled -- this file is the check
that stops being true silently again.
"""
import json

from proxploy.models import Host
from proxploy.services.selfguard import is_self_host_node
from proxploy.services.settings import get_setting
from tests.support import make_app, seed_host_row


def _seeded(tmp_path):
    from fastapi.testclient import TestClient

    app = make_app(tmp_path)
    c = TestClient(app)

    def seed(name="host-01", node="pve1"):
        with app.state.sessionmaker() as db:
            h = seed_host_row(db, name=name, node=node)
            return h.id
    return app, c, seed


def test_setting_self_host_makes_node_power_self_detection_real(tmp_path, csrf_header, bootstrap_admin):
    app, c, seed = _seeded(tmp_path)
    with c:
        bootstrap_admin(c)
        host_id = seed(node="pve1")

        # Before the answer is recorded, detection fails open (today's
        # behaviour, must survive this route existing).
        with app.state.sessionmaker() as db:
            host = db.get(Host, host_id)
            assert is_self_host_node(db, host, "pve1") is False

        r = c.put("/api/v1/hosts/self", json={"host_id": host_id},
                  headers=csrf_header(c))
        assert r.status_code == 200, r.text
        assert r.json() == {"host_id": host_id}

        with app.state.sessionmaker() as db:
            assert get_setting(db, "self.host_id") == host_id
            host = db.get(Host, host_id)
            # Real branch now: the entry node is flagged self...
            assert is_self_host_node(db, host, "pve1") is True
            # ...and a sibling node of the same Host row is still not.
            assert is_self_host_node(db, host, "pve2") is False


def test_unknown_host_id_is_rejected_not_stored(tmp_path, csrf_header, bootstrap_admin):
    app, c, seed = _seeded(tmp_path)
    with c:
        bootstrap_admin(c)
        seed()  # host id 1 enrolled; 999 never was

        r = c.put("/api/v1/hosts/self", json={"host_id": 999},
                  headers=csrf_header(c))
        assert r.status_code == 404

        with app.state.sessionmaker() as db:
            assert get_setting(db, "self.host_id") is None


def test_none_of_these_is_recorded_and_keeps_fail_open(tmp_path, csrf_header, bootstrap_admin):
    app, c, seed = _seeded(tmp_path)
    with c:
        bootstrap_admin(c)
        host_id = seed(node="pve1")

        r = c.put("/api/v1/hosts/self", json={"host_id": None},
                  headers=csrf_header(c))
        assert r.status_code == 200, r.text
        assert r.json() == {"host_id": None}

        with app.state.sessionmaker() as db:
            from proxploy.models import AppSetting
            row = db.query(AppSetting).filter_by(key="self.host_id").one_or_none()
            # Answered (a row exists)...
            assert row is not None
            # ...but the value is still None, so every read stays fail-open.
            assert get_setting(db, "self.host_id") is None
            host = db.get(Host, host_id)
            assert is_self_host_node(db, host, "pve1") is False


def test_write_rejected_through_the_settings_allowlist_route(csrf_header, bootstrap_admin, client):
    """PXP-36 note: self.host_id must stay rejected by the general allowlist
    route even after this dedicated one exists."""
    bootstrap_admin(client)
    r = client.patch("/api/v1/settings", json={"self.host_id": 1},
                     headers=csrf_header(client))
    assert r.status_code == 422
