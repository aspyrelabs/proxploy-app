"""Doc 10 Phase 8: '/api/docs covers everything the UI does'. Mechanical
audit: every path the frontend hands to api() must resolve to a documented
route. Template params (`${x}`) match any {param} segment. SSE/WebSocket
URLs are consumed by EventSource/WebSocket constructors, not api(), so this
regex covering api() calls covers exactly the REST surface — which is the
claim being audited."""
import re
from pathlib import Path

from fastapi.testclient import TestClient

from tests.support import make_app

FRONTEND_SRC = Path(__file__).resolve().parents[2] / "frontend" / "src"
CALL_RE = re.compile(r"""api(?:<[^>(]*>)?\(\s*[`'"](/[^`'"?\s]*)""")


def _normalise(path: str) -> tuple:
    return tuple("{}" if seg.startswith("${") else seg
                 for seg in path.split("/") if seg)


# The line-regex extractor above is text-based, not a JS/TS parser: it can't
# resolve a path whose FIRST segment is itself a computed expression (a
# ternary, a function call) rather than a literal prefixed with `${` at a
# segment boundary — the capture cuts off at the first quote/`?`/whitespace
# inside that expression. Three call sites in the frontend do this; each is
# checked by hand below against every route it can actually produce at
# runtime, rather than silently allowlisted. If a documented route the
# resolved set expects goes away, this test still catches it.
KNOWN_DYNAMIC = {
    # api/storage.ts:71 — `/storage/${hostId}/${name}/content${qs ? `?${qs}` : ''}`
    # the regex stops at the un-terminated `${qs ...}` and swallows it whole.
    ("storage", "{}", "{}", "content${qs"): (
        ("storage", "{}", "{}", "content"),),
    # api/network.ts:104 — `` `/${v.guestType === 'app' ? 'apps' : 'vms'}/${v.guestId}/network/${v.iface}` ``
    # the regex stops at the space before `===`, capturing only `/${v.guestType`.
    ("{}",): (
        ("apps", "{}", "network", "{}"), ("vms", "{}", "network", "{}")),
    # api/jobs.ts:92 — `` `/${key(v.target)}/${v.id}/${v.action}` ``
    # `key(v.target)` is a function call, not a literal-prefixed template slot.
    ("{}", "{}", "{}"): (
        ("apps", "{}", "{}"), ("vms", "{}", "{}")),
}


def test_every_frontend_api_call_is_a_documented_route(tmp_path):
    app = make_app(tmp_path)
    documented = set()
    for path in app.openapi()["paths"]:
        assert path.startswith("/api/v1")
        documented.add(tuple("{}" if s.startswith("{") else s
                             for s in path.removeprefix("/api/v1").split("/") if s))
    calls = {}
    for f in FRONTEND_SRC.rglob("*.ts*"):
        for m in CALL_RE.finditer(f.read_text()):
            calls.setdefault(_normalise(m.group(1)), []).append(
                (f.relative_to(FRONTEND_SRC), m.group(1)))
    missing = {k: v for k, v in calls.items() if k not in documented}

    for key, resolved in KNOWN_DYNAMIC.items():
        if key in missing:
            assert all(r in documented for r in resolved), (
                f"{key} was expected to resolve to {resolved}, but one of "
                f"those routes is no longer documented")
            del missing[key]

    assert calls, "regex matched nothing — the extractor itself broke"
    assert not missing, f"UI calls without a documented route: {missing}"


def test_docs_and_openapi_json_serve_200(tmp_path):
    app = make_app(tmp_path)
    with TestClient(app) as c:
        assert c.get("/api/docs").status_code == 200
        assert c.get("/api/openapi.json").status_code == 200
