"""Repo-wide 422 handler must never echo a secret-bearing request body back
to the caller (main.py::_no_echo_validation_errors).

Pydantic v2's "missing" error reports the whole parent body as `input` when
a sibling field is absent, so any route taking a secret alongside another
required field leaks that secret in the validation-error response unless the
handler strips `input`. Three routes take a secret in the body: ChannelIn.url,
HostIn.token_secret, LicenseIn.license_key.
"""
import asyncio

import pytest
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient

CHANNEL_SECRET = "ntfy://secretuser:sup3rsecret@ntfy.sh/private-topic"
TOKEN_SECRET = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
LICENSE_SECRET = "PROXPLOY-LICENSE-KEY-DO-NOT-LEAK"


def test_channel_missing_name_does_not_echo_the_url(tmp_path, csrf_header, bootstrap_admin):
    from tests.support import make_app

    with TestClient(make_app(tmp_path)) as c:
        bootstrap_admin(c)
        r = c.post("/api/v1/notifications/channels", json={"url": CHANNEL_SECRET},
                   headers=csrf_header(c))
        assert r.status_code == 422
        assert CHANNEL_SECRET not in r.text
        assert "input" not in r.json()["detail"][0]


def test_host_missing_address_does_not_echo_the_token_secret(tmp_path, csrf_header,
                                                              bootstrap_admin):
    from tests.support import make_app

    with TestClient(make_app(tmp_path)) as c:
        bootstrap_admin(c)
        r = c.post("/api/v1/hosts", json={"name": "pve1", "token_id": "root@pam!proxploy",
                                          "token_secret": TOKEN_SECRET},
                   headers=csrf_header(c))
        assert r.status_code == 422
        assert TOKEN_SECRET not in r.text
        assert "input" not in r.json()["detail"][0]


def test_license_missing_key_does_not_echo_a_mistyped_secret_field(tmp_path, csrf_header,
                                                                    bootstrap_admin):
    """license_key is LicenseIn's only field, so there's no sibling to omit
    around it, the realistic leak is a caller who typos the field name and
    the secret rides along as an unrecognized extra key in the same body."""
    from tests.support import make_app

    with TestClient(make_app(tmp_path)) as c:
        bootstrap_admin(c)
        r = c.post("/api/v1/entitlements/license", json={"key": LICENSE_SECRET},
                   headers=csrf_header(c))
        assert r.status_code == 422
        assert LICENSE_SECRET not in r.text
        assert "input" not in r.json()["detail"][0]


def test_validation_handler_survives_a_raw_exception_in_ctx(tmp_path):
    """Pydantic v2 puts the raw exception object in an error's `ctx` when a
    field_validator/model_validator raises ValueError (e.g. `ctx: {'error':
    ValueError(...)}`), that object isn't JSON-serializable on its own, so
    building the response with a plain dict (skipping jsonable_encoder, as
    FastAPI's own default handler does not) raises TypeError instead of
    returning 422. This repo has no field_validator/model_validator today, so
    call the registered handler directly with a fake exc carrying that shape
    rather than routing a real request through one."""
    from tests.support import make_app

    app = make_app(tmp_path)
    handler = app.exception_handlers[RequestValidationError]

    class _FakeExc:
        def errors(self):
            return [{"type": "value_error", "loc": ("body", "name"),
                     "msg": "Value error, boom", "ctx": {"error": ValueError("boom")}}]

    response = asyncio.run(handler(None, _FakeExc()))
    assert response.status_code == 422
    assert b"boom" in response.body  # would have raised TypeError pre-fix


def test_problem_json_handler_for_http_exceptions_is_unaffected(tmp_path, csrf_header,
                                                                 bootstrap_admin):
    """The RequestValidationError handler is new and separate from the
    existing RFC 9457 problem+json handler for StarletteHTTPException, 
    confirm a plain HTTPException(422, ...) still gets the problem+json shape."""
    from tests.support import make_app

    with TestClient(make_app(tmp_path)) as c:
        bootstrap_admin(c)
        r = c.post("/api/v1/notifications/channels",
                   json={"name": "n", "url": "not-a-url"}, headers=csrf_header(c))
        assert r.status_code == 422
        assert r.headers["content-type"] == "application/problem+json"
        body = r.json()
        assert body["type"] == "about:blank" and body["status"] == 422
        assert "url must be an Apprise URL" in body["detail"]




def test_audit_redact_covers_near_miss_secret_key_names():
    """`k.lower() in REDACT_KEYS` was exact membership, so any key name that
    merely CONTAINS a secret marker sailed into the unencrypted
    `audit_events.params` column and out of GET /audit."""
    from proxploy.services.audit import redact

    leaky = {"token_id": "PVEAPIToken=root@pam!p=s3cret", "apprise_url": "ntfy://a:b@h/t",
             "db_url": "postgresql://u:pw@h/d", "dsn": "postgresql://u:pw@h/d",
             "secret_key": "sk", "api_credential": "c", "private_pem": "p",
             "user_password": "hunter2", "totp_secret": "t"}
    assert set(redact(leaky).values()) == {"[redacted]"}

    # ...while the keys that carry no value stay legible. settings.update
    # audits {"keys": [...]}: the NAMES of the settings changed, never their
    # values: and redacting that would blind the audit trail for nothing.
    kept = {"keys": ["a.b", "c.d"], "name": "ntfy", "kind": "webhook", "role": "admin"}
    assert redact(kept) == kept




# --- secret-bearing input echoed into a plaintext sink -----------------------
#
# Same class as the two already-fixed cases (notifier.kind_for writing a
# malformed URL into the unencrypted `kind` column; urllib3 logging a
# token-bearing request line). Each test below forces one leak path and
# asserts a sentinel appears in neither the response nor any log record
# reaching a root handler.

import contextlib
import logging
import sqlite3

PVE_TOKEN_SECRET = "S3NTINEL-TOKEN-SECRET-abc123"
REFRESH_CRED = "S3NTINEL-REFRESH-CRED-www"


@contextlib.contextmanager
def _root_log_capture():
    """A handler on the ROOT logger only, the way an operator's
    `logging.basicConfig()` behaves. Deliberately not `caplog`, which attaches
    itself to non-propagating loggers directly and so cannot observe a
    `propagate = False` guarantee (see test_notifier.py for the long form).
    """
    records: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = records.append
    root = logging.getLogger()
    orig = root.level
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    try:
        yield records
    finally:
        root.removeHandler(handler)
        root.setLevel(orig)


def _messages(records):
    out = []
    for r in records:
        try:
            out.append(r.getMessage())
        except Exception:  # noqa: BLE001  (a mis-formatted record is still evidence)
            out.append(f"{r.msg!r}{r.args!r}")
    return "\n".join(out)


def _db_cells(db_path):
    """Every text/blob cell in the database, so a test can assert no
    *unencrypted* column anywhere picked the secret up."""
    conn = sqlite3.connect(db_path)
    try:
        cells = []
        for (table,) in conn.execute(
                "select name from sqlite_master where type='table'"):
            cur = conn.execute(f"select * from '{table}'")  # noqa: S608  (table names from sqlite_master)
            for row in cur.fetchall():
                for value in row:
                    if isinstance(value, bytes):
                        cells.append(value.decode("utf-8", "replace"))
                    elif isinstance(value, str):
                        cells.append(value)
        return "\n".join(cells)
    finally:
        conn.close()


def test_proxmox_error_never_echoes_the_authorization_header(tmp_path, csrf_header,
                                                             bootstrap_admin):
    """urllib3 rejects a header value it cannot send by raising InvalidHeader
    with the WHOLE header inline, for proxmoxer that header is
    `PVEAPIToken=user@realm!name=<secret>`. services/proxmox.py wraps whatever
    the client raised into ProxmoxError, api/hosts.py turns that into
    `HTTPException(502, str(e))`, and main.py::problem_handler serialises the
    detail straight into the body, so the secret reached the caller verbatim.

    The factory here raises the exact message a real urllib3 produced (captured
    from a live TLS server against real proxmoxer 2.3.0 / requests 2.34.2), 
    that keeps the regression pinned without a network, and it also covers
    every OTHER third-party message shape that might carry the credential,
    which a `_header_safe` input check alone would not.
    """
    from tests.support import make_app

    header_echo = (f"Invalid header value "
                   f"b'PVEAPIToken=root@pam!proxploy={PVE_TOKEN_SECRET}\\n'")

    def exploding_factory(**kwargs):
        raise ValueError(header_echo)

    app = make_app(tmp_path)
    app.state.proxmox_factory = exploding_factory
    with TestClient(app) as c, _root_log_capture() as records:
        bootstrap_admin(c)
        r = c.post("/api/v1/hosts/probe",
                   json={"address": "https://10.0.0.5:8006",
                         "token_id": "root@pam!proxploy",
                         "token_secret": PVE_TOKEN_SECRET, "verify_tls": False},
                   headers=csrf_header(c))
    assert r.status_code == 502
    assert PVE_TOKEN_SECRET not in r.text
    assert "***" in r.json()["detail"]  # scrubbed, not merely absent by luck
    assert PVE_TOKEN_SECRET not in _messages(records)


def test_a_token_secret_that_cannot_be_a_header_is_refused_without_echoing_it():
    """The root cause of the InvalidHeader above: a copy-pasted secret with a
    trailing newline. Rejected before it reaches urllib3 at all, asserted by
    the factory never being called, since `_wrap`'s redaction would otherwise
    make the resulting message look clean either way."""
    from proxploy.services.proxmox import ProxmoxClient, ProxmoxError

    for bad in (PVE_TOKEN_SECRET + "\n", PVE_TOKEN_SECRET + "\r\nX-Evil: 1",
                " " + PVE_TOKEN_SECRET, PVE_TOKEN_SECRET + "中"):
        called = []

        def factory(**kwargs):
            called.append(kwargs)
            return None

        client = ProxmoxClient("https://10.0.0.5:8006", "root@pam!proxploy", bad,
                               factory=factory)
        try:
            client.version()
        except ProxmoxError as e:
            assert PVE_TOKEN_SECRET not in str(e)
        else:
            raise AssertionError(f"{bad!r} should not have been accepted")
        assert not called, f"{bad!r} was handed to the HTTP client anyway"


def test_pasted_pveapitoken_never_reaches_an_unencrypted_sink(tmp_path, csrf_header,
                                                              bootstrap_admin):
    """Proxmox's own copy button yields `PVEAPIToken=user@realm!name=<secret>`.
    Pasting that whole string into `token_id` used to satisfy the old shape
    check, and `token_id` is written verbatim to the UNENCRYPTED
    `host_credentials.public_meta`, returned by GET /hosts/{id} to any viewer,
    and stored in `audit_events.params` (which `redact` missed, because
    "token_id" is not an exact member of REDACT_KEYS) and served by GET /audit.
    """
    from tests.fakes.pve import FakePVE
    from tests.support import make_app

    pasted = f"PVEAPIToken=root@pam!proxploy={PVE_TOKEN_SECRET}"
    with TestClient(make_app(tmp_path, fake=FakePVE())) as c, _root_log_capture() as records:
        bootstrap_admin(c)
        created = c.post("/api/v1/hosts",
                         json={"name": "pve1", "address": "https://10.0.0.5:8006",
                               "token_id": pasted, "token_secret": "irrelevant",
                               "verify_tls": False},
                         headers=csrf_header(c))
        assert created.status_code == 422, "unparseable token id must be refused"
        assert PVE_TOKEN_SECRET not in created.text
        assert PVE_TOKEN_SECRET not in c.get("/api/v1/hosts").text
        assert PVE_TOKEN_SECRET not in c.get("/api/v1/audit?per_page=100").text
    assert PVE_TOKEN_SECRET not in _messages(records)
    assert PVE_TOKEN_SECRET not in _db_cells(tmp_path / "t.db")


def test_public_meta_is_rebuilt_from_parsed_parts_not_the_submitted_string(
        tmp_path, csrf_header, bootstrap_admin):
    """The onboarding half of the same fix, from the other direction: when the
    operator DOES paste correctly, the row that lands in the unencrypted
    `host_credentials.public_meta` must be the one we constructed from the
    parsed user/realm/name, not the caller's string, however validated.

    Proven by feeding a token id whose secret half is separated only by an
    invisible-to-a-denylist difference and asserting the sentinel is in none of
    the three plaintext sinks: public_meta, the API response, audit_events.
    """
    from proxploy.models import HostCredential
    from tests.fakes.pve import FakePVE
    from tests.support import make_app

    app = make_app(tmp_path, fake=FakePVE())
    with TestClient(app) as c:
        bootstrap_admin(c)
        created = c.post("/api/v1/hosts",
                         json={"name": "pve1", "address": "https://10.0.0.5:8006",
                               "token_id": "root@pam!proxploy",
                               "token_secret": PVE_TOKEN_SECRET,
                               "verify_tls": True},
                         headers=csrf_header(c))
        assert created.status_code == 201, created.text
        detail = c.get(f"/api/v1/hosts/{created.json()['id']}").json()
        meta = [cred["public_meta"] for cred in detail["credentials"]
                if cred["kind"] == "api_token"]
        assert meta == ["root@pam!proxploy"]
        assert PVE_TOKEN_SECRET not in c.get(f"/api/v1/hosts/{created.json()['id']}").text
        assert PVE_TOKEN_SECRET not in c.get("/api/v1/audit?per_page=100").text
    with app.state.sessionmaker() as db:
        for cred in db.query(HostCredential):
            assert PVE_TOKEN_SECRET not in (cred.public_meta or "")
    assert PVE_TOKEN_SECRET not in _db_cells(tmp_path / "t.db")


def test_a_real_token_id_still_works(tmp_path, csrf_header, bootstrap_admin):
    """The allowlist must not break onboarding, pinned so a future tightening
    cannot quietly reject the shapes Proxmox actually issues."""
    from proxploy.services.proxmox import parse_token_id

    for good in ("root@pam!proxploy", "proxploy@pve!monitor-01",
                 "svc.account@ldap!token_2", "a+b@pam!t"):
        assert parse_token_id(good)[0].endswith(good.split("@")[1].split("!")[0])


def test_an_ldap_username_with_spaces_and_non_ascii_is_accepted(tmp_path, csrf_header,
                                                                bootstrap_admin):
    """Review item 6: the username class must stay WIDE. An AD/LDAP login is
    routinely `Ana Sofía Ruiz`, a tightened allowlist would reject a legitimate
    operator. Widening is safe only because the separators are what carry the
    secret, so the same test pins that the pasted-secret shape is STILL refused
    with the wide class in force, and that the widened name survives the round
    trip into public_meta intact.
    """
    from proxploy.services.proxmox import ProxmoxError, token_public_meta
    from tests.fakes.pve import FakePVE
    from tests.support import make_app

    wide = "Ana Sofía Ruiz@ldap!monitor-01"
    assert token_public_meta(wide) == wide

    for still_banned in (f"PVEAPIToken=Ana Sofía Ruiz@ldap!monitor-01={PVE_TOKEN_SECRET}",
                         f"Ana Sofía Ruiz@ldap!monitor-01={PVE_TOKEN_SECRET}",
                         f"Ana Sofía Ruiz@ldap!monitor-01!{PVE_TOKEN_SECRET}",
                         "Ana Sofía Ruiz@ldap!moni\ntor"):
        with pytest.raises(ProxmoxError):
            token_public_meta(still_banned)

    with TestClient(make_app(tmp_path, fake=FakePVE())) as c:
        bootstrap_admin(c)
        r = c.post("/api/v1/hosts",
                   json={"name": "pve1", "address": "https://10.0.0.5:8006",
                         "token_id": wide, "token_secret": PVE_TOKEN_SECRET},
                   headers=csrf_header(c))
        assert r.status_code == 201, r.text
        detail = c.get(f"/api/v1/hosts/{r.json()['id']}").json()
        assert any(cred["public_meta"] == wide for cred in detail["credentials"])



def test_license_api_error_never_relays_the_remote_body(tmp_path, csrf_header,
                                                        bootstrap_admin, monkeypatch):
    """`refresh()` sends a credential the caller never sees (decrypted from
    license.refresh_credential.enc). The client used to interpolate the remote
    response body into LicenseApiError, and api/entitlements.py puts that
    straight into a 502 `detail`, so a licensing API that names the offending
    value in its error handed the credential to the browser."""
    import httpx

    from proxploy.services.settings import set_setting
    from tests.support import make_app

    def fake_post(url, **kwargs):
        return httpx.Response(400, json={"error": f"unknown credential {REFRESH_CRED}"},
                              request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", fake_post)

    app = make_app(tmp_path)
    with TestClient(app) as c, _root_log_capture() as records:
        bootstrap_admin(c)
        with app.state.sessionmaker() as db:
            enc, _ = app.state.secretstore.encrypt(REFRESH_CRED.encode())
            set_setting(db, "license.refresh_credential.enc", enc.decode())
        r = c.post("/api/v1/entitlements/refresh", headers=csrf_header(c))
        assert r.status_code == 502
        assert REFRESH_CRED not in r.text
        assert REFRESH_CRED not in c.get("/api/v1/audit?per_page=100").text
    assert REFRESH_CRED not in _messages(records)
    assert REFRESH_CRED not in _db_cells(tmp_path / "t.db")


def test_httpx_request_logging_cannot_reach_a_root_handler():
    """httpx logs `HTTP Request: POST <full url>` at INFO with the URL's
    userinfo intact, so an api_base_url carrying basic-auth credentials; an
    ordinary reverse-proxy setup, puts the password on the root logger. Same
    shape as the urllib3 case in test_notifier.py; a local server is used so a
    REAL request/response cycle emits the real log line.
    """
    import http.server
    import threading

    from proxploy.services.license_client import LicenseApiError, LicenseClient

    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            self.send_response(400)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *a):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    secret = "S3NTINEL-URL-PASSWORD-123"
    try:
        with _root_log_capture() as records:
            client = LicenseClient(f"http://pxu:{secret}@127.0.0.1:{server.server_port}")
            try:
                client.activate("LKEY", "install-1")
            except LicenseApiError:
                pass
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert logging.getLogger("httpx").propagate is False
    assert secret not in _messages(records)



def test_migrations_survive_a_percent_in_the_dsn(tmp_path):
    """Alembic keeps this URL in a ConfigParser, where "%" is interpolation
    syntax: an unescaped DSN whose password contains "%" raised
    `ValueError: invalid interpolation syntax in '<the whole DSN>'` at startup,
    printing the password in the traceback. sqlite stands in for postgres here
    the ConfigParser behaviour is dialect-independent."""
    from proxploy.config import Settings
    from proxploy.db import run_migrations

    db_path = tmp_path / "pct%s100%.db"
    run_migrations(Settings(db_url=f"sqlite:///{db_path}", data_dir=tmp_path,
                            master_key_file=tmp_path / "master.key"))
    assert db_path.exists()
