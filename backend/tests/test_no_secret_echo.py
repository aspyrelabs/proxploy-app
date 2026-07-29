"""Repo-wide 422 handler must never echo a secret-bearing request body back
to the caller (main.py::_no_echo_validation_errors).

Pydantic v2's "missing" error reports the whole parent body as `input` when
a sibling field is absent, so any route taking a secret alongside another
required field leaks that secret in the validation-error response unless the
handler strips `input`. Three routes take a secret in the body: ChannelIn.url,
HostIn.token_secret, LicenseIn.license_key.
"""
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
    around it — the realistic leak is a caller who typos the field name and
    the secret rides along as an unrecognized extra key in the same body."""
    from tests.support import make_app

    with TestClient(make_app(tmp_path)) as c:
        bootstrap_admin(c)
        r = c.post("/api/v1/entitlements/license", json={"key": LICENSE_SECRET},
                   headers=csrf_header(c))
        assert r.status_code == 422
        assert LICENSE_SECRET not in r.text
        assert "input" not in r.json()["detail"][0]


def test_problem_json_handler_for_http_exceptions_is_unaffected(tmp_path, csrf_header,
                                                                 bootstrap_admin):
    """The RequestValidationError handler is new and separate from the
    existing RFC 9457 problem+json handler for StarletteHTTPException —
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
