# Backup verification and test restore — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a Proxploy operator prove a vzdump archive is good — by reading it (`vma verify` / a full tar read) or by restoring it into a throwaway id — on setups with no Proxmox Backup Server.

**Architecture:** Two new job kinds beside the existing five in `services/backupjobs.py`. `backup.verify` runs one SSH command as root on the node, because neither `pvesm path` nor `vma verify` has an HTTP endpoint. `backup.test_restore` uses the PVE HTTP API the real restore path already uses, then destroys what it made. Both write their verdict into the existing `backups.verify_state` column plus a new `checked_at`, and both are refused on archives that live on a PBS datastore, which verifies itself.

**Tech Stack:** FastAPI + SQLAlchemy + Alembic (backend), asyncssh via `proxploy/executor/ssh.py`, proxmoxer via `services/proxmox.py`, React + TanStack Query + vitest (frontend), pytest.

**Spec:** `docs/superpowers/specs/2026-08-24-backup-verification-design.md`

## Global Constraints

- **No new entitlement key.** Both actions ship ungated. Routes carry their normal `authorize()` dependency and nothing else.
- **No em dashes and no jargon in user-facing strings.** A message says what actually happened.
- **A failed check is a successful job.** `vma verify` exiting non-zero means the check ran and the archive is bad: the job SUCCEEDS and the archive is marked `failed`. A job fails only when the check could not run at all.
- **The scratch guest is always destroyed**, on the success path and the failure path. A destroy that itself fails makes the job fail, naming the vmid and node.
- **PBS archives are refused** at the route with 409, per archive, by the datastore's type.
- **Test with what exists:** `tests/fakes/ssh.py::FakeSSHConnection` + `make_fake_connect_factory` for SSH, `tests/fakes/pve.py::FakePVE` for the API, `tests/support.py::make_job_app` / `make_app` for the app.
- **Calling a job handler directly in a test** takes `JobContext(JobBackend(app), job_id=1)`, with `JobBackend` imported from `proxploy.jobs`. NOT `JobContext(app.state.jobs, ...)`: `make_job_app` leaves `state.jobs` as None and the handler dereferences `ctx.backend.app`. `tests/test_appstore_install.py` and `tests/test_backup_verify.py` both show the real idiom; copy it.
- **The plan's "Expected: FAIL with ..." lines have been wrong every time so far.** They mean "this test must fail before you implement", not an exact string to match. Do not chase the wording.
- **Commit after every task.** Backend tests: `cd backend && .venv/bin/python -m pytest <file> -q`. Frontend: `cd frontend && npx vitest run <file>` and `npx tsc --noEmit`.

---

### Task 1: `checked_at` column, and stop sync clobbering the verdict

`sync_host_backups` writes `verify_state` on every sweep, using `"none"` when upstream reports nothing. Our verdict would be erased within fifteen minutes. This task makes the column safe to write to.

**Files:**
- Create: `backend/proxploy/migrations/versions/<rev>_backup_checked_at.py`
- Modify: `backend/proxploy/models/__init__.py:750` (the `Backup` model)
- Modify: `backend/proxploy/services/backupjobs.py` (inside `sync_host_backups`, the per-item loop)
- Modify: `backend/proxploy/api/backups.py` (`_backup_out`)
- Test: `backend/tests/test_backups_sync.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Backup.checked_at: datetime | None`; `GET /backups` rows gain `"checked_at": str | None`.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_backups_sync.py`:

```python
def test_sync_leaves_our_verdict_alone_when_upstream_reports_no_verification(tmp_path):
    """A non-PBS store reports no `verification` at all, and writing "none"
    over our own check erased it on the next sweep, fifteen minutes later."""
    from proxploy.services.backupjobs import sync_host_backups
    from tests.support import make_job_app

    async def run():
        app = make_job_app(tmp_path, fake=_fake_with_backups())
        hid = _seed_host(app)
        sync_host_backups(app, hid)
        with app.state.sessionmaker() as db:
            row = db.query(Backup).filter_by(volid=VOLID_VM).one()
            row.verify_state, row.checked_at = "ok", utcnow()
            db.commit()
        sync_host_backups(app, hid)
        with app.state.sessionmaker() as db:
            row = db.query(Backup).filter_by(volid=VOLID_VM).one()
            assert row.verify_state == "ok"
            assert row.checked_at is not None

    asyncio.run(run())


def test_sync_still_takes_the_verdict_pbs_reports(tmp_path):
    """Where PBS does speak, PBS is authoritative and overwrites ours."""
    from proxploy.services.backupjobs import sync_host_backups
    from tests.support import make_job_app

    async def run():
        app = make_job_app(tmp_path, fake=_fake_with_backups())
        hid = _seed_host(app)
        sync_host_backups(app, hid)          # fixture reports ok / failed
        with app.state.sessionmaker() as db:
            db.query(Backup).filter_by(volid=VOLID_CT).one().verify_state = "failed"
            db.commit()
        sync_host_backups(app, hid)
        with app.state.sessionmaker() as db:
            assert db.query(Backup).filter_by(volid=VOLID_CT).one().verify_state == "ok"

    asyncio.run(run())
```

Add `utcnow` to that file's model import line:

```python
from proxploy.models import App, Backup, Host, HostCredential, Job, Vm, utcnow
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_backups_sync.py -q -k "verdict"`
Expected: FAIL — `AttributeError: 'Backup' object has no attribute 'checked_at'`.

- [ ] **Step 3: Add the column to the model**

In `backend/proxploy/models/__init__.py`, directly after the `verify_state` line in `class Backup`:

```python
    verify_state: Mapped[str | None] = mapped_column(Text)
    # When PROXPLOY last checked this archive itself (services/backupjobs.py's
    # backup.verify / backup.test_restore). `verify_state` holds the verdict
    # whoever produced it: PBS writes it through the sync when PBS is the
    # datastore, we write it when nothing else will. NULL means nobody has.
    checked_at: Mapped[datetime | None] = mapped_column(DateTime)
```

- [ ] **Step 4: Write the migration**

Run `cd backend && .venv/bin/python -m alembic heads` to get the current head, then create `backend/proxploy/migrations/versions/<newrev>_backup_checked_at.py` with `down_revision` set to that head:

```python
"""when proxploy last checked a backup archive

Revision ID: <newrev>
Revises: <current head>
Create Date: 2026-08-24

`backups.verify_state` holds the verdict and is reused rather than doubled:
Proxmox Backup Server writes it through the sync where PBS is the datastore,
and services/backupjobs.py's own checks write it where nothing else would. What
the column cannot carry is WHEN we looked, which the Backups page shows and the
30-day card windows on, so it gets its own stamp beside it.

Nullable with no backfill: NULL means "Proxploy has never checked this one",
which is true of every existing row.
"""
from alembic import op
import sqlalchemy as sa

revision = "<newrev>"
down_revision = "<current head>"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("backups") as batch:
        batch.add_column(sa.Column("checked_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("backups") as batch:
        batch.drop_column("checked_at")
```

- [ ] **Step 5: Stop the clobber**

In `backend/proxploy/services/backupjobs.py::sync_host_backups`, replace the `verify_state` assignment in the per-item loop:

```python
            b.verify_state = (item.get("verification") or {}).get("state") or "none"
```

with:

```python
            # Only when upstream actually reports one. A non-PBS store carries
            # no `verification` at all, and writing "none" there erased the
            # verdict services/backupjobs.py's own check had just written, on
            # the next sweep. PBS still wins wherever PBS speaks.
            upstream = (item.get("verification") or {}).get("state")
            if upstream:
                b.verify_state = upstream
            elif b.verify_state is None:
                b.verify_state = "none"
```

- [ ] **Step 6: Expose it on the API row**

In `backend/proxploy/api/backups.py::_backup_out`, add to the returned dict, next to `"verify_state"`:

```python
        "checked_at": to_iso(b.checked_at),
```

- [ ] **Step 7: Run the tests**

Run: `cd backend && .venv/bin/python -m pytest tests/test_backups_sync.py tests/test_backups_api.py -q`
Expected: PASS, including the two new cases.

- [ ] **Step 8: Commit**

```bash
git add backend/proxploy/models/__init__.py backend/proxploy/migrations/versions backend/proxploy/services/backupjobs.py backend/proxploy/api/backups.py backend/tests/test_backups_sync.py
git commit -m "feat(backups): record when we last checked an archive, and stop sync erasing it"
```

---

### Task 2: the `backup.verify` job handler

**Files:**
- Modify: `backend/proxploy/services/backupjobs.py` (new handler + registration)
- Test: `backend/tests/test_backup_verify.py` (create)

**Interfaces:**
- Consumes: `Backup.checked_at` from Task 1.
- Produces: `async def verify_backup(ctx: JobContext, params: dict) -> dict`, registered as `HANDLERS["backup.verify"]`. Params: `{"backup_id": int}`. Returns `{"volid": str, "verdict": "ok"|"failed", "exit_status": int}`. Also produces the module-level `_verify_command(volid: str, guest_type: str | None) -> str`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_backup_verify.py`:

```python
"""backup.verify: read an archive back and say whether it is intact.

Neither `pvesm path` nor `vma verify` is on the PVE HTTP API, so this is the
one backup path that runs over SSH.
"""
import asyncio
import json

from proxploy.models import Backup, Host, HostCredential, Job

VOLID_VM = "nfs-bk:backup/vzdump-qemu-201-2026_07_30-03_00_00.vma.zst"
VOLID_CT = "nfs-bk:backup/vzdump-lxc-150-2026_07_30-02_00_00.tar.zst"


def _seed(app, volid=VOLID_VM, guest_type="vm"):
    with app.state.sessionmaker() as db:
        host = Host(name="host-01", address="https://10.0.0.7:8006", node_name="pve1",
                    status="connected", ssh_host_key_fingerprint="SHA256:abc")
        db.add(host)
        db.commit()
        blob, ver = app.state.secretstore.encrypt(json.dumps(
            {"token_id": "proxploy@pve!bk", "token_secret": "s"}).encode())
        db.add(HostCredential(host_id=host.id, kind="api_token:backup",
                              encrypted_blob=blob, key_version=ver))
        db.add(HostCredential(host_id=host.id, kind="ssh_key",
                              encrypted_blob=blob, key_version=ver))
        b = Backup(host_id=host.id, volid=volid, storage="nfs-bk",
                   guest_type=guest_type, guest_vmid=201, size_bytes=1024)
        db.add(b)
        db.add(Job(id=1, kind="backup.verify", status="running"))
        db.commit()
        return host.id, b.id


def test_the_vm_command_resolves_the_path_and_pipes_into_vma_verify():
    from proxploy.services.backupjobs import _verify_command

    cmd = _verify_command(VOLID_VM, "vm")
    assert "pvesm path" in cmd and VOLID_VM in cmd
    assert "vma verify -v -" in cmd
    # Without pipefail a truncated archive exits 0 through the decompressor.
    assert "set -o pipefail" in cmd


def test_the_container_command_reads_the_whole_tar_instead():
    from proxploy.services.backupjobs import _verify_command

    cmd = _verify_command(VOLID_CT, "ct")
    assert "tar -tf -" in cmd
    assert "vma verify" not in cmd


def test_a_clean_verify_marks_the_archive_ok(tmp_path):
    from proxploy.jobs import JobContext
    from proxploy.services.backupjobs import verify_backup
    from tests.fakes.ssh import FakeSSHConnection, make_fake_connect_factory
    from tests.support import make_job_app

    async def run():
        ssh = FakeSSHConnection(host_key_fingerprint="SHA256:abc",
                                stdout_lines=["CFG: size: 462 name: qemu-server.conf",
                                              "verify done"],
                                stderr_lines=[], exit_status=0)
        app = make_job_app(tmp_path, ssh_factory=make_fake_connect_factory(ssh))
        _, bid = _seed(app)
        out = await verify_backup(JobContext(JobBackend(app), job_id=1), {"backup_id": bid})
        assert out["verdict"] == "ok"
        with app.state.sessionmaker() as db:
            row = db.get(Backup, bid)
            assert row.verify_state == "ok" and row.checked_at is not None

    asyncio.run(run())


def test_a_corrupt_archive_is_a_finished_job_with_a_failed_archive(tmp_path):
    """The check RAN. Failing the job here would report a broken checker."""
    from proxploy.jobs import JobContext
    from proxploy.services.backupjobs import verify_backup
    from tests.fakes.ssh import FakeSSHConnection, make_fake_connect_factory
    from tests.support import make_job_app

    async def run():
        ssh = FakeSSHConnection(host_key_fingerprint="SHA256:abc", stdout_lines=[],
                                stderr_lines=["vma: verify failed - wrong magic"],
                                exit_status=1)
        app = make_job_app(tmp_path, ssh_factory=make_fake_connect_factory(ssh))
        _, bid = _seed(app)
        out = await verify_backup(JobContext(JobBackend(app), job_id=1), {"backup_id": bid})
        assert out["verdict"] == "failed"
        with app.state.sessionmaker() as db:
            assert db.get(Backup, bid).verify_state == "failed"

    asyncio.run(run())


def test_an_unresolvable_path_fails_the_job_and_marks_nothing(tmp_path):
    """Exit 90 is the command's own "pvesm path said nothing" signal: the check
    could not run, which is not the same as an archive that failed it."""
    from proxploy.jobs import JobContext, JobFailed
    from proxploy.services.backupjobs import verify_backup
    from tests.fakes.ssh import FakeSSHConnection, make_fake_connect_factory
    from tests.support import make_job_app

    async def run():
        ssh = FakeSSHConnection(host_key_fingerprint="SHA256:abc", stdout_lines=[],
                                stderr_lines=["pvesm path returned nothing"],
                                exit_status=90)
        app = make_job_app(tmp_path, ssh_factory=make_fake_connect_factory(ssh))
        _, bid = _seed(app)
        try:
            await verify_backup(JobContext(JobBackend(app), job_id=1), {"backup_id": bid})
            raise AssertionError("expected JobFailed")
        except JobFailed as e:
            assert "could not be read" in str(e)
        with app.state.sessionmaker() as db:
            assert db.get(Backup, bid).verify_state is None

    asyncio.run(run())
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_backup_verify.py -q`
Expected: FAIL — `ImportError: cannot import name '_verify_command'`.

- [ ] **Step 3: Write the command builder**

In `backend/proxploy/services/backupjobs.py`, above `run_backup`:

```python
def _verify_command(volid: str, guest_type: str | None) -> str:
    """One shell command: resolve the archive's path, then read it back.

    One command rather than an SSH round trip per step, because the path is
    only useful to the reader that follows it, and because a single exit status
    is what the caller has to judge.

    `pvesm path`, not `/mnt/pve/<store>/dump/...`: the mount point belongs to
    the storage plugin, and a guessed path breaks on the first non-default one.

    `set -o pipefail` is load bearing. Without it the pipeline's status is the
    verifier's alone, and a truncated archive that makes `zstdcat` die still
    reports whatever `vma verify` said about the bytes it did get.

    Exit 90 is reserved for "the path could not be resolved", which is a broken
    check rather than a bad archive; the caller tells those two apart.
    """
    reader = ("vma verify -v -" if guest_type == "vm" else "tar -tf - >/dev/null")
    script = (
        "set -o pipefail; "
        f"P=\"$(pvesm path {shlex.quote(volid)})\"; "
        "test -n \"$P\" || { echo 'pvesm path returned nothing' >&2; exit 90; }; "
        "test -r \"$P\" || { echo \"cannot read $P\" >&2; exit 90; }; "
        "case \"$P\" in "
        "*.zst) D=zstdcat;; *.lzo) D='lzop -dc';; *.gz) D=zcat;; *) D=cat;; esac; "
        f"$D \"$P\" | {reader}"
    )
    return f"bash -c {shlex.quote(script)}"
```

Add `import shlex` to the module's imports, after `import re`.

- [ ] **Step 4: Write the handler**

Below `_verify_command` in the same file:

```python
async def verify_backup(ctx: JobContext, params: dict) -> dict:
    """`backup.verify`: read one archive back and record whether it is intact.

    The only backup path that runs over SSH. Neither `pvesm path` nor
    `vma verify` exists on the PVE HTTP API, and a check that cannot be run is
    worse than a check that has to borrow the installer's transport.
    """
    app = ctx.backend.app
    backup_id = int(params["backup_id"])
    with app.state.sessionmaker() as db:
        row = db.get(Backup, backup_id)
        if row is None:
            raise JobFailed(f"backup {backup_id} is no longer in the list")
        host = db.get(Host, row.host_id)
        if host is None:
            raise JobFailed("the host this archive belongs to is gone")
        volid, guest_type, storage = row.volid, row.guest_type, row.storage
        host_id, address, host_name = host.id, host.address, host.name
        fingerprint = host.ssh_host_key_fingerprint
        label = row.guest_name or volid

    executor = SSHExecutor(connect_factory=app.state.ssh_connect_factory)

    def on_new_fingerprint(fp: str) -> None:
        with app.state.sessionmaker() as db:
            h = db.get(Host, host_id)
            if h is not None:
                h.ssh_host_key_fingerprint = fp
                db.commit()

    ctx.log(f"reading {volid} back off {storage} to check it")
    ctx.progress(5)
    try:
        status = await executor.run_for_host(
            app.state.sessionmaker, app.state.secretstore, host_id, address,
            _verify_command(volid, guest_type),
            pinned_fingerprint=fingerprint, on_new_fingerprint=on_new_fingerprint,
            on_line=lambda stream, line: ctx.log(line, stream=stream),
            timeout_s=app.state.settings.pve_task_timeout_s)
    except LookupError as e:
        # executor/keys.py raises this when the host carries no ssh_key.
        raise JobFailed(
            f"checking a backup needs SSH access to {host_name}, which is not "
            f"set up: {e}") from e
    if status == 90:
        raise JobFailed(f"{volid} could not be read on the node, so it was not "
                        f"checked. Its storage may be offline.")
    verdict = "ok" if status == 0 else "failed"
    with app.state.sessionmaker() as db:
        row = db.get(Backup, backup_id)
        if row is not None:
            row.verify_state = verdict
            row.checked_at = utcnow()
            db.commit()
    ctx.progress(100)
    ctx.log(f"{label}: {'archive is intact' if verdict == 'ok' else 'ARCHIVE FAILED THE CHECK'}")
    app.state.bus.publish("resource", {"type": "backup", "change": "list"})
    return {"volid": volid, "verdict": verdict, "exit_status": status}


HANDLERS["backup.verify"] = verify_backup
```

Add the import at the top of the file, beside the other service imports:

```python
from proxploy.executor import SSHExecutor
```

- [ ] **Step 5: Run the tests**

Run: `cd backend && .venv/bin/python -m pytest tests/test_backup_verify.py -q`
Expected: PASS, 5 tests.

- [ ] **Step 6: Commit**

```bash
git add backend/proxploy/services/backupjobs.py backend/tests/test_backup_verify.py
git commit -m "feat(backups): backup.verify reads an archive back over SSH and records the verdict"
```

---

### Task 3: `POST /backups/{id}/verify`

**Files:**
- Modify: `backend/proxploy/api/backups.py`
- Test: `backend/tests/test_backup_verify_routes.py` (create)

**Interfaces:**
- Consumes: `HANDLERS["backup.verify"]` from Task 2.
- Produces: `POST /api/v1/backups/{backup_id}/verify` → 202 `{"job": {...}}`; 409 `{"detail": ...}` when the archive is on a PBS datastore; 404 when the row is gone.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_backup_verify_routes.py`:

```python
"""The Verify action, and the one archive it refuses: PBS verifies its own."""
import json

from proxploy.models import Backup, Host, HostCredential, Job


def _seed(app, storage="nfs-bk"):
    with app.state.sessionmaker() as db:
        host = Host(name="host-01", address="https://10.0.0.7:8006", node_name="pve1",
                    status="connected")
        db.add(host)
        db.commit()
        blob, ver = app.state.secretstore.encrypt(json.dumps(
            {"token_id": "t", "token_secret": "s"}).encode())
        db.add(HostCredential(host_id=host.id, kind="api_token:backup",
                              encrypted_blob=blob, key_version=ver))
        b = Backup(host_id=host.id, volid=f"{storage}:backup/vzdump-qemu-201-x.vma.zst",
                   storage=storage, guest_type="vm", guest_vmid=201)
        db.add(b)
        db.commit()
        return host.id, b.id


def _snapshot(app, host_id, storage="nfs-bk", type_="nfs"):
    from tests.support import seed_snapshot

    seed_snapshot(app, host_id, storage=[{"storage": storage, "node": "pve1",
                                          "type": type_, "content": ["backup"],
                                          "shared": True, "status": "available",
                                          "used_bytes": 1, "total_bytes": 100}])


def test_verify_enqueues_a_job_for_an_archive_on_a_plain_store(tmp_path, csrf_header,
                                                               bootstrap_admin):
    from fastapi.testclient import TestClient
    from tests.support import make_app

    app = make_app(tmp_path)
    c = TestClient(app)
    with c:
        bootstrap_admin(c)
        hid, bid = _seed(app)
        _snapshot(app, hid)
        r = c.post(f"/api/v1/backups/{bid}/verify", headers=csrf_header(c))
        assert r.status_code == 202
        with app.state.sessionmaker() as db:
            job = db.query(Job).filter_by(kind="backup.verify").one()
            assert job.params["backup_id"] == bid


def test_only_one_check_runs_on_a_host_at_a_time(tmp_path, csrf_header,
                                                 bootstrap_admin):
    """A check reads the whole archive off the share. Two at once on one host
    means two full reads competing for the same link."""
    from fastapi.testclient import TestClient
    from tests.support import make_app

    app = make_app(tmp_path)
    c = TestClient(app)
    with c:
        bootstrap_admin(c)
        hid, bid = _seed(app)
        _snapshot(app, hid)
        assert c.post(f"/api/v1/backups/{bid}/verify",
                      headers=csrf_header(c)).status_code == 202
        r = c.post(f"/api/v1/backups/{bid}/verify", headers=csrf_header(c))
        assert r.status_code == 409
        assert "already" in r.json()["detail"]


def test_verify_is_refused_on_a_pbs_archive(tmp_path, csrf_header, bootstrap_admin):
    from fastapi.testclient import TestClient
    from tests.support import make_app

    app = make_app(tmp_path)
    c = TestClient(app)
    with c:
        bootstrap_admin(c)
        hid, bid = _seed(app, storage="pbs-ds")
        _snapshot(app, hid, storage="pbs-ds", type_="pbs")
        r = c.post(f"/api/v1/backups/{bid}/verify", headers=csrf_header(c))
        assert r.status_code == 409
        assert "Proxmox Backup Server" in r.json()["detail"]
        with app.state.sessionmaker() as db:
            assert db.query(Job).filter_by(kind="backup.verify").count() == 0
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_backup_verify_routes.py -q`
Expected: FAIL with 404 — the route does not exist.

- [ ] **Step 3: Write the shared PBS guard**

In `backend/proxploy/api/backups.py`, below `_host_or_404` (or below `_backup_out` if that helper is absent):

```python
def _refuse_on_pbs(request: Request, db, b: Backup) -> None:
    """Proxmox Backup Server verifies its own archives against stored digests,
    on its own schedule. Ours reads the whole thing back over the network and
    knows less, so offering it there would only overwrite a better verdict with
    a worse one. Per archive, not per install: PBS for the important guests and
    an NFS share for the rest is an ordinary layout."""
    host = db.get(Host, b.host_id)
    snap = request.app.state.poller.snapshots.get(b.host_id) if host else None
    for st in (snap.storage if snap else []):
        if st.get("storage") == b.storage and (st.get("type") or "") == "pbs":
            raise HTTPException(409, "Proxmox Backup Server checks this archive "
                                     "itself, on its own schedule.")


def _backup_or_404(db, backup_id: int) -> Backup:
    b = db.get(Backup, backup_id)
    if b is None:
        raise HTTPException(404, "backup not found")
    return b


def _refuse_a_second_check(db, host_id: int) -> None:
    """One check per host at a time.

    A verify reads the entire archive back off the datastore: 40 GB over 1GbE
    saturates the link for six minutes, and two at once on one host halve each
    other while doubling nothing. A test restore additionally writes a whole
    guest. Serialising is the same reasoning `sync_in_flight` already applies
    to the sync sweep, applied at the door instead of in the handler, so the
    caller is told rather than silently queued behind something.
    """
    running = (db.query(Job)
               .filter(Job.kind.in_(("backup.verify", "backup.test_restore")),
                       Job.target_id == host_id,
                       Job.status.in_(("queued", "running")))
               .first())
    if running is not None:
        raise HTTPException(409, "A backup check is already running on this host. "
                                 "Wait for it to finish, it reads the whole "
                                 "archive back.")
```

- [ ] **Step 4: Write the route**

Add to `backend/proxploy/api/backups.py`, after the `/run` route (literal segments before `/{backup_id}` routes is already this file's rule; `/{backup_id}/verify` is fine anywhere after them):

```python
@router.post("/{backup_id}/verify", status_code=202, dependencies=[Depends(_run)])
def verify_backup_route(request: Request, backup_id: int, db=Depends(get_db),
                        user: User = Depends(_run)):
    """Read one archive back and record whether it is intact.

    `_run`, the same permission a backup itself needs: this reads an archive
    and writes a verdict, and anyone allowed to create archives is allowed to
    find out whether they are any good.
    """
    b = _backup_or_404(db, backup_id)
    _refuse_on_pbs(request, b)   # signature as shipped in Task 3: no `db`
    _refuse_a_second_check(db, b.host_id)
    return enqueue_and_audit(request, db, user, kind="backup.verify",
                             target_type="host", target_id=b.host_id,
                             target_name=b.guest_name or b.volid,
                             params={"backup_id": b.id})
```

- [ ] **Step 5: Run the tests**

Run: `cd backend && .venv/bin/python -m pytest tests/test_backup_verify_routes.py tests/test_route_auth_invariant.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/proxploy/api/backups.py backend/tests/test_backup_verify_routes.py
git commit -m "feat(backups): POST /backups/{id}/verify, refused on a PBS archive"
```

---

### Task 4: the `backup.test_restore` job handler

**Files:**
- Modify: `backend/proxploy/services/backupjobs.py`
- Test: `backend/tests/test_backup_test_restore.py` (create)

**Interfaces:**
- Consumes: Task 1's `checked_at`, Task 2's verdict-writing shape.
- Produces: `async def test_restore_backup(ctx: JobContext, params: dict) -> dict`, registered as `HANDLERS["backup.test_restore"]`. Params: `{"backup_id": int, "storage": str | None}`. Returns `{"volid": str, "verdict": "ok", "scratch_vmid": int}`. Also `_scratch_vmid(client, floor: int = 900) -> int`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_backup_test_restore.py`:

```python
"""backup.test_restore: restore into a throwaway id, then destroy it.

The strongest proof available without PBS, and the one that must never leave
anything behind.
"""
import asyncio
import json

from proxploy.models import Backup, Host, HostCredential, Job


def _seed(app, size_bytes=1024):
    with app.state.sessionmaker() as db:
        host = Host(name="host-01", address="https://10.0.0.7:8006", node_name="pve1",
                    status="connected")
        db.add(host)
        db.commit()
        blob, ver = app.state.secretstore.encrypt(json.dumps(
            {"token_id": "t", "token_secret": "s"}).encode())
        for kind in ("api_token:backup", "api_token:lifecycle"):
            db.add(HostCredential(host_id=host.id, kind=kind,
                                  encrypted_blob=blob, key_version=ver))
        b = Backup(host_id=host.id, storage="nfs-bk", guest_type="vm", guest_vmid=201,
                   guest_name="win11", size_bytes=size_bytes,
                   volid="nfs-bk:backup/vzdump-qemu-201-x.vma.zst")
        db.add(b)
        db.add(Job(id=1, kind="backup.test_restore", status="running"))
        db.commit()
        return host.id, b.id


def test_the_scratch_id_starts_at_900_and_skips_what_is_in_use():
    from proxploy.services.backupjobs import _scratch_vmid
    from tests.fakes.pve import FakePVE

    fake = FakePVE(resources=[
        {"type": "qemu", "vmid": 900}, {"type": "lxc", "vmid": 901},
        {"type": "qemu", "vmid": 150},
    ])
    assert _scratch_vmid(fake.client()) == 902


def test_a_passing_test_restore_destroys_the_copy_and_marks_the_archive(tmp_path):
    from proxploy.jobs import JobContext
    from proxploy.services.backupjobs import test_restore_backup
    from tests.fakes.pve import FakePVE
    from tests.support import make_job_app

    async def run():
        fake = FakePVE()
        fake.storages_by_node = {"pve1": [{"storage": "local-lvm", "type": "lvmthin",
                                           "content": "images", "active": 1,
                                           "enabled": 1, "avail": 10 ** 12}]}
        app = make_job_app(tmp_path, fake=fake)
        _, bid = _seed(app)
        out = await test_restore_backup(JobContext(JobBackend(app), job_id=1),
                                        {"backup_id": bid, "storage": "local-lvm"})
        assert out["verdict"] == "ok"
        assert fake.guest_deletes == [("qemu", "pve1", out["scratch_vmid"])]
        with app.state.sessionmaker() as db:
            row = db.get(Backup, bid)
            assert row.verify_state == "ok" and row.checked_at is not None

    asyncio.run(run())


def test_a_failed_restore_still_destroys_the_scratch_guest(tmp_path):
    """The half-built guest is exactly the leftover this must never produce."""
    from proxploy.jobs import JobContext, JobFailed
    from proxploy.services.backupjobs import test_restore_backup
    from tests.fakes.pve import FakePVE
    from tests.support import make_job_app

    async def run():
        fake = FakePVE(task_exitstatus="restore failed: archive is corrupt")
        fake.storages_by_node = {"pve1": [{"storage": "local-lvm", "type": "lvmthin",
                                           "content": "images", "active": 1,
                                           "enabled": 1, "avail": 10 ** 12}]}
        app = make_job_app(tmp_path, fake=fake)
        _, bid = _seed(app)
        try:
            await test_restore_backup(JobContext(JobBackend(app), job_id=1),
                                      {"backup_id": bid, "storage": "local-lvm"})
            raise AssertionError("expected JobFailed")
        except JobFailed:
            pass
        assert len(fake.guest_deletes) == 1, "the scratch guest was left behind"
        with app.state.sessionmaker() as db:
            assert db.get(Backup, bid).verify_state == "failed"

    asyncio.run(run())


def test_it_refuses_before_touching_pve_when_the_store_is_too_small(tmp_path):
    from proxploy.jobs import JobContext, JobFailed
    from proxploy.services.backupjobs import test_restore_backup
    from tests.fakes.pve import FakePVE
    from tests.support import make_job_app

    async def run():
        fake = FakePVE()
        fake.storages_by_node = {"pve1": [{"storage": "local-lvm", "type": "lvmthin",
                                           "content": "images", "active": 1,
                                           "enabled": 1, "avail": 10}]}
        app = make_job_app(tmp_path, fake=fake)
        _, bid = _seed(app, size_bytes=10 ** 9)
        try:
            await test_restore_backup(JobContext(JobBackend(app), job_id=1),
                                      {"backup_id": bid, "storage": "local-lvm"})
            raise AssertionError("expected JobFailed")
        except JobFailed as e:
            assert "free" in str(e)
        assert fake.guest_deletes == []

    asyncio.run(run())
```

If `FakePVE` has no `guest_deletes` list or no `task_exitstatus` knob, add them in this task: `guest_deletes` appended by its `delete` handler as `(kind, node, vmid)`, and `task_exitstatus` returned by `task_status` in place of `"OK"`.

- [ ] **Step 2: Run them and watch them fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_backup_test_restore.py -q`
Expected: FAIL — `cannot import name '_scratch_vmid'`.

- [ ] **Step 3: Write the scratch id picker**

In `backend/proxploy/services/backupjobs.py`:

```python
def _scratch_vmid(client, floor: int = 900) -> int:
    """The lowest free guest id at or above `floor`.

    Not `cluster_nextid()`, which answers from 100 and would hand back an id in
    the range a human reads as "my guests". Ids from 900 up are the convention
    for throwaway work, and a test restore is the definition of throwaway.

    Read fresh from /cluster/resources rather than the poll snapshot: the
    snapshot can be a poll interval old, and this number is about to have a
    guest created on it.
    """
    used = {int(r["vmid"]) for r in client.cluster_resources()
            if r.get("type") in ("qemu", "lxc") and r.get("vmid") is not None}
    vmid = floor
    while vmid in used:
        vmid += 1
    return vmid
```

- [ ] **Step 4: Write the handler**

```python
async def test_restore_backup(ctx: JobContext, params: dict) -> dict:
    """`backup.test_restore`: restore into a throwaway id, then destroy it.

    The strongest proof available without PBS: not "the file reads back" but
    "Proxmox built a guest out of it". The copy is never started, never
    networked, and never kept, so the only lasting effect is the verdict.
    """
    app = ctx.backend.app
    backup_id = int(params["backup_id"])
    with app.state.sessionmaker() as db:
        row = db.get(Backup, backup_id)
        if row is None:
            raise JobFailed(f"backup {backup_id} is no longer in the list")
        volid, host_id = row.volid, row.host_id
        kind = "lxc" if row.guest_type == "ct" else "qemu"
        size = int(row.size_bytes or 0)
        label = row.guest_name or volid

    client, node, host_name = await asyncio.to_thread(_host_target, app, host_id,
                                                      "lifecycle")
    target = params.get("storage")
    if not target:
        want = "rootdir" if kind == "lxc" else "images"
        target = await asyncio.to_thread(storage_for_content, client, node, want)
        if target is None:
            raise JobFailed(f"no storage on {host_name} can hold a restored "
                            f"{'container' if kind == 'lxc' else 'virtual machine'}")

    # Preflight, before anything is created: a test restore needs as much room
    # as the archive, and filling the pool to prove a backup is good is a worse
    # outcome than not knowing.
    free = await asyncio.to_thread(_free_bytes, client, node, target)
    if free is not None and size and free < size:
        raise JobFailed(f"{target} has {fmt_bytes(free)} free and this archive "
                        f"needs {fmt_bytes(size)}. Choose another storage or "
                        f"make room, nothing was changed.")

    vmid = await asyncio.to_thread(_scratch_vmid, client)
    ctx.log(f"restoring {volid} onto {target} as a throwaway {kind} {vmid} on "
            f"{host_name}/{node}, it will be deleted when the check finishes")
    ctx.progress(5)

    call = {"archive": volid, "storage": target} if kind == "qemu" else \
           {"ostemplate": volid, "restore": 1, "storage": target}
    created = False
    try:
        upid = await asyncio.to_thread(client.restore_guest, kind, node, vmid, call)
        created = True
        await await_task(ctx, client, node, upid,
                         timeout_s=app.state.settings.pve_task_timeout_s,
                         start_pct=10, end_pct=90)
        verdict = "ok"
    except JobFailed:
        verdict = "failed"
        raise
    finally:
        if created:
            ctx.log(f"deleting the throwaway {kind} {vmid}")
            try:
                del_upid = await asyncio.to_thread(client.guest_delete, kind, node, vmid)
                await await_task(ctx, client, node, del_upid,
                                 timeout_s=app.state.settings.pve_task_timeout_s,
                                 report_progress=False)
            except Exception as e:  # noqa: BLE001
                # Never swallowed. A guest nobody knows about, holding a disk,
                # is worse than a red job.
                raise JobFailed(
                    f"the test restore finished but its throwaway {kind} {vmid} "
                    f"on {node} could not be deleted: {e}. Delete it by hand.") from e
        with app.state.sessionmaker() as db:
            b = db.get(Backup, backup_id)
            if b is not None:
                b.verify_state = verdict
                b.checked_at = utcnow()
                db.commit()
        app.state.poller.wake(host_id)
        app.state.bus.publish("resource", {"type": "backup", "change": "list"})

    ctx.progress(100)
    ctx.log(f"{label}: restored cleanly and the copy was deleted")
    return {"volid": volid, "verdict": verdict, "scratch_vmid": vmid}


HANDLERS["backup.test_restore"] = test_restore_backup
```

- [ ] **Step 5: Add the two helpers it leans on**

Also in `backend/proxploy/services/backupjobs.py`, if `storage_for_content` is not already imported there, import it from wherever `restore_backup` gets it. Then add:

```python
def _free_bytes(client, node: str, storage: str) -> int | None:
    """Free space on one datastore, or None when PVE does not say. None means
    "unknown", and unknown never blocks: refusing a restore on a number we do
    not have would be worse than trying."""
    for st in client.storages(node):
        if st.get("storage") == storage:
            avail = st.get("avail")
            return int(avail) if avail is not None else None
    return None
```

For `fmt_bytes`, use the module's existing formatter if there is one; otherwise add:

```python
def fmt_bytes(n: int) -> str:
    """Human sizes for a job log line. GiB is the unit an operator reads a
    datastore in."""
    gib = n / (1024 ** 3)
    return f"{gib:.1f} GiB" if gib >= 0.1 else f"{n} bytes"
```

- [ ] **Step 6: Run the tests**

Run: `cd backend && .venv/bin/python -m pytest tests/test_backup_test_restore.py -q`
Expected: PASS, 4 tests.

- [ ] **Step 7: Commit**

```bash
git add backend/proxploy/services/backupjobs.py backend/tests/test_backup_test_restore.py backend/tests/fakes/pve.py
git commit -m "feat(backups): backup.test_restore proves an archive by restoring it, then deletes the copy"
```

---

### Task 5: `POST /backups/{id}/test-restore`

**Files:**
- Modify: `backend/proxploy/api/backups.py`
- Test: `backend/tests/test_backup_verify_routes.py`

**Interfaces:**
- Consumes: `HANDLERS["backup.test_restore"]` (Task 4), `_refuse_on_pbs` and `_backup_or_404` (Task 3).
- Produces: `POST /api/v1/backups/{backup_id}/test-restore` with body `{"storage": str | None}` → 202 `{"job": {...}}`.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_backup_verify_routes.py`:

```python
def test_test_restore_enqueues_with_the_chosen_storage(tmp_path, csrf_header,
                                                       bootstrap_admin):
    from fastapi.testclient import TestClient
    from tests.support import make_app

    app = make_app(tmp_path)
    c = TestClient(app)
    with c:
        bootstrap_admin(c)
        hid, bid = _seed(app)
        _snapshot(app, hid)
        r = c.post(f"/api/v1/backups/{bid}/test-restore",
                   json={"storage": "local-lvm"}, headers=csrf_header(c))
        assert r.status_code == 202
        with app.state.sessionmaker() as db:
            job = db.query(Job).filter_by(kind="backup.test_restore").one()
            assert job.params == {"backup_id": bid, "storage": "local-lvm"}


def test_test_restore_is_refused_on_a_pbs_archive(tmp_path, csrf_header,
                                                  bootstrap_admin):
    from fastapi.testclient import TestClient
    from tests.support import make_app

    app = make_app(tmp_path)
    c = TestClient(app)
    with c:
        bootstrap_admin(c)
        hid, bid = _seed(app, storage="pbs-ds")
        _snapshot(app, hid, storage="pbs-ds", type_="pbs")
        r = c.post(f"/api/v1/backups/{bid}/test-restore", json={},
                   headers=csrf_header(c))
        assert r.status_code == 409
```

- [ ] **Step 2: Run and watch it fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_backup_verify_routes.py -q`
Expected: FAIL with 404 on the two new tests.

- [ ] **Step 3: Write the route**

In `backend/proxploy/api/backups.py`, beside the verify route:

```python
class TestRestoreIn(BaseModel):
    storage: str | None = None


@router.post("/{backup_id}/test-restore", status_code=202,
             dependencies=[Depends(_restore)])
def test_restore_route(request: Request, backup_id: int,
                       body: TestRestoreIn = Body(default=TestRestoreIn()),
                       db=Depends(get_db), user: User = Depends(_restore)):
    """Prove an archive by restoring it into a throwaway id.

    `_restore`, not `_run`: this really does create a guest, even though it
    deletes it again, so it needs the permission that creating one needs.
    """
    b = _backup_or_404(db, backup_id)
    _refuse_on_pbs(request, b)   # signature as shipped in Task 3: no `db`
    _refuse_a_second_check(db, b.host_id)
    return enqueue_and_audit(request, db, user, kind="backup.test_restore",
                             target_type="host", target_id=b.host_id,
                             target_name=b.guest_name or b.volid,
                             params={"backup_id": b.id, "storage": body.storage})
```

- [ ] **Step 4: Run the tests**

Run: `cd backend && .venv/bin/python -m pytest tests/test_backup_verify_routes.py tests/test_route_auth_invariant.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/proxploy/api/backups.py backend/tests/test_backup_verify_routes.py
git commit -m "feat(backups): POST /backups/{id}/test-restore"
```

---

### Task 6: the two row actions on the Backups page

**Files:**
- Modify: `frontend/src/api/backups.ts` (types + two hooks)
- Modify: `frontend/src/routes/backups.tsx` (the Recent backups row)
- Test: `frontend/src/tests/backups.test.tsx`

**Interfaces:**
- Consumes: the two routes from Tasks 3 and 5, `checked_at` from Task 1.
- Produces: `useVerifyBackup()` and `useTestRestore()` from `api/backups.ts`, both `useMutation` returning `{ job: JobRow }`.

- [ ] **Step 1: Write the failing test**

Append to the `describe('BackupsPage', ...)` block in `frontend/src/tests/backups.test.tsx`:

```tsx
  it('verifies one archive from its row, and says PBS owns the PBS one', async () => {
    calls.length = 0
    wrap()
    const rows = await screen.findAllByRole('row')
    const immich = rows.find((r) => within(r).queryByText('Immich'))!
    fireEvent.click(within(immich).getByRole('button', { name: 'Verify' }))
    await waitFor(() => expect(calls.length).toBe(1))
    expect(calls[0].path).toBe('/backups/11/verify')
    expect(calls[0].method).toBe('POST')
  })

  it('offers no check on an archive Proxmox Backup Server already verifies', async () => {
    // pbs-ds is type pbs in the storage fixture, so both actions are disabled
    // with the reason rather than hidden.
    wrap()
    const rows = await screen.findAllByRole('row')
    const immich = rows.find((r) => within(r).queryByText('Immich'))!
    expect(within(immich).getByRole('button', { name: 'Verify' }))
      .toHaveAttribute('title', expect.stringContaining('Proxmox Backup Server'))
  })
```

Note for the implementer: the fixture's archives live on `pbs-ds`, which IS a `pbs` store in the `stores` fixture, so the FIRST test above needs its archive moved to a plain store. Change the two `BACKUPS.backups[*].storage` fixture values to `local` and their volids to `local:backup/...` before writing these tests, and leave one row on `pbs-ds` for the second test by adding a third fixture row:

```tsx
    { id: 13, host_id: 1, host_name: 'host-01', storage: 'pbs-ds',
      volid: 'pbs-ds:backup/vm/999/2026-07-30T04:00:00Z', guest_type: 'vm',
      guest_vmid: 999, guest_name: 'pbs-guest', taken_at: '2026-07-30T04:00:00Z',
      size_bytes: 1024, verify_state: 'ok', notes: null, checked_at: null },
```

and point the second test at the `pbs-guest` row instead of `Immich`.

- [ ] **Step 2: Run and watch it fail**

Run: `cd frontend && npx vitest run src/tests/backups.test.tsx`
Expected: FAIL — no button named Verify.

- [ ] **Step 3: Add the hooks**

In `frontend/src/api/backups.ts`, beside `useRunBackup`:

```ts
/** Read one archive back and record whether it is intact. Settles like every
 *  other job mutation here: ['jobs'] and the activity feed, never ['backups'],
 *  which the handler's own resource delta refreshes once the verdict exists. */
export function useVerifyBackup() {
  const qc = useQueryClient()
  return useMutation<{ job: JobRow }, ApiError, number>({
    mutationFn: (id) => api<{ job: JobRow }>(`/backups/${id}/verify`, { method: 'POST' }),
    onSettled: jobSettled(qc),
  })
}

/** Restore into a throwaway id and delete it again. `storage` is where the
 *  throwaway copy lands; null lets the handler pick one that can hold it. */
export function useTestRestore() {
  const qc = useQueryClient()
  return useMutation<{ job: JobRow }, ApiError, { id: number; storage?: string | null }>({
    mutationFn: (v) => api<{ job: JobRow }>(`/backups/${v.id}/test-restore`, {
      method: 'POST', body: JSON.stringify({ storage: v.storage ?? null }),
    }),
    onSettled: jobSettled(qc),
  })
}
```

And add `checked_at: string | null` to the `BackupRow` type.

- [ ] **Step 4: Wire the row**

In `frontend/src/routes/backups.tsx`, inside `BackupsPage`, above the return:

```tsx
  const verify = useVerifyBackup()
  const testRestore = useTestRestore()
  // Which datastores Proxmox Backup Server owns. An archive on one of those is
  // verified properly, on a schedule, against stored digests; our own check
  // reads the whole thing back over the network and knows less, so it is not
  // offered there.
  const pbsStores = new Set((storage.data ?? [])
    .filter((s) => s.type === 'pbs').map((s) => s.storage))
  const pbsOwned = (b: BackupRow) => b.storage != null && pbsStores.has(b.storage)
```

In the row's actions cell, before the existing Restore button:

```tsx
                    <Button variant="ghost" size="sm" disabled={verify.isPending || pbsOwned(b)}
                            title={pbsOwned(b)
                              ? 'Proxmox Backup Server checks this archive itself'
                              : 'Read the archive back and check it is intact'}
                            onClick={() => verify.mutate(b.id, {
                              onError: () => notify.error('Could not start that check, try again.'),
                            })}>
                      Verify
                    </Button>
                    <Button variant="ghost" size="sm" className="ml-2"
                            disabled={testRestore.isPending || pbsOwned(b)}
                            title={pbsOwned(b)
                              ? 'Proxmox Backup Server checks this archive itself'
                              : 'Restore into a throwaway id, then delete it'}
                            onClick={() => testRestore.mutate({ id: b.id }, {
                              onError: () => notify.error('Could not start that test restore, try again.'),
                            })}>
                      Test restore
                    </Button>
```

Add `useTestRestore, useVerifyBackup` to the existing `../api/backups` import.

- [ ] **Step 5: Run the tests and the typecheck**

Run: `cd frontend && npx tsc --noEmit && npx vitest run src/tests/backups.test.tsx`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api/backups.ts frontend/src/routes/backups.tsx frontend/src/tests/backups.test.tsx
git commit -m "feat(backups): Verify and Test restore on each archive's row"
```

---

### Task 7: check the archive after a backup run

**Files:**
- Modify: `backend/proxploy/api/backups.py` (`RunIn`)
- Modify: `backend/proxploy/services/backupjobs.py` (`run_backup` tail)
- Modify: `frontend/src/api/backups.ts` (`useRunBackup` vars)
- Modify: `frontend/src/routes/backups.tsx` (Run now dialog)
- Modify: `frontend/src/components/ScheduleForm.tsx`
- Test: `backend/tests/test_backup_verify.py`, `frontend/src/tests/backups.test.tsx`, `frontend/src/tests/schedules.test.tsx`

**Interfaces:**
- Consumes: `HANDLERS["backup.verify"]` (Task 2).
- Produces: `backup.run` accepts `params.verify: bool`; when true it enqueues one `backup.verify` per archive it wrote, after its resync.

- [ ] **Step 1: Write the failing backend test**

Append to `backend/tests/test_backup_verify.py`:

```python
def test_a_run_with_verify_set_enqueues_a_check_for_what_it_wrote(tmp_path):
    """A separate job, not an inline check: a backup that succeeded must read
    as succeeded even when the check that follows it finds a bad archive, and
    the two take very different amounts of time."""
    from proxploy.jobs import JobContext
    from proxploy.models import Backup, Job
    from proxploy.services.backupjobs import run_backup
    from tests.fakes.pve import FakePVE
    from tests.support import make_job_app

    async def run():
        fake = FakePVE()
        app = make_job_app(tmp_path, fake=fake)
        hid, bid = _seed(app)
        with app.state.sessionmaker() as db:
            db.add(Job(id=2, kind="backup.run", status="running"))
            db.commit()
        await run_backup(JobContext(app.state.jobs, 2),
                         {"host_id": hid, "vmids": [201], "verify": True})
        with app.state.sessionmaker() as db:
            queued = db.query(Job).filter_by(kind="backup.verify").all()
            assert len(queued) == 1
            assert queued[0].params["backup_id"] == bid

    asyncio.run(run())
```

- [ ] **Step 2: Run and watch it fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_backup_verify.py -q -k enqueues`
Expected: FAIL — no `backup.verify` job is created.

- [ ] **Step 3: Chain it in the handler**

At the end of `run_backup` in `backend/proxploy/services/backupjobs.py`, after `await _resync(ctx, host_id)` and before the return:

```python
    if params.get("verify"):
        # A separate job, deliberately. A backup that wrote its archive
        # succeeded, whatever a later check says about the bytes, and the check
        # can take as long again as the backup did.
        with app.state.sessionmaker() as db:
            fresh = (db.query(Backup)
                     .filter(Backup.host_id == host_id,
                             Backup.guest_vmid.in_(vmids) if vmids else True)
                     .order_by(Backup.taken_at.desc())
                     .limit(len(vmids) or 5).all())
            for b in fresh:
                app.state.jobs.enqueue(db, kind="backup.verify", target_type="host",
                                       target_id=host_id,
                                       params={"backup_id": b.id},
                                       requested_by=None)
            ctx.log(f"queued a check for {len(fresh)} archive(s)")
```

- [ ] **Step 4: Accept the flag on the route**

In `backend/proxploy/api/backups.py`, add to `class RunIn`:

```python
    verify: bool = False
```

and pass it through in `run_backup_route`'s params dict:

```python
                                     "compress": body.compress,
                                     "verify": body.verify})
```

- [ ] **Step 5: Add the checkbox to Run now**

In `frontend/src/api/backups.ts`, add `verify?: boolean` to `useRunBackup`'s vars type and to the posted body:

```ts
          ...(v.verify ? { verify: true } : {}),
```

In `frontend/src/routes/backups.tsx`'s `RunDialog`, add state `const [check, setCheck] = useState(false)` and, below the storage select:

```tsx
            <label className="mt-3 flex items-center gap-2 text-[12.5px] text-text-2">
              <input type="checkbox" checked={check}
                     onChange={(e) => setCheck(e.target.checked)} />
              Check the archive afterwards
            </label>
```

and pass `verify: check` in the `run.mutate` call.

- [ ] **Step 6: Add the same checkbox to the schedule form**

In `frontend/src/components/ScheduleForm.tsx`, add `const [verifyAfter, setVerifyAfter] = useState(false)`, render inside the existing `isBackup && hostId != null` block:

```tsx
          <div className="sm:col-span-2">
            <label className="flex items-center gap-2 text-[12.5px] text-text-2">
              <input type="checkbox" checked={verifyAfter}
                     onChange={(e) => setVerifyAfter(e.target.checked)} />
              Check each archive afterwards
            </label>
          </div>
```

and in the params builder: `if (verifyAfter) params.verify = true`. Read it back for an edit with `savedParams.verify === true` as the initial state.

- [ ] **Step 7: Write the frontend tests**

In `frontend/src/tests/backups.test.tsx`, inside the Run now group:

```tsx
  it('asks for a check afterwards only when the box is ticked', async () => {
    calls.length = 0
    wrap()
    fireEvent.click(await screen.findByRole('button', { name: 'Run now' }))
    fireEvent.click(await screen.findByLabelText('Check the archive afterwards'))
    fireEvent.click(screen.getByRole('button', { name: 'Start backup' }))
    await waitFor(() => expect(calls.length).toBe(1))
    expect(calls[0].body.verify).toBe(true)
  })
```

In `frontend/src/tests/schedules.test.tsx`, inside the backup-targets group:

```tsx
  it('saves the after-backup check on the schedule', async () => {
    posted.length = 0
    hosts = [{ id: 1, name: 'host-01' }]
    wrap(<ScheduleForm jobKind="backup.run" onSaved={() => {}} />)
    fireEvent.change(screen.getByLabelText(/name/i), { target: { value: 'Nightly' } })
    fireEvent.click(await screen.findByLabelText('Check each archive afterwards'))
    fireEvent.click(screen.getByRole('button', { name: /create schedule/i }))
    await waitFor(() => expect(posted.length).toBe(1))
    expect(posted[0].body.params.verify).toBe(true)
  })
```

- [ ] **Step 8: Run everything touched**

Run: `cd backend && .venv/bin/python -m pytest tests/test_backup_verify.py tests/test_backups_api.py -q`
Run: `cd frontend && npx tsc --noEmit && npx vitest run src/tests/backups.test.tsx src/tests/schedules.test.tsx`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add backend/proxploy frontend/src backend/tests frontend/src/tests
git commit -m "feat(backups): optionally check each archive right after the backup writes it"
```

---

### Task 8: the scheduled sweep

**Files:**
- Modify: `backend/proxploy/services/backupjobs.py` (`verify_backup` accepts a sweep form)
- Modify: `frontend/src/api/schedules.ts` (`SCHEDULABLE`)
- Test: `backend/tests/test_backup_verify.py`

**Interfaces:**
- Consumes: `verify_backup` (Task 2).
- Produces: `backup.verify` also accepts `{"host_id": int, "storage": str | None, "max": int}` and walks unchecked archives; `SCHEDULABLE` gains `{ kind: 'backup.verify', label: 'Check backups on a host', needs: 'host' }`.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_backup_verify.py`:

```python
def test_the_sweep_checks_the_oldest_unchecked_archives_up_to_its_cap(tmp_path):
    from proxploy.jobs import JobContext
    from proxploy.models import Backup, utcnow
    from proxploy.services.backupjobs import verify_backup
    from tests.fakes.ssh import FakeSSHConnection, make_fake_connect_factory
    from tests.support import make_job_app

    async def run():
        ssh = FakeSSHConnection(host_key_fingerprint="SHA256:abc", stdout_lines=["ok"],
                                stderr_lines=[], exit_status=0)
        app = make_job_app(tmp_path, ssh_factory=make_fake_connect_factory(ssh))
        hid, _ = _seed(app)
        with app.state.sessionmaker() as db:
            db.add(Backup(host_id=hid, volid="nfs-bk:backup/a.vma.zst", storage="nfs-bk",
                          guest_type="vm", checked_at=utcnow()))       # already checked
            db.add(Backup(host_id=hid, volid="nfs-bk:backup/b.vma.zst", storage="nfs-bk",
                          guest_type="vm"))
            db.commit()
        out = await verify_backup(JobContext(JobBackend(app), job_id=1),
                                  {"host_id": hid, "max": 10})
        assert out["checked"] == 2      # the seeded one plus b, never a
        with app.state.sessionmaker() as db:
            done = db.query(Backup).filter(Backup.checked_at.isnot(None)).count()
            assert done == 3

    asyncio.run(run())
```

- [ ] **Step 2: Run and watch it fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_backup_verify.py -q -k sweep`
Expected: FAIL — `KeyError: 'backup_id'`.

- [ ] **Step 3: Give the handler its sweep form**

At the top of `verify_backup`, before the single-archive path:

```python
    if "backup_id" not in params:
        # Sweep form, which is what a schedule fires. One job, several
        # archives, so the transcript reads as one pass rather than filling the
        # activity feed with a row per file.
        return await _verify_sweep(ctx, params)
```

And add, above `verify_backup`:

```python
async def _verify_sweep(ctx: JobContext, params: dict) -> dict:
    """Check the archives nobody has checked yet, oldest first.

    Capped, because a sweep reads every byte of every archive it takes and a
    year of daily backups is not a thing to start at 3am without a ceiling.
    """
    app = ctx.backend.app
    host_id = int(params["host_id"])
    limit = max(1, min(int(params.get("max") or 20), 200))
    want_storage = params.get("storage")
    with app.state.sessionmaker() as db:
        q = (db.query(Backup.id)
             .filter(Backup.host_id == host_id, Backup.checked_at.is_(None)))
        if want_storage:
            q = q.filter(Backup.storage == want_storage)
        ids = [i for (i,) in q.order_by(Backup.taken_at.asc()).limit(limit)]
    ctx.log(f"{len(ids)} archive(s) have never been checked, checking them now")
    checked = failed = 0
    for i, bid in enumerate(ids):
        out = await verify_backup(ctx, {"backup_id": bid})
        checked += 1
        failed += 1 if out["verdict"] == "failed" else 0
        ctx.progress(int((i + 1) / len(ids) * 100))
    ctx.log(f"checked {checked}, {failed} failed")
    return {"checked": checked, "failed": failed}
```

Note: `verify_backup` calls `ctx.progress(100)` per archive; inside the sweep that is harmless because the sweep re-reports its own figure right after each one.

- [ ] **Step 4: Offer it in the schedule picker**

In `frontend/src/api/schedules.ts`, add to `SCHEDULABLE` after the `backup.run` entry:

```ts
  // Spelled as a job, not as "backup.verify": the Settings list shows this
  // label as the whole description of what the schedule does.
  { kind: 'backup.verify', label: 'Check backups on a host are readable', needs: 'host' },
```

- [ ] **Step 5: Run the tests**

Run: `cd backend && .venv/bin/python -m pytest tests/test_backup_verify.py -q`
Run: `cd frontend && npx vitest run src/tests/schedules.test.tsx`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/proxploy/services/backupjobs.py backend/tests/test_backup_verify.py frontend/src/api/schedules.ts
git commit -m "feat(backups): a schedulable sweep that checks archives nobody has checked"
```

---

### Task 9: job phrases, and the limitations card

**Files:**
- Modify: `frontend/src/lib/activityDisplay.ts` (`JOB_PHRASE`, `GERUND`, `ACTION_LABEL`)
- Modify: `frontend/src/components/BackupLimitsDialog.tsx`
- Test: `frontend/src/tests/backups.test.tsx`

**Interfaces:**
- Consumes: the two job kinds from Tasks 2 and 4.
- Produces: nothing further.

- [ ] **Step 1: Write the failing test**

In `frontend/src/tests/backups.test.tsx`, replace the limitations-card content assertions with:

```tsx
  it('pairs each Proxmox limit with what Proxploy does about it', async () => {
    localStorage.removeItem('proxploy.backups.limits-ack')
    wrap()
    expect(await screen.findByText(/Before you rely on these backups/)).toBeInTheDocument()
    expect(screen.getByText(/limits of Proxmox VE itself, not of Proxploy/)).toBeInTheDocument()
    // The one we answer, and the two we cannot.
    expect(screen.getByText(/Checks them for you/)).toBeInTheDocument()
    expect(screen.getAllByText(/Cannot fix it/).length).toBeGreaterThanOrEqual(2)
    expect(screen.getByText(/Proxmox Backup Server/)).toBeInTheDocument()
  })
```

- [ ] **Step 2: Run and watch it fail**

Run: `cd frontend && npx vitest run src/tests/backups.test.tsx -t "pairs each"`
Expected: FAIL — no "Checks them for you".

- [ ] **Step 3: Add the phrases**

In `frontend/src/lib/activityDisplay.ts`, add to `JOB_PHRASE`:

```ts
  // "Check Finished", not "Check Passed": the job succeeding means the check
  // RAN, and whether the archive passed is the row's own verdict. A toast
  // reading "Verify Failed" over an archive that is merely corrupt would state
  // the opposite of what happened.
  'backup.verify': {
    queued: 'Check Queued',
    running: 'Checking Backup',
    succeeded: 'Check Finished',
    failed: 'Check Could Not Run',
    canceled: 'Check Stopped',
    interrupted: 'Check Interrupted',
  },
  'backup.test_restore': {
    queued: 'Test Restore Queued',
    running: 'Test Restore Started',
    succeeded: 'Test Restore Completed',
    failed: 'Test Restore Failed',
    canceled: 'Test Restore Stopped',
    interrupted: 'Test Restore Interrupted',
  },
```

Add to `GERUND`:

```ts
  'backup.verify': 'checking the backups of',
  'backup.test_restore': 'test restoring',
```

Add to `ACTION_LABEL`, keeping its two-word rule:

```ts
  'backup.test_restore': 'Test Restore',
  'backup.verify': 'Backup Check',
```

- [ ] **Step 4: Restructure the card**

Rewrite the body of `frontend/src/components/BackupLimitsDialog.tsx`'s `LIMITS` constant as pairs and render both halves:

```tsx
/** Each limit, and what Proxploy does about it. A list of four things that are
 *  wrong leaves the reader with a problem and no move; two of these four we
 *  genuinely answer, and saying plainly which two is the point of the card. */
const LIMITS: { limit: string; body: string; answer: string }[] = [
  {
    limit: 'Every backup is a full copy',
    body: 'Proxmox writes the whole guest every time. Ten nightly backups of a '
      + '40 GB machine take ten times the space.',
    answer: 'Cannot fix it, that is how vzdump writes. Proxploy gives you retention '
      + 'rules and a preview that shows exactly what a rule would delete, before it '
      + 'deletes it.',
  },
  {
    limit: 'Nothing checks that a backup is readable',
    body: 'Proxmox VE never reads an archive back after writing it. One can sit in '
      + 'this list looking fine and fail when you need it.',
    answer: 'Checks them for you. Verify reads the whole archive and checks its '
      + 'structure. Test restore goes further: it restores the backup into a spare '
      + 'id, confirms Proxmox finished, then deletes the copy, without ever touching '
      + 'your real machine. Run either from a backup’s row, after every backup, '
      + 'or on a schedule.',
  },
  {
    limit: 'You restore a whole machine, not one file',
    body: 'There is no way to open a backup and pull a single file out of it.',
    answer: 'Cannot fix it. A vzdump archive carries no file index to browse.',
  },
  {
    limit: 'Backups are not encrypted',
    body: 'Anyone who can read the share they sit on can read what is inside them.',
    answer: 'Cannot fix it. Whatever the share and the filesystem give you is what '
      + 'you have.',
  },
]
```

Render each as the limit (semibold), the body (text-3), then the answer on its own line prefixed with a label, e.g.:

```tsx
        {LIMITS.map((l) => (
          <div key={l.limit}>
            <dt className="text-[13px] font-semibold text-text">{l.limit}</dt>
            <dd className="mt-0.5 text-[12.5px] text-text-3">{l.body}</dd>
            <dd className="mt-1 text-[12.5px] text-text-2">
              <span className="text-text-3">Proxploy: </span>{l.answer}
            </dd>
          </div>
        ))}
```

Add one sentence to the closing amber panel: `The checks Proxploy runs are not as thorough as its: PBS verifies every block against a stored digest on its own schedule, instead of reading the whole archive back over the network each time.`

- [ ] **Step 5: Run the tests**

Run: `cd frontend && npx tsc --noEmit && npx vitest run src/tests/backups.test.tsx src/tests/activity-display.test.ts`
Expected: PASS.

- [ ] **Step 6: Full sweep before finishing**

Run: `cd backend && .venv/bin/python -m pytest tests/ -q -m "not pve_integration and not e2e"`
Run: `cd frontend && npx vitest run --no-file-parallelism && npx tsc --noEmit && npx oxlint`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/src
git commit -m "feat(backups): name each check outcome, and tell the card what we do about each limit"
```
