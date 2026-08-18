# backend/tests/test_migrate_job.py
"""`migrate.app` job handler (Phase 8 Task 15, services/migrate.py).

FAKES vs HARDWARE, read this before trusting a green run: there is no live
Proxmox host in this repo and never will be. Every assertion here is proven
against `tests/fakes/pve.py`'s `FakePVE`, a hand-maintained mimic of the
proxmoxer attribute surface fed rows this file writes itself. What that
proves: the handler's call sequence (stop -> vzdump/migrate -> restore/skip
-> start -> health check -> repoint), its honesty properties (downtime
MEASURED from a real wall-clock delta rather than carried over from
preflight's estimate, the source guest never destroyed, `apps.host_id`/
`apps.ctid` never rewritten before the target's health check passes), and
its JobFailed/rollback-messaging on the way real proxmoxer calls fail. What
it does NOT prove: that a real PVE 8.x/9.x vzdump/restore/migrate cycle
actually behaves this way on real disks over a real network, or that
`cluster_resources()` transitions a guest to "running" the way FakePVE's
static snapshot does (FakePVE does not simulate state transitions, a test
that wants the target to "be seen running" seeds that row itself, exactly
like tests/test_app_update_job.py's `add_ct(..., status="running")`
precedent). That needs live hardware.
"""
import asyncio
import json

import pytest

from proxploy.jobs import HANDLERS, JobBackend, JobContext, JobFailed
from proxploy.models import App, Host, HostCredential, Job, JobEvent
from proxploy.services import migrate as migrate_mod  # registers migrate.app
from tests.fakes.pve import FakePVE, make_addressed_factory
from tests.support import make_job_app

SRC_ADDR = "https://10.0.0.101:8006"
TGT_ADDR = "https://10.0.0.102:8006"
SRC_HOSTNAME = "10.0.0.101"
TGT_HOSTNAME = "10.0.0.102"

SHARED_ROW = {"storage": "pbs-ds", "type": "pbs", "content": "backup"}


def _two_host_app(tmp_path, fakes: dict):
    app = make_job_app(tmp_path)
    app.state.proxmox_factory = make_addressed_factory(fakes)
    app.state.jobs = JobBackend(app)
    return app


def _seed(app, *, src_node="pve-src", tgt_node="pve-tgt", ctid=150):
    with app.state.sessionmaker() as db:
        src = Host(name="host-src", address=SRC_ADDR, node_name=src_node,
                  status="connected", pve_version="8.4.1")
        tgt = Host(name="host-tgt", address=TGT_ADDR, node_name=tgt_node,
                  status="connected", pve_version="8.4.1")
        db.add(src); db.add(tgt); db.commit()
        # Migration needs monitoring (preflight/health-check reads),
        # lifecycle (stop/start/cluster-migrate) and backup (vzdump/
        # restore/cleanup) on BOTH hosts (services/migrate.py::_load).
        # FakePVE does not validate token identity against capability, so
        # every row below reuses the same secret; what matters here is that
        # `client_for_host(..., capability=X)` finds a row for every X this
        # job asks for.
        for h, tag in ((src, "src"), (tgt, "tgt")):
            for cap in ("monitoring", "lifecycle", "backup"):
                blob, ver = app.state.secretstore.encrypt(json.dumps(
                    {"token_id": f"proxploy@pve!{tag}-{cap}",
                     "token_secret": "s3cret"}).encode())
                db.add(HostCredential(host_id=h.id, kind=f"api_token:{cap}",
                                      encrypted_blob=blob, key_version=ver,
                                      public_meta=f"proxploy@pve!{tag}-{cap}"))
        a = App(host_id=src.id, ctid=ctid, name="immich", slug="immich",
               web_protocol="http", web_path="/")
        db.add(a)
        db.commit()
        return src.id, tgt.id, a.id


def _job(app, app_id, target_host_id):
    with app.state.sessionmaker() as db:
        j = Job(kind="migrate.app", status="running", target_type="app",
               target_id=app_id, params={"app_id": app_id,
                                         "target_host_id": target_host_id})
        db.add(j)
        db.commit()
        return j.id


def _events(app, job_id) -> list[str]:
    with app.state.sessionmaker() as db:
        rows = (db.query(JobEvent).filter_by(job_id=job_id)
               .order_by(JobEvent.seq).all())
        return [e.message for e in rows]


def _app_row(app, app_id):
    with app.state.sessionmaker() as db:
        a = db.get(App, app_id)
        return a.host_id, a.ctid


def _shared_pair(cluster=None):
    a, b = FakePVE(), FakePVE()
    # `pbs-ds` above holds the ARCHIVE and cannot hold a rootfs, which is the
    # whole reason the restore has to name a storage: PVE otherwise falls back
    # to `local` and refuses with "does not support container directories".
    # Modelled per node because that is the read the handler makes.
    for fake, node in ((a, "pve-src"), (b, "pve-tgt")):
        fake.storages_by_node = {node: [
            dict(SHARED_ROW, active=1),
            {"storage": f"rootfs-{node}", "type": "lvmthin",
             "content": "rootdir,images", "active": 1}]}
    if cluster:
        rows = [{"type": "cluster", "name": cluster, "nodes": 2, "quorate": 1},
               {"type": "node", "name": "pve-src"}, {"type": "node", "name": "pve-tgt"}]
        a.cluster_status_rows = list(rows)
        b.cluster_status_rows = list(rows)
    else:
        a.cluster_storage_rows = [dict(SHARED_ROW)]
        b.cluster_storage_rows = [dict(SHARED_ROW)]
    return a, b


# --- shared-storage happy path ------------------------------------------------

def test_shared_storage_migrates_and_repoints_with_measured_downtime(tmp_path):
    async def go():
        fake_src, fake_tgt = _shared_pair()
        fake_src.add_ct(150, node="pve-src", name="immich", status="running")
        fake_tgt.nextid = "500"
        fake_tgt.content_by_storage["pbs-ds"] = [{
            "volid": "pbs-ds:backup/ct/150/2026-08-05T00:00:00Z",
            "content": "backup", "ctime": 1785000000}]
        # Static-snapshot fake: pre-seed the post-restore/post-start view.
        fake_tgt.add_ct(500, node="pve-tgt", name="immich", status="running")

        app = _two_host_app(tmp_path, {SRC_HOSTNAME: fake_src, TGT_HOSTNAME: fake_tgt})
        src_id, tgt_id, app_id = _seed(app)
        job_id = _job(app, app_id, tgt_id)
        ctx = JobContext(app.state.jobs, job_id)

        out = await HANDLERS["migrate.app"](ctx, {"app_id": app_id,
                                                   "target_host_id": tgt_id})

        assert out["strategy"] == "shared_storage"
        assert out["source_ctid"] == 150
        assert out["target_ctid"] == 500
        assert out["volid"] == "pbs-ds:backup/ct/150/2026-08-05T00:00:00Z"
        assert out["downtime_s"] > 0                    # MEASURED, not the preflight estimate
        assert "150" in out["rollback"] and "host-src" in out["rollback"]

        # vzdump on the source, stop mode, into the shared storage
        assert len(fake_src.vzdumps) == 1
        node, params = fake_src.vzdumps[0]
        assert node == "pve-src"
        assert params["vmid"] == 150
        assert params["storage"] == "pbs-ds"
        assert params["mode"] == "stop"

        # restore on the target, restore=1, at the fresh nextid
        assert len(fake_tgt.creates) == 1
        _, tgt_node, restore_params = fake_tgt.creates[0]
        assert tgt_node == "pve-tgt"
        assert restore_params["vmid"] == 500
        assert restore_params["restore"] == 1
        assert restore_params["ostemplate"] == out["volid"]

        # source: stopped, never destroyed. Target: started.
        assert ("lxc", 150, "stop") in fake_src.actions
        assert fake_src.guest_deletes == []
        assert fake_tgt.guest_deletes == []
        assert ("lxc", 500, "start") in fake_tgt.actions

        # identity repointed only after everything above succeeded
        host_id, ctid = _app_row(app, app_id)
        assert host_id == tgt_id
        assert ctid == 500

    asyncio.run(go())


# --- cluster path --------------------------------------------------------------

def test_cluster_strategy_uses_migrate_guest_keeps_ctid_no_vzdump(tmp_path):
    async def go():
        fake_src, fake_tgt = _shared_pair(cluster="prod")
        fake_src.add_ct(150, node="pve-src", name="immich", status="running")
        # Static-snapshot fake: the migrate task moved CT 150 to pve-tgt.
        fake_tgt.add_ct(150, node="pve-tgt", name="immich", status="running")

        app = _two_host_app(tmp_path, {SRC_HOSTNAME: fake_src, TGT_HOSTNAME: fake_tgt})
        src_id, tgt_id, app_id = _seed(app)
        job_id = _job(app, app_id, tgt_id)
        ctx = JobContext(app.state.jobs, job_id)

        out = await HANDLERS["migrate.app"](ctx, {"app_id": app_id,
                                                   "target_host_id": tgt_id})

        assert out["strategy"] == "cluster"
        assert out["source_ctid"] == out["target_ctid"] == 150  # vmid unchanged
        assert out["volid"] is None
        assert out["downtime_s"] > 0

        assert fake_src.vzdumps == []
        assert fake_tgt.creates == []
        assert len(fake_src.migrations) == 1
        kind, node, vmid, params = fake_src.migrations[0]
        assert (kind, node, vmid) == ("lxc", "pve-src", 150)
        assert params["target"] == "pve-tgt"

        assert ("lxc", 150, "stop") in fake_src.actions
        assert ("lxc", 150, "start") in fake_tgt.actions

        host_id, ctid = _app_row(app, app_id)
        assert host_id == tgt_id
        assert ctid == 150

    asyncio.run(go())


# --- per-capability tokens: non-cluster migration needs lifecycle AND -----
# backup on both hosts, not one blended credential (per-capability-tokens-
# plan.md §3 point 2, host-token-privileges-step-one-report.md). Cluster
# migration needs only lifecycle (native PVE migrate, no vzdump/restore).

def _seed_partial(app, *, src_caps, tgt_caps, src_node="pve-src",
                  tgt_node="pve-tgt", ctid=150):
    """Like `_seed`, but only the named capabilities get a token per host --
    for proving the degrade path when one is deliberately left out."""
    with app.state.sessionmaker() as db:
        src = Host(name="host-src", address=SRC_ADDR, node_name=src_node,
                  status="connected", pve_version="8.4.1")
        tgt = Host(name="host-tgt", address=TGT_ADDR, node_name=tgt_node,
                  status="connected", pve_version="8.4.1")
        db.add(src); db.add(tgt); db.commit()
        for h, tag, caps in ((src, "src", src_caps), (tgt, "tgt", tgt_caps)):
            for cap in caps:
                blob, ver = app.state.secretstore.encrypt(json.dumps(
                    {"token_id": f"proxploy@pve!{tag}-{cap}",
                     "token_secret": "s3cret"}).encode())
                db.add(HostCredential(host_id=h.id, kind=f"api_token:{cap}",
                                      encrypted_blob=blob, key_version=ver,
                                      public_meta=f"proxploy@pve!{tag}-{cap}"))
        a = App(host_id=src.id, ctid=ctid, name="immich", slug="immich",
               web_protocol="http", web_path="/")
        db.add(a)
        db.commit()
        return src.id, tgt.id, a.id


def test_non_cluster_migration_needs_both_lifecycle_and_backup_not_monitoring_alone(tmp_path):
    """A host enrolled with only the mandatory monitoring token (the state
    every fresh install and every upgraded pre-per-capability install
    reaches) must fail the migration with a message naming exactly which
    capability is missing, before any PVE call -- not a mid-job 403."""
    async def go():
        fake_src, fake_tgt = _shared_pair()  # no cluster: forces shared_storage
        fake_src.add_ct(150, node="pve-src", name="immich", status="running")

        app = _two_host_app(tmp_path, {SRC_HOSTNAME: fake_src, TGT_HOSTNAME: fake_tgt})
        src_id, tgt_id, app_id = _seed_partial(
            app, src_caps=("monitoring",),
            tgt_caps=("monitoring", "lifecycle", "backup"))
        job_id = _job(app, app_id, tgt_id)
        ctx = JobContext(app.state.jobs, job_id)

        with pytest.raises(JobFailed) as ei:
            await HANDLERS["migrate.app"](ctx, {"app_id": app_id,
                                                "target_host_id": tgt_id})
        msg = str(ei.value)
        assert "host-src" in msg
        assert "lifecycle" in msg
        # No PVE call was ever attempted with the missing credential: the
        # source is not even touched (no stop, no vzdump).
        assert fake_src.actions == []
        assert fake_src.vzdumps == []

    asyncio.run(go())


def test_non_cluster_migration_needs_backup_too_lifecycle_alone_is_not_enough(tmp_path):
    async def go():
        fake_src, fake_tgt = _shared_pair()
        fake_src.add_ct(150, node="pve-src", name="immich", status="running")

        app = _two_host_app(tmp_path, {SRC_HOSTNAME: fake_src, TGT_HOSTNAME: fake_tgt})
        src_id, tgt_id, app_id = _seed_partial(
            app, src_caps=("monitoring", "lifecycle"),
            tgt_caps=("monitoring", "lifecycle", "backup"))
        job_id = _job(app, app_id, tgt_id)
        ctx = JobContext(app.state.jobs, job_id)

        with pytest.raises(JobFailed) as ei:
            await HANDLERS["migrate.app"](ctx, {"app_id": app_id,
                                                "target_host_id": tgt_id})
        assert "host-src" in str(ei.value)
        assert "backup" in str(ei.value)

    asyncio.run(go())


def test_cluster_strategy_needs_only_lifecycle_backup_absent_is_fine(tmp_path):
    """The flip side: cluster-native migration never calls vzdump/restore,
    so a host with no backup token at all must still be able to migrate via
    the cluster strategy. Proves the backup client is resolved lazily, only
    for the strategies that actually use it."""
    async def go():
        fake_src, fake_tgt = _shared_pair(cluster="prod")
        fake_src.add_ct(150, node="pve-src", name="immich", status="running")
        fake_tgt.add_ct(150, node="pve-tgt", name="immich", status="running")

        app = _two_host_app(tmp_path, {SRC_HOSTNAME: fake_src, TGT_HOSTNAME: fake_tgt})
        src_id, tgt_id, app_id = _seed_partial(
            app, src_caps=("monitoring", "lifecycle"),
            tgt_caps=("monitoring", "lifecycle"))
        job_id = _job(app, app_id, tgt_id)
        ctx = JobContext(app.state.jobs, job_id)

        out = await HANDLERS["migrate.app"](ctx, {"app_id": app_id,
                                                   "target_host_id": tgt_id})
        assert out["strategy"] == "cluster"

    asyncio.run(go())


# --- failure ordering: source stays intact, app row stays untouched -----------

def test_restore_failure_leaves_source_intact_and_app_row_untouched(tmp_path):
    async def go():
        fake_src, fake_tgt = _shared_pair()
        fake_src.add_ct(150, node="pve-src", name="immich", status="running")
        fake_tgt.nextid = "500"
        fake_tgt.content_by_storage["pbs-ds"] = [{
            "volid": "pbs-ds:backup/ct/150/2026-08-05T00:00:00Z",
            "content": "backup", "ctime": 1785000000}]
        fake_tgt.task_exit = "restore error"  # every task on this fake fails

        app = _two_host_app(tmp_path, {SRC_HOSTNAME: fake_src, TGT_HOSTNAME: fake_tgt})
        src_id, tgt_id, app_id = _seed(app)
        job_id = _job(app, app_id, tgt_id)
        ctx = JobContext(app.state.jobs, job_id)

        with pytest.raises(JobFailed) as e:
            await HANDLERS["migrate.app"](ctx, {"app_id": app_id,
                                                "target_host_id": tgt_id})
        assert "restore error" in str(e.value)

        # never started on target, never deleted anywhere
        assert not any(a == "start" for _, _, a in fake_tgt.actions)
        assert fake_src.guest_deletes == fake_tgt.guest_deletes == []

        host_id, ctid = _app_row(app, app_id)
        assert (host_id, ctid) == (src_id, 150)          # untouched

        transcript = " ".join(_events(app, job_id)).lower()
        assert "intact" in transcript
        assert "150" in transcript
        assert "host-src" in transcript

    asyncio.run(go())


def test_health_check_timeout_leaves_source_intact_and_app_row_untouched(tmp_path, monkeypatch):
    """Target restore + start both succeed, but the target CT never shows up
    running in /cluster/resources, the one failure mode that happens AFTER
    the target guest was started but BEFORE repoint (doc 11 §2's hardest
    case: neither host has settled yet)."""
    monkeypatch.setattr(migrate_mod, "HEALTH_CHECK_DEADLINE_S", 0.05)
    monkeypatch.setattr(migrate_mod, "HEALTH_CHECK_POLL_S", 0.01)

    async def go():
        fake_src, fake_tgt = _shared_pair()
        fake_src.add_ct(150, node="pve-src", name="immich", status="running")
        fake_tgt.nextid = "500"
        fake_tgt.content_by_storage["pbs-ds"] = [{
            "volid": "pbs-ds:backup/ct/150/2026-08-05T00:00:00Z",
            "content": "backup", "ctime": 1785000000}]
        # Deliberately NOT added to fake_tgt.resources: cluster_resources()
        # never reports CT 500 as running, so the health check times out.

        app = _two_host_app(tmp_path, {SRC_HOSTNAME: fake_src, TGT_HOSTNAME: fake_tgt})
        src_id, tgt_id, app_id = _seed(app)
        job_id = _job(app, app_id, tgt_id)
        ctx = JobContext(app.state.jobs, job_id)

        with pytest.raises(JobFailed) as e:
            await HANDLERS["migrate.app"](ctx, {"app_id": app_id,
                                                "target_host_id": tgt_id})
        assert "did not report running" in str(e.value)
        assert "not repointed" in str(e.value).lower()

        # restore and start DID happen this time: the target guest exists
        assert fake_tgt.creates and fake_tgt.creates[0][2]["vmid"] == 500
        assert ("lxc", 500, "start") in fake_tgt.actions
        assert fake_src.guest_deletes == fake_tgt.guest_deletes == []  # never deleted

        host_id, ctid = _app_row(app, app_id)
        assert (host_id, ctid) == (src_id, 150)          # untouched

        transcript = " ".join(_events(app, job_id)).lower()
        assert "intact" in transcript
        assert "150" in transcript
        assert "500" in transcript                        # both CTs named

    asyncio.run(go())


# --- a stopped source skips the stop call, downtime is still measured ---------

def test_stopped_source_skips_stop_but_downtime_is_still_measured(tmp_path):
    async def go():
        fake_src, fake_tgt = _shared_pair()
        fake_src.add_ct(150, node="pve-src", name="immich", status="stopped")
        fake_tgt.nextid = "500"
        fake_tgt.content_by_storage["pbs-ds"] = [{
            "volid": "pbs-ds:backup/ct/150/2026-08-05T00:00:00Z",
            "content": "backup", "ctime": 1785000000}]
        fake_tgt.add_ct(500, node="pve-tgt", name="immich", status="running")

        app = _two_host_app(tmp_path, {SRC_HOSTNAME: fake_src, TGT_HOSTNAME: fake_tgt})
        src_id, tgt_id, app_id = _seed(app)
        job_id = _job(app, app_id, tgt_id)
        ctx = JobContext(app.state.jobs, job_id)

        out = await HANDLERS["migrate.app"](ctx, {"app_id": app_id,
                                                   "target_host_id": tgt_id})

        assert ("lxc", 150, "stop") not in fake_src.actions  # already stopped
        assert out["downtime_s"] > 0                         # still measured, not skipped

    asyncio.run(go())


# The vzdump+SFTP transfer strategy (Task 16, no shared storage/cluster) is
# implemented and tested in test_migrate_transfer.py: this file previously
# asserted the strategy was refused, which stopped being true once Task 16
# landed.
