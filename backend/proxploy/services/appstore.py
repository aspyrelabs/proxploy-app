"""App Store install job handler (doc 10 Phase 4 DoD: pin + diff + consent +
stream + archive). Mirrors services/lifecycle.py's shape: blocking _resolve
helper in a thread, ctx.log/ctx.progress narration, JobFailed for expected
errors, module-bottom HANDLERS registration.

Root-consent gating lives at the API layer (Task 6), this handler assumes
the caller has already obtained consent and only does the pin + SSH-install
+ archive work.
"""
from __future__ import annotations

import asyncio
import hashlib
import shlex

from proxploy.executor import SSHExecutor
from proxploy.jobs import HANDLERS, JobContext, JobFailed
from proxploy.models import App, AppScript, CatalogEntry, Host, Job, utcnow
from proxploy.services.catalog import pinned_payload_script, raw_url
from proxploy.services.hostclient import client_for_host
from proxploy.services.proxmox import ProxmoxError


SHORT_SHA = 7


def pinned_ref(db, app_id: int) -> str | None:
    """The upstream commit the app's newest saved script came from."""
    latest = (db.query(AppScript).filter_by(app_id=app_id)
              .order_by(AppScript.version.desc()).first())
    return latest.upstream_ref if latest else None


def mark_updates_available(db) -> dict:
    """Recompute `apps.update_available` for every app. Blocking.

    community-scripts publishes no version numbers (doc 01 §3), so the only
    honest signal is "the commit this app was pinned to is behind the commit
    the catalog now holds". The column stores the SHORT sha an update would
    move the app to, which is what doc 06's "Update to vX" renders.

    This is DERIVED state, recomputed wholesale rather than latched: an app
    that updated, or whose catalog entry was rolled back, must stop advertising
    an update. `cleared` counts exactly that.

    Skipped, each for a reason rather than as an oversight:
      - no `catalog_slug`, a hand-rolled CT adopted in Phase 4 has no upstream;
      - no `app_scripts` row, an adopted app has no "from" commit, so there is
        no diff to show and nothing to consent to;
      - catalog entry with no `upstream_sha`, never successfully refreshed.
    """
    shas = {c.slug: c.upstream_sha
            for c in db.query(CatalogEntry.slug, CatalogEntry.upstream_sha).all()}
    marked = cleared = 0
    for a in db.query(App).all():
        want = None
        upstream = shas.get(a.catalog_slug) if a.catalog_slug else None
        if upstream:
            ref = pinned_ref(db, a.id)
            if ref and ref != upstream:
                want = upstream[:SHORT_SHA]
        if want == a.update_available:
            continue
        if want:
            marked += 1
        else:
            cleared += 1
        a.update_available = want
    db.commit()
    return {"marked": marked, "cleared": cleared}


def _resolve(app, catalog_slug: str, host_id: int):
    """Blocking: (catalog row, host, install script). Runs in a thread.

    Deliberately does NOT fetch the SSH private key here: only
    proxploy/executor/ may reference `get_ssh_private_key`
    (scripts/check_executor_isolation.py), the key is instead resolved
    inside `SSHExecutor.run_for_host` at connect time.
    """
    with app.state.sessionmaker() as db:
        entry = db.query(CatalogEntry).filter_by(slug=catalog_slug).one_or_none()
        if entry is None:
            raise JobFailed(f"catalog entry {catalog_slug} not found")
        if not entry.installable:
            raise JobFailed(f"{catalog_slug} is not installable: {entry.unsupported_reason}")
        if not entry.upstream_sha:
            # Without a pinned commit there is nothing to execute that matches
            # what was classified and diffed: never silently fall back to
            # `main`, which is the bug this guard exists to prevent.
            raise JobFailed(f"{catalog_slug} has no pinned upstream commit; "
                            f"refresh the catalog before installing")
        host = db.get(Host, host_id)
        if host is None:
            raise JobFailed(f"host {host_id} not found")
        # Whatever shape upstream ships the payload in: five apps carry it
        # under "addon_script" instead (services/catalog.py).
        install_script = pinned_payload_script(entry) or ""
        return entry, host, install_script


async def run_install(ctx: JobContext, params: dict) -> dict:
    app = ctx.backend.app
    catalog_slug = params["catalog_slug"]
    host_id = int(params["host_id"])
    ctid = params.get("ctid")
    ctid = int(ctid) if ctid is not None else None
    name = params["name"]
    overrides = params.get("overrides") or {}

    entry, host, install_script = await asyncio.to_thread(
        _resolve, app, catalog_slug, host_id)

    ctx.log(f"installing {catalog_slug} on {host.name}"
            + (f" as CT {ctid}" if ctid is not None else
               ", letting the node assign the next free CT id"))
    # Refuse to "install" onto a container that already exists: the catalog
    # script would reconfigure or clobber somebody else's CT and this handler
    # would then file an App row claiming to own it. Nothing to check yet when
    # no ctid was supplied; the post-check below is what proves which id the
    # node picked.
    before = await asyncio.to_thread(_lxc_ids, app, host_id)
    if ctid is not None and ctid in before:
        raise JobFailed(f"CT {ctid} already exists on {host.name}; "
                        f"refusing to install over it")

    # Two corrections a real node forced, both invisible to the fakes (PVE
    # 9.2.6, 2026-08-10):
    #
    # `mode` is lowercase. build.func reads `CHOICE="${mode:-${1:-}}"` and
    # never looks at MODE, which this handler exported for five phases: the
    # menu was therefore always shown, whiptail read EOF from the DEVNULL
    # stdin, and the script took its `|| exit_script` branch and exited 0
    # having installed nothing.
    #
    # TERM must be a real terminal type. A non-PTY ssh session lands on
    # TERM=dumb, where build.func's early `clear` exits 1 and its error trap
    # aborts the run ("in line 1018: exit code 1").
    #
    # `mode` is also `generated`, not `default`. Both branches of build.func's
    # case statement are byte-identical apart from METHOD (which reaches
    # nothing but the telemetry payload) EXCEPT that `default` also runs
    # `defaults_target="$(ensure_global_default_vars_file)"`, and that is what
    # reaches ensure_storage_selection_for_vars_file at build.func:3533. On a
    # host with two or more pools for a content type that function calls
    # select_storage, whiptail cannot run without a TTY, `|| exit_script`
    # fires, and exit_script does `exit 0`: a container is never created and
    # the script reports success. This is the same failure shape as the
    # uppercase-MODE bug documented above, in a second place. Do not revert
    # this to `mode=default`: that silently reintroduces the exit 0.
    env = {"TERM": "xterm", "mode": "generated", "PHS_SILENT": "1"}
    for key, val in overrides.items():
        env[f"var_{key}"] = str(val)

    # Sent on EVERY install, Default included. build.func only auto-picks when
    # exactly one candidate exists for the content type; with two or more it
    # asks, and we can never let it ask. See resolve_storage_pools: it refuses
    # rather than picking when the operator has not chosen.
    container_pool, template_pool = await asyncio.to_thread(
        resolve_storage_pools, app, host_id, overrides)
    env["var_container_storage"] = container_pool
    env["var_template_storage"] = template_pool

    if ctid is not None:
        # Set last so it always wins over an `overrides` entry: the App row
        # below records this ctid as fact, so the container has to actually
        # land there. misc/build.func honours it
        # (`local requested_id="${var_ctid:-$NEXTID}"`).
        #
        # When ctid is None the key must be ABSENT from env, never present
        # and empty: build.func reads it a second time at :1086 with
        # `[[ -n "${var_ctid:-}" ]]`, which branches on non-empty, and only
        # absence is honest about "let the node pick" under both that read
        # and the `:-$NEXTID}` read above. An empty string happens to satisfy
        # the first reader but not the second.
        env["var_ctid"] = str(ctid)

    executor = SSHExecutor(connect_factory=app.state.ssh_connect_factory)

    def on_new_fingerprint(fp: str) -> None:
        # Fresh session, not the `_resolve` one above: that session is
        # already closed by the time the SSH connection is made.
        with app.state.sessionmaker() as db:
            h = db.get(Host, host_id)
            if h is not None:
                h.ssh_host_key_fingerprint = fp
                db.commit()

    # Decline community-scripts telemetry BEFORE the install runs, because
    # build.func's diagnostics_check() draws an interactive whiptail radiolist
    # ("TELEMETRY & DIAGNOSTICS") whenever its config file is absent. That is
    # the same failure shape as select_storage, and it arrived from upstream
    # with no change on our side.
    #
    # There is NO environment variable for this, and adding a DIAGNOSTICS=no
    # to `env` above would be theatre: variables() does a hard
    # `DIAGNOSTICS="no"` assignment, not `${DIAGNOSTICS:-no}`, so anything we
    # export is overwritten before diagnostics_check() is reached, and that
    # function ignores the variable's value anyway when the file is missing.
    # The file is the only control surface upstream offers.
    #
    # Why we are not already broken: the whiptail call ends in
    # `|| result="no"`, so a non-TTY session falls through to "no" and then
    # WRITES the file, which is why only the first install on a node ever saw
    # the dialog. That is a fallback on failure, not a supported
    # non-interactive path, and it is one upstream edit away from becoming a
    # hang. Do not rely on it.
    #
    # Written only when absent, so an operator who opted IN from the node's
    # own shell keeps their choice; this refuses to answer a question on their
    # behalf, it only refuses to be ASKED one in a session with no terminal.
    #
    # A separate SSH call rather than a prefix on the install command below:
    # `env` is inlined as a `KEY=value ...` prefix by executor/ssh.py, and
    # those assignments only apply to the FIRST simple command, so gluing a
    # guard on with `;` would silently strip mode/PHS_SILENT/every var_* from
    # the install itself. Not worth reshaping that command to save a
    # connection.
    telemetry_dir = "/usr/local/community-scripts"
    opt_out = (f"mkdir -p {telemetry_dir} && "
               f"{{ [ -e {telemetry_dir}/diagnostics ] || "
               f"printf 'DIAGNOSTICS=no\n' > {telemetry_dir}/diagnostics; }}")
    try:
        await executor.run_for_host(
            app.state.sessionmaker, app.state.secretstore, host_id, host.address,
            opt_out, pinned_fingerprint=host.ssh_host_key_fingerprint,
            on_new_fingerprint=on_new_fingerprint, timeout_s=60)
    except Exception as e:  # noqa: BLE001
        # Never fails the install: the worst case is the state we were already
        # in before this existed, and an install that works is worth more than
        # a guarantee we could not get.
        ctx.log(f"could not pre-set the telemetry preference: {e}", stream="stderr")

    # Pinned to the exact commit that was ingested, classified and diffed; 
    # not to `main`, which would be a fresh, possibly-different fetch at
    # execution time and would make the app_scripts pin decorative.
    #
    # RESIDUAL LIMITATION (deliberately not solved here): the pinned ct/*.sh
    # itself contains a literal `source <(curl -fsSL .../main/misc/build.func)`
    # line. That line's text is frozen at this commit, but the framework file
    # it names is still fetched live from `main` at execution time, one level
    # down. Full transitive vendoring of the community-scripts framework is a
    # separate, larger piece of work: see docs/notes/phase-4-store.md.
    # The URL is quoted, the `$(...)` around it is not: `bash -c "$(curl ...)"`
    # runs the downloaded script, while quoting the whole substitution would
    # make its output a command *word* instead, which is a different thing.
    # script_path comes from the upstream catalog, so it is not ours to trust
    # as a bare word inside the substitution.
    _url = shlex.quote(raw_url(entry.upstream_sha, entry.script_path))
    command = f"bash -c \"$(curl -fsSL {_url})\""
    try:
        status = await executor.run_for_host(
            app.state.sessionmaker, app.state.secretstore, host_id, host.address, command,
            pinned_fingerprint=host.ssh_host_key_fingerprint,
            on_new_fingerprint=on_new_fingerprint, env=env,
            on_line=lambda stream, line: ctx.log(line, stream=stream),
        )
    except LookupError as e:
        raise JobFailed(str(e)) from e
    if status != 0:
        raise JobFailed(f"install script exited {status}")

    # Exit status 0 is NOT proof the container was built. build.func's own
    # cancel path (`|| exit_script`) exits 0, so a script that showed a menu
    # and gave up looks identical here to one that installed cleanly. Without
    # this check the handler filed an App row for a CT that does not exist,
    # which is exactly what happened on the first real-hardware run.
    after = await asyncio.to_thread(_lxc_ids, app, host_id)
    if ctid is None:
        # No id was pinned, so read back which one build.func picked from the
        # diff of the id sets. This assumes an install creates exactly one
        # container, true of every ct/ script today, and the failure mode
        # when that assumption breaks is loud (JobFailed) rather than a
        # silently wrong id recorded on the App row.
        created = sorted(after - before)
        if len(created) != 1:
            raise JobFailed(
                f"install script exited 0 but {len(created)} containers appeared "
                f"on {host.name}: cannot record which one is this app")
        ctid = created[0]
    elif ctid not in after:
        raise JobFailed(
            f"install script exited 0 but CT {ctid} does not exist on "
            f"{host.name}: nothing was installed")
    ctx.progress(80)

    # host_id is part of the slug, not just catalog_slug+ctid: App.slug has a
    # global UNIQUE constraint, and two different hosts could each install
    # the same catalog app onto the same CTID, which would collide without
    # host_id in the slug.
    slug = f"{catalog_slug}-{host_id}-{ctid}"
    try:
        with app.state.sessionmaker() as db:
            row = App(host_id=host_id, ctid=ctid, name=name, slug=slug,
                      catalog_slug=catalog_slug, category=entry.category,
                      web_protocol="http", web_path="/", adopted=True,
                      update_available=None)
            db.add(row)
            db.flush()
            # A freshly created App row can never legitimately own an
            # app_scripts row yet, so any that exist for this id are stale by
            # definition. SQLite reissues row ids once a table is empty (or
            # once older rows are gone), so a leftover row from a deleted app
            # (an orphan left by a path that bypassed the FK cascade, or from
            # before db.py started enforcing foreign keys) can collide with
            # the id this brand new app was just given. One poisoned row must
            # never be able to brick every future install on
            # ux_app_scripts, so clear it before writing the real one.
            db.query(AppScript).filter_by(app_id=row.id).delete()
            db.add(AppScript(app_id=row.id, version=1, content=install_script,
                             content_sha256=hashlib.sha256(install_script.encode()).hexdigest(),
                             source="upstream", upstream_ref=entry.upstream_sha))
            db.commit()
            app_id, out_slug = row.id, row.slug
    except Exception as e:  # noqa: BLE001
        # The container is REAL and RUNNING on the node at this point; only
        # the bookkeeping failed. A raw DB error can carry the full SQL
        # statement, every bound parameter, and even the install script text
        # (SQLAlchemy's IntegrityError.__str__ includes all three), and none
        # of that may ever reach the user. Say plainly what actually
        # happened instead. Nothing on the node is touched: the container is
        # not removed, and it will show up as a discovered, not-yet-adopted
        # container on the Apps page, where it can be adopted to bring it
        # under management.
        ctx.log(f"could not record the install in the database: {e}", stream="stderr")
        raise JobFailed(
            f"{catalog_slug} was installed on {host.name} as CT {ctid} and is "
            f"running, but Proxploy could not save a record of it. The "
            f"container was not removed. It will appear as a discovered "
            f"container on the Apps page, where you can adopt it to bring it "
            f"under management.") from e

    ctx.progress(100)
    app.state.bus.publish("resource", {"type": "app", "id": app_id, "change": "installed"})
    return {"app_id": app_id, "slug": out_slug}


HANDLERS["app.install"] = run_install


def _resolve_update(app, app_id: int):
    """Blocking: (app row fields, host row fields, catalog entry fields).

    Plain dicts, not ORM objects: the session closes when this returns and the
    caller runs for minutes afterwards. Same reason services/backupjobs.py's
    `_backup_target` returns a dict.
    """
    with app.state.sessionmaker() as db:
        a = db.get(App, app_id)
        if a is None:
            raise JobFailed(f"app {app_id} not found")
        if not a.catalog_slug:
            raise JobFailed(f"{a.name} was adopted, not installed from the catalog "
                            f"; there is no upstream script to update it with")
        entry = db.query(CatalogEntry).filter_by(slug=a.catalog_slug).one_or_none()
        if entry is None:
            raise JobFailed(f"catalog entry {a.catalog_slug} not found; "
                            f"refresh the catalog first")
        if not entry.upstream_sha:
            raise JobFailed(f"{a.catalog_slug} has no pinned upstream commit; "
                            f"refresh the catalog before updating")
        latest = (db.query(AppScript).filter_by(app_id=app_id)
                  .order_by(AppScript.version.desc()).first())
        # api/apps.py::put_app_script writes an "edited" row WITHOUT an
        # upstream_ref, so from_ref would read None below regardless: but
        # that's an accident of that route, not something to depend on here.
        # Checked explicitly: if it's ever backfilled with a ref, silently
        # trusting upstream_ref==None would stop catching this and overwrite
        # the operator's edits.
        if latest is not None and latest.source == "edited":
            # api/apps.py::revert_app_script (Task 6) is the way out: it pins
            # a fresh version sourced "upstream" so this guard clears. Point
            # at it by name rather than making the operator guess.
            raise JobFailed(
                f"{a.name}'s script was edited locally (version {latest.version}); "
                f"updating would replace it with the upstream script and discard "
                f"those edits. POST /api/v1/apps/{app_id}/script/revert will "
                f"restore the upstream script first if you want to proceed with "
                f"the update.")
        from_ref = pinned_ref(db, app_id)
        if from_ref is None:
            raise JobFailed(f"{a.name} has no pinned script; there is no commit "
                            f"to update from")
        if from_ref == entry.upstream_sha:
            raise JobFailed(f"{a.name} is already on upstream commit "
                            f"{from_ref[:SHORT_SHA]}")
        host = db.get(Host, a.host_id)
        if host is None:
            raise JobFailed(f"host {a.host_id} not found")
        return (
            {"id": a.id, "name": a.name, "ctid": a.ctid, "host_id": a.host_id},
            {"id": host.id, "name": host.name, "address": host.address,
             "fingerprint": host.ssh_host_key_fingerprint},
            {"slug": entry.slug, "sha": entry.upstream_sha,
             "script_path": entry.script_path,
             "install_script": pinned_payload_script(entry) or "",
             "from_ref": from_ref},
        )


def _lxc_ids(app, host_id: int) -> set[int]:
    """Blocking: every LXC id currently on the host, straight from PVE.

    One `/cluster/resources` call, the same read the poller makes. Deliberately
    NOT the poller's cached snapshot: this is a safety check, and a cache up to
    30 s stale is exactly what would miss a container created seconds ago.
    """
    with app.state.sessionmaker() as db:
        host = db.get(Host, host_id)
        if host is None:
            raise JobFailed(f"host {host_id} not found")
        try:
            client = client_for_host(app, db, host)
            rows = client.cluster_resources()
        except ProxmoxError as e:
            raise JobFailed(str(e)) from e
    return {int(r["vmid"]) for r in rows if r.get("type") == "lxc"}


def _storage_pools(app, host_id: int, content: str) -> list[str]:
    """Blocking: the pool names on this host's node that carry `content`.

    The API-side equivalent of build.func's `pvesm status -content
    "$content"`, the query whose result becomes an interactive picker when it
    returns more than one row. Deliberately NOT the poller's cached snapshot,
    for the same reason `_lxc_ids` gives: this decides where a container's
    disk lands, and a 30 s stale cache is the wrong input for that.

    Sorted so a caller comparing two candidate lists gets a stable answer, and
    so an error message naming them reads the same every time.
    """
    with app.state.sessionmaker() as db:
        host = db.get(Host, host_id)
        if host is None:
            raise JobFailed(f"host {host_id} not found")
        if not host.node_name:
            raise JobFailed(f"host {host.name} has no node name recorded")
        try:
            client = client_for_host(app, db, host)
            rows = client.storages(host.node_name)
        except ProxmoxError as e:
            raise JobFailed(str(e)) from e
    out = []
    for row in rows:
        if not row.get("enabled", 1) or not row.get("active", 1):
            continue
        if content in str(row.get("content") or "").split(","):
            out.append(str(row["storage"]))
    return sorted(out)


_STORAGE_CLASSES = (
    # (overrides key, Host column, build.func content type)
    ("container_storage", "default_container_storage", "rootdir"),
    ("template_storage", "default_template_storage", "vztmpl"),
)


def resolve_storage_pools(app, host_id: int, supplied: dict) -> tuple[str, str]:
    """The container and template pools for this install, or JobFailed.

    THIS FUNCTION NEVER PICKS. Which pool a container's disk lands on is a
    question, and choosing one on the operator's behalf is exactly the
    interactive-picker problem this design exists to refuse: build.func asks
    that question itself with `pvesm status -content "$content"` whenever it
    finds more than one candidate, and over a non-interactive SSH session that
    picker cannot be answered, so the run hangs. The order tried here is:

      1. what the operator supplied for this install (`supplied`)
      2. what the operator previously chose for this host, if it is still
         valid (Host.default_*_storage)
      3. the sole candidate, if the node has exactly one. This is not a pick:
         there is nothing to choose between.
      4. refuse, naming the candidates so the operator can choose

    Every value taken from (1) or (2), including a remembered one, is
    revalidated against the node's current content list before use. A pool
    name that is stale or was never valid reaches build.func's
    resolve_storage_preselect, whose failure branch returns 238 and then spins
    in a `while true` with an empty body: a real hang that our 1800 s SSH
    timeout would surface as an opaque `TimeoutError: ` with no message.
    Sending an unvalidated name is worse than sending none, so nothing here
    is ever trusted without being checked against `_storage_pools` first.
    """
    resolved = []
    for key, column, content in _STORAGE_CLASSES:
        candidates = _storage_pools(app, host_id, content)
        if not candidates:
            raise JobFailed(f"host has no storage carrying {content!r}")

        # str(...) first: the API validator constrains override KEYS to a
        # shell-identifier pattern but not value types, so a non-string value
        # (e.g. {"container_storage": 5}) reaches here and `.strip()` on a
        # bare int raises AttributeError instead of one of this function's
        # deliberately-written JobFailed messages.
        chosen = str(supplied.get(key) or "").strip() or None
        if chosen:
            if chosen not in candidates:
                raise JobFailed(
                    f"storage {chosen!r} does not carry {content!r} on this host; "
                    f"available: {', '.join(candidates)}")
            resolved.append(chosen)
            continue

        with app.state.sessionmaker() as db:
            host = db.get(Host, host_id)
            remembered = getattr(host, column, None) if host else None
        if remembered:
            # A remembered choice that no longer carries this content is
            # NEVER quietly swapped for another pool: that would move
            # someone's container without telling them. Re-ask instead.
            if remembered in candidates:
                resolved.append(remembered)
                continue
            raise JobFailed(
                f"this host's saved {content!r} storage {remembered!r} is no longer "
                f"available; choose one of: {', '.join(candidates)}")

        if len(candidates) == 1:
            resolved.append(candidates[0])
            continue

        raise JobFailed(
            f"this host has {len(candidates)} pools for {content!r} and none has "
            f"been chosen: {', '.join(candidates)}. Choose one in the install form.")
    return resolved[0], resolved[1]


# Job kinds that build a new guest (Task 5 review B1). JobBackend runs up to
# MAX_CONCURRENT jobs at once, so an id appearing in `after` that wasn't in
# `before` may belong to one of these running concurrently, not to this
# update's script taking build.func's install branch.
_GUEST_CREATING_KINDS = ("app.install", "vm.create", "vm.clone")


def _concurrent_guest_ctids(app, exclude_job_id: int, host_id: int,
                            window_start, window_end) -> set[int]:
    """Blocking: ctids from OTHER guest-creating jobs whose run overlapped
    this job's SSH window, so the stray-CT check doesn't blame; and point an
    operator at destroying, a legitimate container an unrelated job built at
    the same time.

    Only `app.install`'s target id is knowable without guessing, and only when
    the operator supplied one: `params["ctid"]` is passed to the remote script
    as `var_ctid`, so a job that has one built exactly that id, finished or
    not. A CTID-less install (Task 5 made the field optional; the node then
    assigns the next free id) contributes NOTHING here, because the id it
    built is not knowable until it has built it.
    `vm.create`/`vm.clone` are qemu-only (services/guestjobs.py, doc 05) and
    can never produce an LXC row in the first place, so nothing is extracted
    for them, they're queried (per review) alongside app.install for
    completeness, not because either can contribute an id `_lxc_ids` would
    ever see.
    """
    with app.state.sessionmaker() as db:
        rows = (db.query(Job)
                .filter(Job.id != exclude_job_id,
                        Job.kind.in_(_GUEST_CREATING_KINDS),
                        Job.started_at.isnot(None),
                        Job.started_at <= window_end)
                .all())
        ids: set[int] = set()
        for j in rows:
            if j.finished_at is not None and j.finished_at < window_start:
                continue  # finished before this job's window even opened
            if (j.kind == "app.install" and j.params
                    and j.params.get("host_id") == host_id):
                ctid = j.params.get("ctid")
                if ctid is not None:
                    ids.add(int(ctid))
        return ids


async def run_update(ctx: JobContext, params: dict) -> dict:
    """`app.update`, re-run the app's catalog script, pinned to the CURRENT
    upstream commit, over the same SSH path install uses (doc 10 Phase 7:
    "same pin/diff/consent/stream/archive path as install").

    Consent and the upstream diff are the API layer's job (Task 6), exactly as
    install splits them; this handler assumes both were obtained.

    Two guards bracket the SSH run. A community-scripts `ct/*.sh` decides for
    itself whether it is installing or updating, `build.func`'s `start` routes
    to `update_script()` when it finds the container and to `build_container()`
    when it does not, and Proxploy cannot see inside that decision. The
    failure mode when it goes the wrong way is a second container built while
    the `apps` row still points at the first. So the CT must exist BEFORE
    (otherwise the script would certainly install fresh), and no new CT may
    exist AFTER (otherwise it installed anyway, and the job must say so rather
    than report success over a stray container).

    RESIDUAL LIMITATION, stated rather than hidden: whether a given entry's
    update path is non-interactive is a property of that upstream script.
    services/classifier.py classifies INSTALL feasibility only. An update path
    that prompts aborts under `catch_errors`' `set -Ee` and this job fails with
    the full transcript archived, the honest outcome. Classifying update paths
    is separate, larger work; see docs/notes/phase-7-operate.md.

    A SECOND, more severe residual limitation (Task 5 review B4): the post-
    check is an id-SET comparison (before vs. after), and a set diff is blind
    to a script that destroys CT <ctid> and rebuilds it at the SAME id, no id
    is added, none is missing, the diff sees nothing wrong, and this handler
    reports success and advances the pin over what is now a freshly built,
    EMPTY container. This is undetected. It is the one failure mode here with
    real data loss, and nothing in `_lxc_ids`'s id-set approach can catch it;
    detecting it would need something like a creation-time/uptime marker,
    deliberately not attempted here.
    """
    app = ctx.backend.app
    app_id = int(params["app_id"])

    a, host, entry = await asyncio.to_thread(_resolve_update, app, app_id)

    ctx.log(f"updating {a['name']} (CT {a['ctid']}) on {host['name']}: "
            f"{entry['from_ref'][:SHORT_SHA]} -> {entry['sha'][:SHORT_SHA]}")

    window_start = utcnow()
    before = await asyncio.to_thread(_lxc_ids, app, a["host_id"])
    if a["ctid"] not in before:
        raise JobFailed(
            f"CT {a['ctid']} is not present on {host['name']}, refusing to run "
            f"the catalog script, which would install a NEW container rather "
            f"than update this one")
    ctx.progress(10)

    executor = SSHExecutor(connect_factory=app.state.ssh_connect_factory)

    def on_new_fingerprint(fp: str) -> None:
        with app.state.sessionmaker() as db:
            h = db.get(Host, a["host_id"])
            if h is not None:
                h.ssh_host_key_fingerprint = fp
                db.commit()

    # Pinned to the exact commit that was ingested and classified, never to
    # `main`: identical rule and identical raw_url() helper as run_install,
    # and it carries the same one-level-down residual: the pinned script's own
    # `source <(curl ... /main/misc/build.func)` line is frozen text but still
    # fetches live. See docs/notes/phase-4-store.md.
    #
    # Run it INSIDE the container, not on the host. build.func's start() picks
    # install-vs-update by where it is running, nothing else:
    #
    #     if command -v pveversion; then install_script        # on the PVE host
    #     elif [ "$PHS_SILENT" == 1 ]; then update_script      # in the CT
    #
    # `pveversion` exists on the host, so running this over plain host SSH took
    # the install branch every time and built a SECOND container instead of
    # updating this one. Verified on PVE 9.2.6, 2026-08-10: host-side produced
    # a stray CT 100 with a duplicate AdGuard; `pct exec` into the CT reached
    # the real update path and created nothing. No env var changes that choice.
    #
    # The env goes INSIDE the pct exec: the executor's own `env=` is a prefix
    # on the outer host command and does not cross into the container.
    inner = (f"curl -fsSL {raw_url(entry['sha'], entry['script_path'])} "
             f"-o /tmp/proxploy-update.sh && "
             f"TERM=xterm PHS_SILENT=1 bash /tmp/proxploy-update.sh; "
             f"rc=$?; rm -f /tmp/proxploy-update.sh; exit $rc")
    command = f"pct exec {int(a['ctid'])} -- bash -c {shlex.quote(inner)}"
    env: dict[str, str] = {}
    try:
        status = await executor.run_for_host(
            app.state.sessionmaker, app.state.secretstore, a["host_id"],
            host["address"], command,
            pinned_fingerprint=host["fingerprint"],
            on_new_fingerprint=on_new_fingerprint, env=env,
            on_line=lambda stream, line: ctx.log(line, stream=stream),
        )
    except LookupError as e:
        raise JobFailed(str(e)) from e
    if status != 0:
        raise JobFailed(f"update script exited {status}")
    ctx.progress(80)

    after = await asyncio.to_thread(_lxc_ids, app, a["host_id"])
    window_end = utcnow()
    strays = set(after - before)
    if strays:
        concurrent = await asyncio.to_thread(
            _concurrent_guest_ctids, app, ctx.job_id, a["host_id"],
            window_start, window_end)
        strays -= concurrent
    if strays:
        names = ", ".join(f"CT {s}" for s in sorted(strays))
        # Never an imperative "remove it" (Task 5 review B1): this is a
        # whole-cluster snapshot diff and JobBackend runs jobs concurrently,
        # so a stray id here is not proof this update's script built it: it
        # could just as well be an unrelated job that landed in the same
        # window. B2: also tell the truth about retrying: the pin and
        # update_available are both left untouched below, and a plain retry
        # hits the same install branch again.
        raise JobFailed(
            f"{names} appeared on {host['name']} during this update of "
            f"{a['name']} (CT {a['ctid']}) that {'was' if len(strays) == 1 else 'were'} "
            f"not there before. {names} may have been created by this update's "
            f"script taking the catalog's install branch, or by something else "
            f"running on this host at the same time, verify which before "
            f"removing anything. This update was NOT recorded as applied, an "
            f"update is still shown as available, and simply retrying will "
            f"likely hit the same install branch again and create yet another "
            f"container, so resolve {names} first")
    if a["ctid"] not in after:
        raise JobFailed(f"CT {a['ctid']} disappeared during the update")

    # The pin advances only now, on a run that provably updated this container.
    def _record() -> int:
        with app.state.sessionmaker() as db:
            row = db.get(App, app_id)
            latest = (db.query(AppScript).filter_by(app_id=app_id)
                      .order_by(AppScript.version.desc()).first())
            version = (latest.version + 1) if latest else 1
            content = entry["install_script"]
            db.add(AppScript(app_id=app_id, version=version, content=content,
                             content_sha256=hashlib.sha256(
                                 content.encode()).hexdigest(),
                             source="upstream", upstream_ref=entry["sha"]))
            if row is not None:
                row.update_available = None
            db.commit()
            return version

    version = await asyncio.to_thread(_record)
    ctx.progress(100)
    app.state.bus.publish("resource", {"type": "app", "id": app_id,
                                       "change": "updated"})
    return {"app_id": app_id, "from_ref": entry["from_ref"], "to_ref": entry["sha"],
            "script_version": version}


HANDLERS["app.update"] = run_update
