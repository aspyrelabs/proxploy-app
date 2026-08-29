"""App Store install job handler: pin, diff, consent, stream, archive.
Mirrors services/lifecycle.py's shape: blocking _resolve helper in a thread,
ctx.log/ctx.progress narration, JobFailed for expected errors, module-bottom
HANDLERS registration. Root-consent gating lives at the API layer; this
handler assumes consent and only does the pin, SSH install and archive work.
"""
from __future__ import annotations

import asyncio
import hashlib
import shlex
from collections import deque

from proxploy.executor import SSHExecutor
from proxploy.executor.ssh import SSHHostKeyMismatch, SSHUnreachable
from proxploy.jobs import HANDLERS, JobContext, JobFailed, JobUnknown
from proxploy.models import App, AppScript, CatalogEntry, Host, Job, utcnow
from proxploy.services import installanswers
from proxploy.services.catalog import pinned_payload_script, raw_url
from proxploy.services.hostclient import client_for_host
from proxploy.services.proxmox import ProxmoxError
from proxploy.services.webui import TAIL_LINES, url_from_install_log


SHORT_SHA = 7


def pinned_ref(db, app_id: int) -> str | None:
    """The upstream commit the app's newest saved script came from."""
    latest = (db.query(AppScript).filter_by(app_id=app_id)
              .order_by(AppScript.version.desc()).first())
    return latest.upstream_ref if latest else None


def mark_updates_available(db) -> dict:
    """Recompute `apps.update_available` for every app. Blocking.

    community-scripts publishes no version numbers, so the only honest signal
    is "the pinned commit is behind the commit the catalog now holds". The
    column stores the SHORT sha an update would move the app to.

    DERIVED state, recomputed wholesale rather than latched: an app that
    updated, or whose catalog entry was rolled back, must stop advertising an
    update. `cleared` counts exactly that.

    Skipped, each for a reason: no `catalog_slug`, a hand-adopted CT has no
    upstream; no `app_scripts` row, so no "from" commit to diff or consent to;
    a catalog entry with no `upstream_sha`, never successfully refreshed.
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


# Answers the operator gave to prompts the upstream installer never guarded.
#
# BY VARIABLE, NOT BY POSITION. The obvious implementation pipes answers to
# stdin in order, and it silently misfires: of the 70 blocked scripts measured
# on 2026-08-27, 21 have prompts inside an if/case and 8 inside a loop, so a
# branch not taken shifts every later answer onto the wrong question. `docker`,
# the most installed app in the catalog, is one of them. Matching on the
# variable a prompt assigns into is order, branch and loop proof.
#
# Verified on node1 on 2026-08-27: exported bash FUNCTIONS cross `lxc-attach`,
# which is how build.func:5194 runs the installer inside the container. That
# same hop already carries FUNCTIONS_FILE_PATH, which every install script
# sources, so this rides upstream's own mechanism rather than adding one.
#
# PXP_ANSWERED is an explicit allowlist, deliberately not "any variable that
# happens to be set". This shim is in scope for build.func's own `read` calls
# too, and it has to stay inert for every prompt we were not asked about:
# those fall through to `builtin read`, meet the DEVNULL stdin, and behave
# exactly as they did before this existed.
READ_SHIM = (
    'read() { local _a _t="" _c _n _v; '
    'for _a in "$@"; do case "$_a" in -*) ;; *) _t="$_a" ;; esac; done; '
    'if [ -n "$_t" ]; then case " ${PXP_ANSWERED:-} " in *" $_t "*) '
    '_c="PXP_N_$_t"; _n=$(( ${!_c:-0} + 1 )); printf -v "$_c" %s "$_n"; '
    '_v="PXP_A_${_t}_${_n}"; '
    'if [ -n "${!_v+x}" ]; then printf -v "$_t" %s "${!_v}"; fi; '
    'return 0 ;; esac; fi; '
    'builtin read "$@"; }; export -f read; '
)


def apply_answers(ctx: JobContext, env: dict, command: str,
                  plain: dict, secret: dict, prompts: list | None = None) -> str:
    """Put answers in the environment, prefix the shim, return the command.

    `secret` values are hidden from every job sink (JobContext.hide); `plain`
    ones are not, because a version number or a timezone left readable in the
    transcript is what makes a failed install diagnosable.
    """
    answers = {**plain, **secret}
    if not answers:
        return command
    prompts = prompts or []
    names: set[str] = set()
    for key, value in answers.items():
        name, _, index = str(key).rpartition("#")
        if not name or not index.isdigit() or int(index) >= len(prompts):
            continue
        occurrence = installanswers.occurrence_of(prompts, int(index))
        env[f"PXP_A_{name}_{occurrence}"] = str(value)
        names.add(name)
    if not names:
        return command
    env["PXP_ANSWERED"] = " ".join(sorted(names))
    ctx.hide(*[str(v) for v in secret.values()])
    # WRAPPED, not prefixed. executor/ssh.py builds `NAME=value ... <command>`,
    # and a shell FUNCTION DEFINITION cannot follow an environment prefix:
    # `VAR=x read() { ... }` is a syntax error, which is what a real node said
    # on 2026-08-27 ("syntax error near unexpected token `('"). Wrapping keeps
    # a genuine command in that position. The prefix assignments still reach
    # the script, because they are exported into this bash's environment and
    # inherited by the one it starts.
    return f"bash -c {shlex.quote(READ_SHIM + command)}"


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
    # would then file an App row claiming to own it. Nothing to check when no
    # ctid was supplied; the post-check below proves which id the node picked.
    before = await asyncio.to_thread(_lxc_ids, app, host_id)
    if ctid is not None and ctid in before:
        raise JobFailed(f"CT {ctid} already exists on {host.name}; "
                        f"refusing to install over it")

    # Three corrections a real node forced, all invisible to the fakes:
    #
    # `mode` is lowercase. build.func reads `CHOICE="${mode:-${1:-}}"` and
    # never looks at MODE. With MODE the menu was always shown, whiptail read
    # EOF from the DEVNULL stdin, and the script took `|| exit_script` and
    # exited 0 having installed nothing.
    #
    # TERM must be a real terminal type. A non-PTY ssh session lands on
    # TERM=dumb, where build.func's early `clear` exits 1 and its error trap
    # aborts the run.
    #
    # `mode` is `generated`, not `default`. The two branches are identical
    # apart from METHOD EXCEPT that `default` also runs
    # `ensure_global_default_vars_file`, which reaches
    # ensure_storage_selection_for_vars_file at build.func:3533. With two or
    # more pools for a content type that calls select_storage, whiptail cannot
    # run without a TTY, `|| exit_script` fires, and exit_script does `exit 0`:
    # no container, reported as success. Do not revert to `mode=default`.
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
        # below records this ctid as fact. misc/build.func honours it
        # (`local requested_id="${var_ctid:-$NEXTID}"`).
        #
        # When ctid is None the key must be ABSENT, never present and empty:
        # build.func reads it again at :1086 with `[[ -n "${var_ctid:-}" ]]`,
        # which branches on non-empty. An empty string satisfies the first
        # reader but not the second, so only absence is honest.
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

    # Decline community-scripts telemetry BEFORE the install runs:
    # build.func's diagnostics_check() draws an interactive whiptail radiolist
    # whenever its config file is absent, the same failure shape as
    # select_storage.
    #
    # There is NO environment variable for this. variables() does a hard
    # `DIAGNOSTICS="no"` assignment, not `${DIAGNOSTICS:-no}`, so anything we
    # export is overwritten first, and diagnostics_check() ignores the value
    # anyway when the file is missing. The file is upstream's only control
    # surface.
    #
    # Do not rely on the current escape: the whiptail call ends in
    # `|| result="no"`, so a non-TTY session falls through and writes the file
    # itself. That is a fallback on failure, one upstream edit from a hang.
    #
    # Written only when absent, so an operator who opted IN from the node's
    # own shell keeps their choice.
    #
    # A separate SSH call, not a prefix on the install command: `env` is
    # inlined as a `KEY=value ...` prefix by executor/ssh.py and those
    # assignments apply only to the FIRST simple command, so gluing a guard on
    # with `;` would strip mode/PHS_SILENT/every var_* from the install.
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

    # Pinned to the exact commit that was ingested, classified and diffed, not
    # to `main`, which would be a fresh fetch at execution time and would make
    # the app_scripts pin decorative.
    #
    # RESIDUAL LIMITATION: the pinned ct/*.sh still contains a literal
    # `source <(curl -fsSL .../main/misc/build.func)`. That line's text is
    # frozen, but the framework file it names is fetched live from `main` one
    # level down. Vendoring the framework is separate, larger work.
    #
    # The URL is quoted, the `$(...)` around it is not: `bash -c "$(curl ...)"`
    # runs the downloaded script, while quoting the whole substitution would
    # make its output a command *word*. script_path comes from the upstream
    # catalog, so it is not ours to trust as a bare word.
    _url = shlex.quote(raw_url(entry.upstream_sha, entry.script_path))
    command = f"bash -c \"$(curl -fsSL {_url})\""

    # The secret half never travelled in params: it was staged encrypted by
    # the route and params carries only the handle. See services/installanswers.
    answers_handle = params.get("answers_handle")
    with app.state.sessionmaker() as db:
        secret_answers = installanswers.load(db, app.state.secretstore, answers_handle)
    # Defaults underneath, the operator's answers on top: a prompt nobody was
    # asked about still needs a value, or the install meets it and blocks.
    # answerable_without_asking refuses a gate, so no consent question can pick
    # up a default here however it is shaped.
    plain = {**installanswers.defaults_for(entry.prompts),
             **(params.get("answers") or {})}
    command = apply_answers(ctx, env, command, plain, secret_answers,
                            entry.prompts)

    # The script's last words are where it prints the finished URL, so they are
    # kept as they stream rather than read back out of job_events: job_events
    # has no retention policy, so a parse depending on those rows would quietly
    # stop working the day someone adds pruning.
    tail: deque[str] = deque(maxlen=TAIL_LINES)

    def on_line(stream: str, line: str) -> None:
        ctx.log(line, stream=stream)
        if stream == "stdout":
            tail.append(line)

    # Written BEFORE the dispatch, because a checkpoint written after it would
    # be missing in exactly the crash it exists for. `before` is the same id set
    # the post-check below diffs against; recording it is what lets that same
    # question be asked later, by a reconciliation, on a run that never got to
    # its own post-check.
    ctx.checkpoint(dispatched=True, before_ctids=sorted(before), host_id=host_id,
                   ctid=ctid, catalog_slug=catalog_slug, name=name)

    try:
        status = await executor.run_for_host(
            app.state.sessionmaker, app.state.secretstore, host_id, host.address, command,
            pinned_fingerprint=host.ssh_host_key_fingerprint,
            on_new_fingerprint=on_new_fingerprint, env=env,
            on_line=on_line,
        )
    except LookupError as e:
        raise JobFailed(str(e)) from e
    except (SSHUnreachable, SSHHostKeyMismatch) as e:
        # Both are raised from executor/ssh.py's connect block, BEFORE
        # `async with conn`, so the command never reached a shell and there is
        # nothing on the node to reconcile. `failed` is the honest answer and
        # keeps the App Store unblocked.
        raise JobFailed(str(e)) from e
    except Exception as e:  # noqa: BLE001
        # Anything else out of run_for_host happened after create_process, so
        # the script was already running as root on the node. It may have done
        # nothing, part of the work, or all of it, and this process can no
        # longer tell which. Saying "failed" here is what turned one partial
        # install into two containers: the operator reinstalls, the default
        # blank ctid takes the next free id, and the first container is
        # orphaned. A timeout counts too, because proc.terminate() runs on a
        # command that was already executing.
        raise JobUnknown(
            f"the connection to {host.name} was lost while the install script "
            f"was running: {type(e).__name__}: {e}. Proxploy does not know "
            f"whether the container was created and is checking the node.") from e
    if status is None:
        # asyncssh returns exit_status None when the channel closed without
        # delivering one, which is what a dropped connection actually looks
        # like: wait_closed() completes normally and nothing is raised. Found
        # on hardware; the SSH fake raises instead, so every non-hardware test
        # took the except branch above and this path was invisible.
        #
        # No exit status means the script's own verdict never arrived, and it
        # was already running as root when the channel went, so this is the
        # same "may have completed" case as a raised connection error.
        raise JobUnknown(
            f"the connection to {host.name} closed without the install script "
            f"reporting an exit status. Proxploy does not know whether the "
            f"container was created and is checking the node.")
    if status != 0:
        raise JobFailed(f"install script exited {status}")

    # Exit status 0 is NOT proof the container was built. build.func's cancel
    # path (`|| exit_script`) exits 0, so a script that showed a menu and gave
    # up looks identical to one that installed cleanly. Without this check the
    # handler filed an App row for a CT that does not exist.
    after = await asyncio.to_thread(_lxc_ids, app, host_id)
    if ctid is None:
        # No id was pinned, so read back which one build.func picked from the
        # diff of the id sets. This assumes an install creates exactly one
        # container, true of every ct/ script today, and the failure when that
        # breaks is loud rather than a silently wrong id on the App row.
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
                      # No web_protocol: an install does not know whether the
                      # app speaks http or https, and writing "http" here is
                      # what used to send Open at the wrong scheme. Left NULL
                      # so the app is asked (services/webui.py).
                      #
                      # `installed_url` is what the script printed, read only
                      # after exit 0: a failed install can still have printed
                      # a URL for a container that was rolled back. The
                      # catalog's port corroborates it, so a documentation
                      # link near the end cannot win over the real one.
                      installed_url=url_from_install_log(
                          tail, expected_port=entry.port),
                      web_path="/", adopted=True,
                      update_available=None)
            db.add(row)
            db.flush()
            # A freshly created App row can never legitimately own an
            # app_scripts row, so any that exist for this id are stale. SQLite
            # reissues row ids once older rows are gone, so an orphan left by
            # a path that bypassed the FK cascade can collide with the id this
            # brand new app was just given. One poisoned row must never brick
            # every future install on ux_app_scripts, so clear it first.
            db.query(AppScript).filter_by(app_id=row.id).delete()
            db.add(AppScript(app_id=row.id, version=1, content=install_script,
                             content_sha256=hashlib.sha256(install_script.encode()).hexdigest(),
                             source="upstream", upstream_ref=entry.upstream_sha))
            db.commit()
            app_id, out_slug = row.id, row.slug
    except Exception as e:  # noqa: BLE001
        # The container is REAL and RUNNING; only the bookkeeping failed. A raw
        # DB error can carry the full SQL, every bound parameter and the
        # install script text (SQLAlchemy's IntegrityError.__str__ includes all
        # three), and none of that may reach the user. Nothing on the node is
        # touched: the container stays and shows up as a discovered container
        # on the Apps page, where it can be adopted.
        ctx.log(f"could not record the install in the database: {e}", stream="stderr")
        raise JobFailed(
            f"{catalog_slug} was installed on {host.name} as CT {ctid} and is "
            f"running, but Proxploy could not save a record of it. The "
            f"container was not removed. It will appear as a discovered "
            f"container on the Apps page, where you can adopt it to bring it "
            f"under management.") from e

    ctx.progress(100)
    # Everything live about an app, its status, cpu, memory and address, comes
    # from the poller's snapshot of /cluster/resources, and the CT this install
    # just made is not in it yet. Without the wake a brand new app sits at
    # "unknown" for up to a poll interval.
    app.state.poller.wake(host_id)
    app.state.bus.publish("resource", {"type": "app", "id": app_id, "change": "installed"})
    # Bound only now, on a run that provably produced an app. Until this the
    # row is an orphan on a TTL; after it, ON DELETE CASCADE means uninstalling
    # the app takes its secrets with it and nothing has to remember to.
    with app.state.sessionmaker() as db:
        installanswers.bind(db, answers_handle, app_id)
    return {"app_id": app_id, "slug": out_slug}


def _resolve_install_job(app, job_id: int, status: str, *, error: str | None = None,
                         result: dict | None = None) -> None:
    """Move an `unknown` install job to a real answer.

    Writes the row directly because the run it describes is long over: this is
    not a job finishing, it is a later job recording what the node said. Guarded
    on the status still being `unknown` so two reconciles cannot both claim it.
    """
    with app.state.sessionmaker() as db:
        job = db.get(Job, job_id)
        if job is None or job.status != "unknown":
            return
        job.status = status
        if error is not None:
            job.error = error
        if result is not None:
            job.result = {**(job.result or {}), **result}
        db.commit()


def _record_reconciled_install(app, job_id: int, catalog_slug: str, host_id: int,
                               ctid: int, name: str) -> int:
    """Blocking: file the App row an interrupted install never got to file.

    Deliberately leaves `installed_url` NULL. The success path reads it from
    the script's last lines as they stream, and those lines are gone with the
    connection. Guessing a URL is worse than not having one: services/webui.py
    already asks the app when it is NULL, and that answer comes from the
    running container rather than from a reconstruction.
    """
    entry, _host, install_script = _resolve(app, catalog_slug, host_id)
    slug = f"{catalog_slug}-{host_id}-{ctid}"
    with app.state.sessionmaker() as db:
        existing = db.query(App).filter_by(host_id=host_id, ctid=ctid).one_or_none()
        if existing is not None:
            # Someone adopted it from the Apps page before reconciliation got
            # here. That is a resolution, not a collision.
            _resolve_install_job(app, job_id, "succeeded",
                                 result={"app_id": existing.id, "reconciled": True})
            return existing.id
        row = App(host_id=host_id, ctid=ctid, name=name, slug=slug,
                  catalog_slug=catalog_slug, category=entry.category,
                  installed_url=None, web_path="/", adopted=True,
                  update_available=None)
        db.add(row)
        db.flush()
        db.query(AppScript).filter_by(app_id=row.id).delete()
        db.add(AppScript(app_id=row.id, version=1, content=install_script,
                         content_sha256=hashlib.sha256(install_script.encode()).hexdigest(),
                         source="upstream", upstream_ref=entry.upstream_sha))
        db.commit()
        app_id = row.id
    _resolve_install_job(app, job_id, "succeeded",
                         result={"app_id": app_id, "reconciled": True})
    return app_id


async def run_install_reconcile(ctx: JobContext, params: dict) -> dict:
    """Ask the node what an interrupted install actually did.

    `run_install` already knows that exit status proves nothing and diffs the
    container ids before and after to find out what was really built. That
    check only ever ran on the success path, which is the one case where the
    answer was least in doubt. This runs the same check on the interruption
    path, from the checkpoint the interrupted run left behind.

    It is a job rather than a boot step so it can be retried and so it never
    makes startup wait on a node being reachable.

    Three outcomes, and only three:
      one new container   -> the install did build something. The App row is
                             created here, which is what makes catalog.py's
                             existing (host_id, ctid) guard refuse a duplicate
                             from then on.
      no new container    -> nothing was built. `failed` for real this time,
                             said after asking rather than assumed.
      anything ambiguous  -> stays `unknown`. An unreachable host or two new
                             containers is not an answer, and guessing here
                             would either orphan a container or claim one that
                             belongs to another job.
    """
    app = ctx.backend.app
    install_job_id = int(params["job_id"])
    with app.state.sessionmaker() as db:
        job = db.get(Job, install_job_id)
        if job is None:
            raise JobFailed(f"install job {install_job_id} no longer exists")
        if job.status != "unknown":
            # Already resolved, by an earlier reconcile or by an operator.
            # Doing nothing is the correct behaviour: this is the guard that
            # stops two reconciles racing into two App rows for one container.
            return {"job_id": install_job_id, "outcome": "already resolved",
                    "status": job.status}
        cp = dict(job.checkpoint or {})
    if not cp.get("dispatched"):
        raise JobFailed(f"install job {install_job_id} never dispatched anything")

    host_id = int(cp["host_id"])
    catalog_slug = cp["catalog_slug"]
    before = set(cp.get("before_ctids") or [])
    pinned = cp.get("ctid")

    ctx.log(f"asking the node what install job {install_job_id} actually did")
    after = await asyncio.to_thread(_lxc_ids, app, host_id)
    appeared = set(after) - before

    # A container an unrelated guest-creating job built during the same window
    # is not ours to claim. This is the reasoning _concurrent_guest_ctids was
    # written for, reused rather than restated.
    with app.state.sessionmaker() as db:
        j = db.get(Job, install_job_id)
        window_start, window_end = j.started_at, (j.finished_at or utcnow())
    concurrent = await asyncio.to_thread(
        _concurrent_guest_ctids, app, install_job_id, host_id,
        window_start, window_end)
    appeared -= concurrent

    if pinned is not None:
        # A pinned id removes the ambiguity entirely: either it is there or it
        # is not, and nothing else on the node can be mistaken for it.
        appeared = {int(pinned)} if int(pinned) in after else set()

    if not appeared:
        _resolve_install_job(app, install_job_id, "failed",
                             error=f"the connection was lost during the install, and "
                                   f"no container was created on the node. Checked "
                                   f"after the fact; nothing was left behind.")
        ctx.log("no container appeared: the install did not build anything")
        return {"job_id": install_job_id, "outcome": "nothing was built"}

    if len(appeared) != 1:
        raise JobFailed(
            f"{len(appeared)} containers appeared during install job "
            f"{install_job_id} and none was pinned, so which one belongs to it "
            f"cannot be established. Left unresolved deliberately: adopt the "
            f"right container from the Apps page.")

    ctid = appeared.pop()
    ctx.log(f"CT {ctid} exists: the install completed after the connection was lost")
    app_id = await asyncio.to_thread(
        _record_reconciled_install, app, install_job_id, catalog_slug, host_id,
        ctid, cp.get("name") or f"{catalog_slug}-{ctid}")
    app.state.poller.wake(host_id)
    app.state.bus.publish("resource", {"type": "app", "id": app_id,
                                       "change": "installed"})
    return {"job_id": install_job_id, "outcome": "container found", "app_id": app_id,
            "ctid": ctid}


HANDLERS["app.install.reconcile"] = run_install_reconcile

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
        # upstream_ref, so from_ref would read None below anyway, but that is
        # an accident of that route. Checked explicitly: if it is ever
        # backfilled with a ref, trusting the NULL would overwrite the edits.
        if latest is not None and latest.source == "edited":
            # api/apps.py::revert_app_script is the way out: it pins a fresh
            # version sourced "upstream" so this guard clears. Point at it by
            # name rather than making the operator guess.
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
             "prompts": entry.prompts,
             "install_script": pinned_payload_script(entry) or "",
             "from_ref": from_ref},
        )


def _lxc_ids(app, host_id: int) -> set[int]:
    """Blocking: every LXC id currently on the host, straight from PVE.

    One `/cluster/resources` call. Deliberately NOT the poller's cached
    snapshot: this is a safety check, and a cache up to 30 s stale is exactly
    what would miss a container created seconds ago.
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

    The API-side equivalent of build.func's `pvesm status -content "$content"`,
    the query that becomes an interactive picker when it returns more than one
    row. Not the poller's cached snapshot, same reason `_lxc_ids` gives. Sorted
    so two candidate lists compare stably and error messages read the same.
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
    # (overrides key, build.func content type)
    ("container_storage", "rootdir"),
    ("template_storage", "vztmpl"),
)


def resolve_storage_pools(app, host_id: int, supplied: dict) -> tuple[str, str]:
    """The container and template pools for this install, or JobFailed.

    THIS FUNCTION NEVER PICKS. Choosing a pool on the operator's behalf is the
    interactive-picker problem this design exists to refuse: build.func asks
    that question itself with `pvesm status -content "$content"` whenever it
    finds more than one candidate, and over a non-interactive SSH session that
    picker cannot be answered, so the run hangs. The order is:

      1. what the operator supplied for this install (`supplied`)
      2. the sole candidate, if the node has exactly one. Not a pick: there is
         nothing to choose between.
      3. refuse, naming the candidates so the operator can choose

    Nothing is remembered across installs: a host with two or more pools for a
    content type is asked every time, never answered from a prior install.

    Every value from (1) is revalidated against the node's current content list
    first. A stale or never-valid name reaches build.func's
    resolve_storage_preselect, whose failure branch returns 238 and then spins
    in a `while true` with an empty body: a real hang our 1800 s SSH timeout
    surfaces as an opaque `TimeoutError: `. Sending an unvalidated name is
    worse than sending none.
    """
    resolved = []
    for key, content in _STORAGE_CLASSES:
        candidates = _storage_pools(app, host_id, content)
        if not candidates:
            raise JobFailed(f"host has no storage carrying {content!r}")

        # str(...) first: the API validator constrains override KEYS to a
        # shell-identifier pattern but not value types, so a non-string value
        # reaches here and `.strip()` on a bare int raises AttributeError
        # instead of one of this function's JobFailed messages.
        chosen = str(supplied.get(key) or "").strip() or None
        if chosen:
            if chosen not in candidates:
                raise JobFailed(
                    f"storage {chosen!r} does not carry {content!r} on this host; "
                    f"available: {', '.join(candidates)}")
            resolved.append(chosen)
            continue

        if len(candidates) == 1:
            resolved.append(candidates[0])
            continue

        raise JobFailed(
            f"this host has {len(candidates)} pools for {content!r} and none has "
            f"been chosen: {', '.join(candidates)}. Choose one in the install form.")
    return resolved[0], resolved[1]


# Job kinds that build a new guest. JobBackend runs up to MAX_CONCURRENT jobs
# at once, so an id appearing in `after` that wasn't in `before` may belong to
# one of these running concurrently, not to this update's script taking
# build.func's install branch.
_GUEST_CREATING_KINDS = ("app.install", "vm.create", "vm.clone")


def _concurrent_guest_ctids(app, exclude_job_id: int, host_id: int,
                            window_start, window_end) -> set[int]:
    """Blocking: ctids from OTHER guest-creating jobs whose run overlapped this
    job's SSH window, so the stray-CT check does not point an operator at
    destroying a container an unrelated job legitimately built.

    Only `app.install`'s target id is knowable without guessing, and only when
    the operator supplied one: `params["ctid"]` reaches the script as
    `var_ctid`, so a job that has one built exactly that id. A CTID-less
    install contributes NOTHING, because the id it built is not knowable until
    it has built it. `vm.create`/`vm.clone` are qemu-only and can never produce
    an LXC row.
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
                continue
            if (j.kind == "app.install" and j.params
                    and j.params.get("host_id") == host_id):
                ctid = j.params.get("ctid")
                if ctid is not None:
                    ids.add(int(ctid))
        return ids


async def run_update(ctx: JobContext, params: dict) -> dict:
    """`app.update`: re-run the app's catalog script, pinned to the CURRENT
    upstream commit, over the same SSH path install uses. Consent and the diff
    are the API layer's job.

    Two guards bracket the SSH run. A community-scripts `ct/*.sh` decides for
    itself whether it is installing or updating: `build.func`'s `start` routes
    to `update_script()` when it finds the container and `build_container()`
    when it does not, and Proxploy cannot see inside that decision. Going the
    wrong way builds a second container while the `apps` row still points at
    the first, so the CT must exist BEFORE and no new CT may exist AFTER.

    RESIDUAL LIMITATION: whether an entry's update path is non-interactive is a
    property of that upstream script, and services/classifier.py classifies
    INSTALL feasibility only. An update path that prompts aborts under
    `set -Ee` and this job fails with the transcript archived.

    A SECOND, more severe one: the post-check is an id-SET comparison, so it is
    blind to a script that destroys CT <ctid> and rebuilds it at the SAME id.
    Nothing is added or missing, so this reports success and advances the pin
    over a freshly built, EMPTY container. Undetected, and the one failure mode
    here with real data loss.
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

    # Pinned to the exact commit, never `main`: same rule and same raw_url()
    # helper as run_install, with the same one-level-down residual.
    #
    # Run it INSIDE the container, not on the host. build.func's start() picks
    # install-vs-update purely by where it is running:
    #
    #     if command -v pveversion; then install_script        # on the PVE host
    #     elif [ "$PHS_SILENT" == 1 ]; then update_script      # in the CT
    #
    # `pveversion` exists on the host, so plain host SSH took the install
    # branch every time and built a SECOND container. No env var changes that.
    #
    # The env goes INSIDE the pct exec: the executor's own `env=` is a prefix
    # on the outer host command and does not cross into the container.
    inner = (f"curl -fsSL {raw_url(entry['sha'], entry['script_path'])} "
             f"-o /tmp/proxploy-update.sh && "
             f"TERM=xterm PHS_SILENT=1 bash /tmp/proxploy-update.sh; "
             f"rc=$?; rm -f /tmp/proxploy-update.sh; exit $rc")
    command = f"pct exec {int(a['ctid'])} -- bash -c {shlex.quote(inner)}"
    env: dict[str, str] = {}
    # An update re-runs the same script and meets the same prompts, so it
    # re-answers from what the install stored rather than asking again. This
    # is the reason the rows outlive the install.
    with app.state.sessionmaker() as db:
        stored = installanswers.for_app(db, app.state.secretstore, app_id)
    command = apply_answers(ctx, env, command, {}, stored, entry.get("prompts"))
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
        # Never an imperative "remove it": this is a whole-cluster snapshot
        # diff and jobs run concurrently, so a stray id is not proof this
        # update's script built it. And tell the truth about retrying: the pin
        # is left untouched below, so a plain retry hits the same branch again.
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
