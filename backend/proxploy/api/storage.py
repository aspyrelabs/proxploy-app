# backend/proxploy/api/storage.py
"""Storage routes (doc 05 §Storage, doc 01 §5).

Reads only, in this task. The LIST is served from the poller's in-memory
`HostSnapshot.storage` — doc 05 calls it a "live-refreshed cache", and since the
poll loop's single `cluster_resources()` already carries every field the page
needs, listing costs zero PVE calls. Detail and content are on-demand
passthroughs, one PVE call each, triggered by a human opening a datastore.
There is no storage table and none is added: doc 04 defines no storage entity.

Entitlements: doc 05 leaves the column blank on all three reads. Doc 01 §5
names `storage.view` (datastore overview) and `storage.content` (content
browser) as real features, and doc 07 §3 says a feature without a key does not
merge — so the reads are gated with their doc-01 keys rather than left ungated.
Functionally identical today (every flag defaults ON); recorded as a doc-05
amendment in the phase notes.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from proxploy.api.deps import get_db, require_entitlement, require_role
from proxploy.models import Host, User
from proxploy.services.hostclient import client_for_host
from proxploy.services.proxmox import ProxmoxError

router = APIRouter(prefix="/storage", tags=["storage"])

# Reused as BOTH the route-level dependency and the parameter-level one so
# FastAPI's dependency cache (keyed on the callable) collapses them into a
# single call that runs FIRST. A bare `dependencies=[Depends(require_entitlement(...))]`
# lands at position 0 and runs BEFORE auth, answering an anonymous caller with
# 403 instead of 401 — see tests/test_route_auth_invariant.py.
_require_viewer = require_role("viewer")


def _pct(used: float, total: float) -> float:
    return round(used / total * 100, 1) if total else 0.0


def _content_list(v) -> list[str]:
    """Snapshot rows already hold a list; `storage_status()` returns PVE's raw
    comma string ("iso,vztmpl,backup"). Accept either."""
    if isinstance(v, list):
        return v
    return [c for c in str(v or "").split(",") if c]


def _row(host: Host, st: dict) -> dict:
    used, total = int(st.get("used_bytes") or 0), int(st.get("total_bytes") or 0)
    return {"host_id": host.id, "host_name": host.name, "node": st.get("node"),
            "storage": st.get("storage"), "type": st.get("type"),
            "content": _content_list(st.get("content")),
            "shared": bool(st.get("shared")),
            "status": st.get("status") or "unknown",
            "used_bytes": used, "total_bytes": total,
            "used_pct": _pct(used, total)}


def _host_or_404(db, host_id: int) -> Host:
    host = db.get(Host, host_id)
    if host is None:
        raise HTTPException(404, "host not found")
    return host


def _nodes_with(request: Request, host_id: int, name: str) -> list[str]:
    snap = request.app.state.poller.snapshots.get(host_id)
    if snap is None:
        return []
    return sorted({st["node"] for st in snap.storage
                   if st.get("storage") == name and st.get("node")})


def _resolve_node(request: Request, host: Host, name: str, node: str | None) -> str:
    """Every per-datastore PVE path is node-scoped, but the UI addresses a
    datastore by (host, name). Explicit ?node= wins; otherwise take the first
    node the last poll saw serving it, then the host's own node."""
    if node:
        return node
    found = _nodes_with(request, host.id, name)
    if found:
        return found[0]
    if host.node_name:
        return host.node_name
    raise HTTPException(409, f"cannot tell which node serves {name!r} on "
                             f"{host.name} — pass ?node=")


@router.get("", dependencies=[Depends(_require_viewer),
                              Depends(require_entitlement("storage.view"))])
def list_storage(request: Request, db=Depends(get_db),
                 user: User = Depends(_require_viewer)):
    snaps = request.app.state.poller.snapshots
    hosts = {h.id: h for h in db.query(Host).all()}
    seen: dict[tuple, dict] = {}
    for host_id, snap in snaps.items():
        host = hosts.get(host_id)
        if host is None:
            continue  # host deleted between poll and request
        for st in snap.storage:
            # A shared datastore is reported once per node and is ONE
            # datastore; a local one with the same name on two nodes is two.
            key = ((host_id, st.get("storage")) if st.get("shared")
                   else (host_id, st.get("node"), st.get("storage")))
            seen.setdefault(key, _row(host, st))
    return sorted(seen.values(),
                  key=lambda r: (r["host_id"], r["storage"] or "", r["node"] or ""))


@router.get("/{host_id}/{name}",
            dependencies=[Depends(_require_viewer),
                          Depends(require_entitlement("storage.view"))])
def storage_detail(request: Request, host_id: int, name: str,
                   node: str | None = None, db=Depends(get_db),
                   user: User = Depends(_require_viewer)):
    host = _host_or_404(db, host_id)
    node = _resolve_node(request, host, name, node)
    try:
        st = client_for_host(request.app, db, host).storage_status(node, name)
    except ProxmoxError as e:
        raise HTTPException(502, str(e))
    used, total = int(st.get("used") or 0), int(st.get("total") or 0)
    return {"host_id": host.id, "host_name": host.name, "node": node,
            "storage": name, "type": st.get("type"),
            "content": _content_list(st.get("content")),
            "shared": bool(st.get("shared")),
            "status": "available" if st.get("active") else "inactive",
            "used_bytes": used, "total_bytes": total,
            "avail_bytes": int(st.get("avail") or 0),
            "used_pct": _pct(used, total),
            "nodes": _nodes_with(request, host_id, name) or [node]}


@router.get("/{host_id}/{name}/content",
            dependencies=[Depends(_require_viewer),
                          Depends(require_entitlement("storage.content"))])
def storage_content(request: Request, host_id: int, name: str,
                    node: str | None = None, content: str | None = None,
                    db=Depends(get_db), user: User = Depends(_require_viewer)):
    host = _host_or_404(db, host_id)
    node = _resolve_node(request, host, name, node)
    try:
        rows = client_for_host(request.app, db, host).storage_content(node, name, content)
    except ProxmoxError as e:
        raise HTTPException(502, str(e))
    # `content` already rides to PVE as a server-side filter (proxmox.py); this
    # re-applies it client-side so the response is correct even against a PVE
    # (or fake) that ignores the filter param and returns everything.
    return [{"volid": r.get("volid"), "format": r.get("format"),
             "size": int(r.get("size") or 0), "used": int(r.get("used") or 0),
             "vmid": r.get("vmid"), "ctime": r.get("ctime"),
             "content": r.get("content"), "notes": r.get("notes"),
             "verification": r.get("verification")}
            for r in rows if not content or r.get("content") == content]
