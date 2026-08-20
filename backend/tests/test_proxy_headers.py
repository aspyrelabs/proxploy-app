"""PXP-29: pin the reverse-proxy trust boundary in the deployed uvicorn
invocations, and prove the operator override actually changes which address
lands in the audit log.

Two things this guards against:
  (a) packaging drift: --proxy-headers silently dropped from the systemd unit
      or the container entrypoint, or --forwarded-allow-ips added there,
      which would beat the FORWARDED_ALLOW_IPS env var and kill the operator
      override this task exists to provide.
  (b) uvicorn's proxy_headers default flipping in a future release: pinning
      the flag on the command line makes the behaviour ours, not uvicorn's.
"""
from pathlib import Path

from starlette.testclient import TestClient
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

REPO_ROOT = Path(__file__).resolve().parents[2]


def _non_comment_lines(text):
    """Strips comment lines before searching for flags. The comments above
    these invocations legitimately name both --proxy-headers and
    --forwarded-allow-ips to explain the trust boundary, so searching the
    whole file text would pass even with a flag missing from the real
    invocation as long as a comment still mentions it."""
    return "\n".join(line for line in text.splitlines() if not line.strip().startswith("#"))


def test_systemd_unit_pins_proxy_headers():
    exec_start = _non_comment_lines(
        (REPO_ROOT / "packaging" / "proxploy.service").read_text())
    assert "--proxy-headers" in exec_start
    # A CLI value beats the FORWARDED_ALLOW_IPS env var, so hardcoding
    # --forwarded-allow-ips here would silently kill the operator override.
    assert "--forwarded-allow-ips" not in exec_start


def test_docker_entrypoint_pins_proxy_headers():
    exec_start = _non_comment_lines(
        (REPO_ROOT / "packaging" / "docker" / "entrypoint.sh").read_text())
    assert "--proxy-headers" in exec_start
    # Same reasoning as the systemd unit: leave the allow list to the env var.
    assert "--forwarded-allow-ips" not in exec_start


def test_uvicorn_invocations_disable_ws_per_message_deflate():
    """The VM console is a websocket relay, and uvicorn defaults
    ws_per_message_deflate to True, so without this flag every browser (they
    all offer permessage-deflate) gets the VNC stream re-compressed frame by
    frame on the event loop thread that also relays it.

    Measured against a throwaway uvicorn echo server, 64 KiB payloads: 2.20 ms
    per round trip with deflate on, 0.17 ms with it off. On the real console
    path a full 1280x800 repaint spent 257 ms in transfer with it on versus 93
    to 126 ms with it off. The bytes saved are near zero because noVNC asks for
    Tight, i.e. the payload is already JPEG/zlib compressed.

    Same "packaging drift" guard as the two --proxy-headers tests above: the
    flag only exists on these command lines, so a dropped flag is a silent 2x
    on every console and nothing else would notice.
    """
    for path in (REPO_ROOT / "packaging" / "proxploy.service",
                 REPO_ROOT / "packaging" / "docker" / "entrypoint.sh"):
        exec_start = _non_comment_lines(path.read_text())
        assert "--ws-per-message-deflate false" in exec_start, path


def _wrapped_app(tmp_path, trusted_hosts):
    """Same app the `client` fixture in conftest.py builds, wrapped in
    uvicorn's own ProxyHeadersMiddleware so scope["client"] gets rewritten
    from X-Forwarded-For exactly the way `uvicorn --proxy-headers` rewrites
    it in production, gated on the same trusted_hosts/FORWARDED_ALLOW_IPS
    story as packaging/proxploy.service.
    """
    from proxploy.config import Settings
    from proxploy.main import create_app

    s = Settings(
        db_url=f"sqlite:///{tmp_path}/proxploy.db",
        data_dir=tmp_path,
        master_key_file=tmp_path / "master.key",
    )
    app = create_app(s)
    return ProxyHeadersMiddleware(app, trusted_hosts=trusted_hosts)


def _failed_login_ip(tmp_path, peer, trusted_hosts):
    """Drives a failed login (no user needs to exist for it to write an
    audit row, per auth.py::login's `if not user` branch) through the
    wrapped app with the given peer address and an X-Forwarded-For header,
    and returns the ip the audit row ended up with."""
    from proxploy.api.auth import limiter
    from proxploy.models import AuditEvent

    limiter.reset()
    wrapped = _wrapped_app(tmp_path, trusted_hosts)
    with TestClient(wrapped, client=(peer, 12345)) as c:
        c.get("/api/v1/meta/health")
        csrf = {"X-CSRF-Token": c.cookies["pp_csrf"]}
        r = c.post("/api/v1/auth/login",
                   json={"email": "nobody@example.com", "password": "wrong"},
                   headers={**csrf, "X-Forwarded-For": "203.0.113.9"})
        assert r.status_code == 401

        # c.app is the ProxyHeadersMiddleware; c.app.app is the FastAPI
        # instance it wraps, same as conftest's `client` fixture reaches
        # state through client.app.state in test_auth.py.
        db = c.app.app.state.sessionmaker()
        row = db.query(AuditEvent).filter_by(action="auth.login", result="error").one()
        return row.ip


def test_audit_row_ip_follows_forwarded_for_when_peer_is_trusted(tmp_path):
    ip = _failed_login_ip(tmp_path, peer="127.0.0.1", trusted_hosts=["127.0.0.1"])
    assert ip == "203.0.113.9"


def test_audit_row_ip_keeps_peer_when_not_trusted(tmp_path):
    ip = _failed_login_ip(tmp_path, peer="10.0.0.5", trusted_hosts=["127.0.0.1"])
    assert ip == "10.0.0.5"
