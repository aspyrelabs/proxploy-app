"""POST /catalog/{slug}/install with answers to the script's own prompts.

The trust boundary this route owns: an answer becomes an environment variable
in a root shell on the operator's node, and the variable NAMES come from
upstream catalog data. So the route validates against the prompts it recorded
rather than accepting whatever the caller sends, exactly as it already does
for `overrides`.
"""
from proxploy.models import CatalogEntry, HostCredential, InstallAnswer, Job

SENTINEL = "pxp-route-token-71c4e9"

PROMPTS = [
    {"variable": "confirm", "label": "Do you want to continue? [y/N]",
     "kind": "yesno", "default": "n", "gate": True, "sensitive": False},
    {"variable": "unbound", "label": "Would you like to add Unbound? <y/N>",
     "kind": "yesno", "default": "n", "gate": False, "sensitive": False},
    {"variable": "tmdbkey", "label": "Enter your TMDb API key:",
     "kind": "text", "default": None, "gate": False, "sensitive": True},
]


def _seed(client, prompts=PROMPTS):
    from tests.support import seed_host_row
    with client.app.state.sessionmaker() as db:
        db.add(CatalogEntry(slug="redis", name="Redis", installable=True,
                            prompts=prompts))
        host = seed_host_row(db)
        db.add(HostCredential(host_id=host.id, kind="ssh_key",
                              encrypted_blob=b"x", key_version=1,
                              public_meta="ssh-ed25519 AAAA"))
        db.commit()
        return host.id


def _post(client, csrf_header, host_id, answers):
    return client.post("/api/v1/catalog/redis/install",
                       json={"host_id": host_id, "name": "Redis", "ctid": 150,
                             "consent": True, "answers": answers},
                       headers=csrf_header(client))


def test_a_sensitive_answer_never_lands_in_job_params(client, csrf_header,
                                                      bootstrap_admin):
    """The whole point of the store. params carries a handle; the value is
    encrypted in its own row."""
    bootstrap_admin(client)
    host_id = _seed(client)
    r = _post(client, csrf_header, host_id,
              {"confirm#0": "y", "unbound#1": "y", "tmdbkey#2": SENTINEL})
    assert r.status_code == 202, r.text

    with client.app.state.sessionmaker() as db:
        job = db.query(Job).filter_by(kind="app.install").one()
        row = db.query(InstallAnswer).one()
    assert SENTINEL not in str(job.params), "the API leaked it into jobs.params"
    assert job.params["answers"] == {"confirm#0": "y", "unbound#1": "y"}
    assert job.params["answers_handle"] == row.handle
    # At rest it is ciphertext, and the row is not yet attached to any app
    # because the job that would create one has not run.
    assert SENTINEL.encode() not in row.encrypted_blob
    assert row.app_id is None


def test_an_answer_the_script_never_asked_for_is_refused(client, csrf_header,
                                                         bootstrap_admin):
    """Answers become environment variables in a root shell. Only names this
    script actually asks about may pass, the same rule `overrides` follows."""
    bootstrap_admin(client)
    host_id = _seed(client)
    r = _post(client, csrf_header, host_id,
              {"confirm#0": "y", "tmdbkey#2": "k", "LD_PRELOAD": "/tmp/evil.so"})
    assert r.status_code == 400, r.text
    assert "LD_PRELOAD" in r.json()["detail"]
    assert client.get("/api/v1/jobs").json() == [], "enqueued despite refusing"
    with client.app.state.sessionmaker() as db:
        assert db.query(InstallAnswer).count() == 0, "staged a secret anyway"


def test_a_gate_must_be_answered_and_must_be_answered_yes(client, csrf_header,
                                                          bootstrap_admin):
    bootstrap_admin(client)
    host_id = _seed(client)

    # Omitted entirely: refused rather than defaulted.
    r = _post(client, csrf_header, host_id, {"tmdbkey#2": "k"})
    assert r.status_code == 400 and "confirm" in r.json()["detail"]

    # Explicitly declined: refused, and nothing is installed.
    r = _post(client, csrf_header, host_id, {"confirm#0": "n", "tmdbkey#2": "k"})
    assert r.status_code == 400 and "not confirmed" in r.json()["detail"]

    assert client.get("/api/v1/jobs").json() == []


def test_a_required_free_text_answer_cannot_be_skipped(client, csrf_header,
                                                       bootstrap_admin):
    """No default exists for an API key, so proceeding without one produces an
    install that blocks at the prompt. Refuse at the door instead."""
    bootstrap_admin(client)
    host_id = _seed(client)
    r = _post(client, csrf_header, host_id, {"confirm#0": "y"})
    assert r.status_code == 400
    assert "tmdbkey" in r.json()["detail"] and "TMDb API key" in r.json()["detail"]


def test_a_defaultable_prompt_may_be_omitted(client, csrf_header, bootstrap_admin):
    """The 26 no-dialog apps depend on this. Only `unbound` is omitted here and
    the handler fills it from the recorded default."""
    bootstrap_admin(client)
    host_id = _seed(client)
    r = _post(client, csrf_header, host_id, {"confirm#0": "y", "tmdbkey#2": SENTINEL})
    assert r.status_code == 202, r.text
    with client.app.state.sessionmaker() as db:
        job = db.query(Job).filter_by(kind="app.install").one()
    assert "unbound#1" not in job.params["answers"]


def test_an_app_that_asks_nothing_stages_nothing(client, csrf_header, bootstrap_admin):
    """Every app installable before this existed has prompts == [], and must
    enqueue exactly the job it always did."""
    bootstrap_admin(client)
    host_id = _seed(client, prompts=[])
    r = _post(client, csrf_header, host_id, {})
    assert r.status_code == 202, r.text
    with client.app.state.sessionmaker() as db:
        job = db.query(Job).filter_by(kind="app.install").one()
        assert db.query(InstallAnswer).count() == 0
    assert job.params["answers"] == {} and job.params["answers_handle"] is None


def test_the_audit_row_records_which_prompts_were_answered_never_the_values(
        client, csrf_header, bootstrap_admin):
    """audit_events.params is unencrypted and readable from GET /audit."""
    bootstrap_admin(client)
    host_id = _seed(client)
    r = _post(client, csrf_header, host_id,
              {"confirm#0": "y", "unbound#1": "y", "tmdbkey#2": SENTINEL})
    assert r.status_code == 202, r.text
    rows = client.get("/api/v1/audit").json()
    body = str(rows)
    assert SENTINEL not in body, "the audit trail leaked the answer"
    assert "tmdbkey" in body, "should still say WHICH prompts were answered"
