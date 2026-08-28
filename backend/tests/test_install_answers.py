"""Install answers: the secret half never enters jobs.params.

The point of the store is that redaction stops being load-bearing. So the
assertions here are about ABSENCE from the params column, not about the
redaction heuristic doing its job, and the key names used are deliberately
ones that heuristic would sail straight past: `answer`, `prompt` and
`ziti_pwd` are the real shapes measured in the upstream catalog.
"""
import asyncio
import json

from proxploy.models import InstallAnswer, Job

SENTINEL = "pxp-token-9c1e7a3f5b2d8e64"


def _store(app):
    return app.state.secretstore


def test_a_staged_answer_round_trips_and_never_touches_params(tmp_path, monkeypatch):
    from proxploy.jobs import HANDLERS, JobBackend
    from proxploy.services import installanswers
    from tests.support import make_job_app

    async def run():
        app = make_job_app(tmp_path)
        backend = JobBackend(app)

        with app.state.sessionmaker() as db:
            handle = installanswers.stage(db, _store(app), {"prompt": SENTINEL})
        assert handle and SENTINEL not in handle

        seen = {}

        async def demo(ctx, params):
            with app.state.sessionmaker() as db:
                seen.update(installanswers.load(db, _store(app),
                                                params["answers_handle"]))
            ctx.hide(*seen.values())
            ctx.log(f"using {seen['prompt']}")
            return {"ok": True}

        monkeypatch.setitem(HANDLERS, "test.answers", demo)
        with app.state.sessionmaker() as db:
            job_id = backend.enqueue(db, kind="test.answers",
                                     params={"answers_handle": handle}).id
        assert await backend.wait(job_id, timeout=5) is True

        # The handler got the real value.
        assert seen == {"prompt": SENTINEL}
        with app.state.sessionmaker() as db:
            row = db.get(Job, job_id)
            stored = db.query(InstallAnswer).one()
        # And the column that would have leaked it holds only the handle.
        assert row.params == {"answers_handle": handle}
        assert SENTINEL not in json.dumps(row.params)
        # At rest it is ciphertext, not JSON we could read back.
        assert SENTINEL.encode() not in stored.encrypted_blob

    asyncio.run(run())


def test_bind_ties_answers_to_the_app_and_uninstall_takes_them_with_it(tmp_path):
    from proxploy.models import App, Host
    from proxploy.services import installanswers
    from tests.support import make_job_app

    async def run():
        app = make_job_app(tmp_path)
        with app.state.sessionmaker() as db:
            host = Host(name="h", address="https://h:8006", status="connected")
            db.add(host); db.commit()
            row = App(host_id=host.id, ctid=101, name="a", slug="a-1-101")
            db.add(row); db.commit()
            app_id = row.id
            handle = installanswers.stage(db, _store(app), {"ziti_pwd": SENTINEL})
            installanswers.bind(db, handle, app_id)
            # app.update reads them back by app, not by handle.
            assert installanswers.for_app(db, _store(app), app_id) == {
                "ziti_pwd": SENTINEL}
            db.delete(db.get(App, app_id)); db.commit()
            # ON DELETE CASCADE: nothing has to remember to clean this up.
            assert db.query(InstallAnswer).count() == 0

    asyncio.run(run())


def test_an_unbound_row_is_swept_but_a_bound_one_is_not(tmp_path):
    from datetime import timedelta

    from proxploy.models import App, Host, utcnow
    from proxploy.services import installanswers
    from tests.support import make_job_app

    async def run():
        app = make_job_app(tmp_path)
        with app.state.sessionmaker() as db:
            host = Host(name="h", address="https://h:8006", status="connected")
            db.add(host); db.commit()
            keep_app = App(host_id=host.id, ctid=102, name="b", slug="b-1-102")
            db.add(keep_app); db.commit()

            fresh = installanswers.stage(db, _store(app), {"a": SENTINEL})
            stale = installanswers.stage(db, _store(app), {"b": SENTINEL})
            bound = installanswers.stage(db, _store(app), {"c": SENTINEL})
            installanswers.bind(db, bound, keep_app.id)

            old = utcnow() - installanswers.ORPHAN_TTL - timedelta(minutes=1)
            for h in (stale, bound):
                db.query(InstallAnswer).filter_by(handle=h).one().created_at = old
            db.commit()

            assert installanswers.sweep_orphans(db) == 1
            left = {r.handle for r in db.query(InstallAnswer).all()}
            assert left == {fresh, bound}, "swept the wrong rows"

    asyncio.run(run())


def test_a_missing_handle_is_empty_rather_than_an_error(tmp_path):
    """A job retried after the sweeper ran must fail at the prompt it cannot
    answer, not with a 500 from the store."""
    from proxploy.services import installanswers
    from tests.support import make_job_app

    async def run():
        app = make_job_app(tmp_path)
        with app.state.sessionmaker() as db:
            assert installanswers.load(db, _store(app), "no-such-handle") == {}
            assert installanswers.load(db, _store(app), None) == {}
            assert installanswers.stage(db, _store(app), {}) is None

    asyncio.run(run())


def test_apply_answers_allowlists_only_what_it_was_given(tmp_path):
    """The shim is in scope for build.func's own `read` calls. It must be
    inert for anything not in PXP_ANSWERED, or it would answer upstream's
    menus with whatever happened to be exported."""
    from proxploy.jobs import JobBackend, JobContext
    from proxploy.services.appstore import READ_SHIM, apply_answers
    from tests.support import make_job_app

    async def run():
        app = make_job_app(tmp_path)
        ctx = JobContext(JobBackend(app), 1)
        env: dict = {}
        prompts = [{"variable": "VER", "kind": "text", "label": "v"},
                   {"variable": "TMDBKEY", "kind": "text", "label": "k"}]
        out = apply_answers(ctx, env, "bash -c run", {"VER#0": "17"},
                            {"TMDBKEY#1": SENTINEL}, prompts)
        # Wrapped rather than prefixed. executor/ssh.py puts `NAME=value ...`
        # in front of whatever this returns, and a function definition cannot
        # follow an environment prefix: a real node answered
        # "syntax error near unexpected token `('" to the prefixed version.
        assert out.startswith("bash -c ")
        assert READ_SHIM in out and out.endswith("'")
        assert not out.startswith(READ_SHIM), "prefixing is the bug, not the fix"
        assert env["PXP_A_VER_1"] == "17" and env["PXP_A_TMDBKEY_1"] == SENTINEL
        assert set(env["PXP_ANSWERED"].split()) == {"VER", "TMDBKEY"}
        # The secret is hidden; the version number stays readable, because a
        # transcript with [redacted] where "17" should be is unusable.
        assert ctx.scrub(f"key={SENTINEL} ver=17") == "key=[redacted] ver=17"

    asyncio.run(run())


def test_no_answers_means_no_shim_and_no_row(tmp_path):
    """An app whose script never prompts must run the exact command it ran
    before this existed."""
    from proxploy.jobs import JobBackend, JobContext
    from proxploy.services.appstore import apply_answers
    from tests.support import make_job_app

    async def run():
        app = make_job_app(tmp_path)
        ctx = JobContext(JobBackend(app), 1)
        env: dict = {}
        assert apply_answers(ctx, env, "bash -c run", {}, {}) == "bash -c run"
        assert env == {}

    asyncio.run(run())
