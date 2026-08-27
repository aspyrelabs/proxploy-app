"""A value the handler marked secret must not survive in ANY job sink.

Tested by execution rather than by reading the code, because the sinks are
what the last audit got wrong: `jobs.params` was already redacted and looked
covered, while `job_events.message` was not redacted at all and neither was
the terminal error text. A sentinel driven through the real JobBackend is the
only thing that proves which is which.

The failing case matters more than the happy one. An install script
interpolates an answer straight into a command (kometa-install.sh:36 puts the
TMDb API key into a `sed`), so the value surfaces in stderr and under xtrace,
not in the transcript the script meant to print.
"""
import asyncio
import logging

from proxploy.models import Job, JobEvent

SENTINEL = "pxp-sentinel-4f8a1c9e2b7d"


def _drain(q: asyncio.Queue) -> list:
    out = []
    while not q.empty():
        out.append(q.get_nowait())
    return out


def test_a_hidden_answer_reaches_no_sink_on_success(tmp_path, monkeypatch, caplog):
    from proxploy.jobs import HANDLERS, JobBackend
    from tests.support import make_job_app

    async def run():
        app = make_job_app(tmp_path)
        backend = JobBackend(app)
        bus_q = app.state.bus.subscribe()

        async def demo(ctx, params):
            ctx.hide(params["answer"])
            ctx.log(f"writing config with apikey: {params['answer']}")
            ctx.log(f"sed: apikey: {params['answer']}", stream="stderr")
            logging.getLogger("proxploy.test").info(
                "handler saw %s", params["answer"])
            return {"configured_with": params["answer"]}

        monkeypatch.setitem(HANDLERS, "test.secret", demo)
        with caplog.at_level(logging.DEBUG):
            with app.state.sessionmaker() as db:
                job_id = backend.enqueue(db, kind="test.secret",
                                         params={"answer": SENTINEL}).id
            job_q = backend.subscribe(job_id)
            assert await backend.wait(job_id, timeout=5) is True

        with app.state.sessionmaker() as db:
            row = db.get(Job, job_id)
            lines = db.query(JobEvent).filter_by(job_id=job_id).all()

        # The transcript kept the shape, lost the value.
        assert any("apikey: [redacted]" in e.message for e in lines)
        assert all(SENTINEL not in e.message for e in lines), "leaked into job_events"
        assert SENTINEL not in str(row.result), "leaked into jobs.result"
        # jobs.params is NOT asserted here, and that is not an oversight.
        # enqueue() redacts params by KEY NAME long before any handler exists
        # to call ctx.hide, so this scrubber structurally cannot reach it: the
        # row is written first. An answer keyed "answer" sails straight past
        # the name heuristic and lands in the column in clear. Closing that is
        # the secretstore work (recommendation 2), which puts a handle in
        # params and leaves nothing to redact. Deliberately not papered over
        # by widening REDACT_SUBSTRINGS.
        assert all(SENTINEL not in str(f) for f in _drain(job_q)), "leaked over the job SSE stream"
        assert all(SENTINEL not in str(f) for f in _drain(bus_q)), "leaked over the global SSE bus"
        assert all(SENTINEL not in r.getMessage() for r in caplog.records), \
            "leaked into a log record"

    asyncio.run(run())


def test_a_hidden_answer_reaches_no_sink_when_the_command_fails(tmp_path, monkeypatch,
                                                                caplog):
    """The path the analysis flagged: error text, not the happy path.

    `error` fans out to five places from JobBackend._finish, so this asserts on
    all five rather than on the database row alone.
    """
    from proxploy.jobs import HANDLERS, JobBackend, JobFailed
    from tests.support import make_job_app

    async def run():
        app = make_job_app(tmp_path)
        backend = JobBackend(app)
        bus_q = app.state.bus.subscribe()

        async def boom(ctx, params):
            ctx.hide(params["answer"])
            # Exactly the shape a failing `sed` produces once the answer has
            # been interpolated into the command line.
            ctx.log(f"+ sed -i s|apikey:.*|apikey: {params['answer']}| config.yml",
                    stream="stderr")
            raise JobFailed(
                f"sed: -e expression #1, char 42: unterminated `s' command "
                f"(apikey: {params['answer']})")

        monkeypatch.setitem(HANDLERS, "test.secret_boom", boom)
        with caplog.at_level(logging.DEBUG):
            with app.state.sessionmaker() as db:
                job_id = backend.enqueue(db, kind="test.secret_boom",
                                         params={"answer": SENTINEL}).id
            job_q = backend.subscribe(job_id)
            assert await backend.wait(job_id, timeout=5) is True

        with app.state.sessionmaker() as db:
            row = db.get(Job, job_id)
            lines = db.query(JobEvent).filter_by(job_id=job_id).all()

        assert row.status == "failed"
        # The operator still gets a usable reason, just without the value.
        assert "unterminated" in row.error and "[redacted]" in row.error
        assert SENTINEL not in row.error, "leaked into jobs.error"
        assert all(SENTINEL not in e.message for e in lines), \
            "leaked into job_events, including the terminal status row"
        assert all(SENTINEL not in str(f) for f in _drain(job_q)), "leaked over the job SSE stream"
        assert all(SENTINEL not in str(f) for f in _drain(bus_q)), \
            "leaked over the global SSE bus, which is what the failure toast reads"
        assert all(SENTINEL not in r.getMessage() for r in caplog.records), \
            "leaked into a log record"

    asyncio.run(run())


def test_hide_refuses_a_value_too_short_to_scrub_safely(tmp_path):
    """`ctx.hide("y")` would replace every "y" in the transcript and tell an
    attacker nothing they could not guess. Refused, not scrubbed."""
    from proxploy.jobs import JobBackend, JobContext
    from tests.support import make_job_app

    async def run():
        app = make_job_app(tmp_path)
        ctx = JobContext(JobBackend(app), 1)
        ctx.hide("y", "no", None, "")
        assert ctx.scrub("you are not redacted") == "you are not redacted"
        ctx.hide("a-real-token-value")
        assert ctx.scrub("t=a-real-token-value") == "t=[redacted]"

    asyncio.run(run())


def test_the_longer_of_two_overlapping_values_wins(tmp_path):
    """A password that contains a shorter registered value must not leave the
    tail of itself behind after the shorter one is replaced first."""
    from proxploy.jobs import JobBackend, JobContext
    from tests.support import make_job_app

    async def run():
        app = make_job_app(tmp_path)
        ctx = JobContext(JobBackend(app), 1)
        ctx.hide("secret", "secret-extended-tail")
        assert ctx.scrub("v=secret-extended-tail") == "v=[redacted]"

    asyncio.run(run())
