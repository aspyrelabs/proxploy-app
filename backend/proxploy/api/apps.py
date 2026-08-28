"""Apps read and lifecycle endpoints. Identity is ours; state is cache."""
from __future__ import annotations

import difflib
import hashlib
import shlex

from fastapi import (APIRouter, Body, Depends, File, HTTPException, Request,
                     UploadFile)
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.exc import IntegrityError

from proxploy.api import firewall as fwapi
from proxploy.api.deps import (authorize, cluster_scope, get_db,
                               require_entitlement, scope_app)
from proxploy.api.firewall import (AliasIn, AliasPatch, IpSetIn, MemberIn,
                                   MemberPatch, MoveIn, ObjectName,
                                   OptionsIn, RuleIn, RulePatch, RulePos)
from proxploy.api.jobs import enqueue_and_audit, job_out
from proxploy.api.network import NicIn, guest_nics, set_guest_nic
from proxploy.models import App, AppScript, CatalogEntry, Host, User, to_iso, utcnow
from proxploy.services import migrate as migrate_service
from proxploy.executor import SSHExecutor
from proxploy.services import app_icons
from proxploy.services.app_identity import monogram, pick_colors, valid_colors
from proxploy.services.audit import write_audit
from proxploy.services.catalog import pinned_payload_script
from proxploy.services.catalog_icons import served_icon_url
from proxploy.services.hostclient import client_for_host
from proxploy.services.lifecycle import APP_ACTIONS, busy_guests, job_kind
from proxploy.services.portdetect import detect_command, rank_ports
from proxploy.services.proxmox import ProxmoxError
from proxploy.services.selfguard import DESTRUCTIVE, is_self
from proxploy.services.webui import installed_parts, scheme_for

router = APIRouter(prefix="/apps", tags=["apps"])

# Reused as BOTH the route-level and the parameter-level dependency so
# FastAPI's dependency cache collapses repeated uses into one call per
# request, and so authorize() runs before require_entitlement: an anonymous
# caller must get 401, never a leaky 403. No-id routes use the unscoped
# singleton; id-carrying routes use the scope_app()-scoped one.
_read = authorize("app", "read")
_read_scoped = authorize("app", "read", scope_of=scope_app())
_lifecycle = authorize("app", "lifecycle", scope_of=scope_app())
_configure = authorize("app", "configure", scope_of=scope_app())
_update = authorize("app", "update")
_update_scoped = authorize("app", "update", scope_of=scope_app())
_script_read = authorize("app", "script_read", scope_of=scope_app())
_script = authorize("app", "script", scope_of=scope_app())
_adopt = authorize("app", "adopt")
_migrate = authorize("app", "migrate", scope_of=scope_app())
_remove = authorize("app", "remove", scope_of=scope_app())
_fw_read = authorize("firewall", "read", scope_of=scope_app())
_fw_guest = authorize("firewall", "guest", scope_of=scope_app())


def _app_out(a: App, host: Host, snapshots, entry: CatalogEntry | None,
             busy: dict[tuple[str, int], str] | None = None,
             data_dir=None) -> dict:
    """`entry` is the catalog row this app was installed from, or None when it
    has no catalog slug or that slug no longer resolves. Deliberately required
    with no default: it is only used for the icon, and a default of None would
    let a future caller silently serve every app without one.

    `busy` maps a guest to what it should READ as while a job acts on it."""
    busy = busy or {}
    snap = snapshots.get(a.host_id)
    g = snap.guests.get(("lxc", a.ctid)) if snap else None
    return {
        "id": a.id, "name": a.name, "slug": a.slug,
        "host_id": a.host_id, "host_name": host.name, "node": host.node_name,
        "ctid": a.ctid, "category": a.category, "catalog_slug": a.catalog_slug,
        "icon_initials": a.icon_initials, "icon_colors": a.icon_colors,
        # The Store entry's icon, resolved through the Store's own pipeline
        # rather than copied onto the app row, where it would go stale the next
        # time upstream rebrands or the catalog refreshes. Null is normal and
        # is NOT an error: no catalog slug, a dropped slug, or an entry with no
        # logo all land here and all fall back to the icon_initials tile.
        # An uploaded icon wins over the catalog's. The operator chose it
        # for this specific app, which is a stronger statement than the slug
        # this app happens to be matched to; and for an app with no slug at
        # all it is the only real icon available.
        "icon_url": (app_icons.custom_icon_url(data_dir, a.id) if data_dir else None)
                    or served_icon_url(entry),
        "web_port": a.web_port, "web_protocol": a.web_protocol,
        "web_path": a.web_path,
        # Read-only, and shown so the operator can see what the install script
        # said before deciding whether the three fields above need correcting.
        "installed_url": a.installed_url,
        # "Open web UI" target port: the catalog's own port, resolved through
        # `entry` like the icon above, never stored on the app row. No entry or
        # no port on it means no button, so None here hides the action.
        "catalog_port": entry.port if entry else None,
        # "pending" while an action is in flight, whatever the cached column
        # says. Proxmox reports the OLD status for as long as a stop or removal
        # is actually running, so answering with it put the pill back to
        # Running mid-action on every refetch. The browser's optimistic patch
        # cannot cover this: it only exists in the tab that clicked.
        "status": busy.get(("app", a.id)) or a.status_cached or "unknown",
        "ip": a.ip_cached,
        "cpu_pct": a.cpu_pct_cached, "mem_bytes": a.mem_bytes_cached,
        "mem_total_bytes": g["mem_total_bytes"] if g else None,
        # Network is two rates with no denominator: there is no link speed to
        # divide by. The raw netin/netout counters stay on the row, they only
        # mean something next to the previous reading.
        "disk_bytes": a.disk_bytes_cached,
        "disk_total_bytes": a.disk_total_bytes_cached,
        "net_in_bps": a.net_in_bps_cached,
        "net_out_bps": a.net_out_bps_cached,
        "uptime_s": a.uptime_s_cached,
        "update_available": a.update_available, "adopted": a.adopted,
    }


@router.get("")
def list_apps(request: Request, host: int | None = None, q: str | None = None,
              status: str | None = None, db=Depends(get_db),
              user: User = Depends(_read)):
    hosts = {h.id: h for h in db.query(Host).all()}
    query = db.query(App)
    if host is not None:
        query = query.filter(App.host_id == host)
    rows = []
    for a in query.order_by(App.name).all():
        if q and q.lower() not in f"{a.name} {a.slug}".lower():
            continue
        if status and (a.status_cached or "unknown") != status:
            continue
        if a.host_id in hosts:
            rows.append(a)
    # One query for the whole page rather than one per card; the icon is all
    # any of them wants from that table.
    slugs = {a.catalog_slug for a in rows if a.catalog_slug}
    entries = {e.slug: e for e in db.query(CatalogEntry)
               .filter(CatalogEntry.slug.in_(slugs))} if slugs else {}
    busy = busy_guests(db, utcnow())
    data_dir = request.app.state.settings.data_dir
    return [_app_out(a, hosts[a.host_id], request.app.state.poller.snapshots,
                     entries.get(a.catalog_slug), busy, data_dir)
            for a in rows]


@router.get("/discovered")
def discovered(request: Request, db=Depends(get_db),
               user: User = Depends(_read)):
    """Pre-existing CTs not yet adopted.

    Two Hosts can be two nodes of the SAME cluster, and cluster_resources()
    returns the whole cluster from either one, so every host's snapshot lists
    the same unadopted CT. Deduped by (cluster, ctid): a ctid is unique only
    WITHIN a cluster, so two clusters can legitimately both have a CT 101 and
    both must be offered, attributed to the Host registered at that CT's own
    `node` rather than whichever host polled it. An App's poll cycle only
    checks its own host_id, so a CT adopted on one host still shows as
    discovered in another host's snapshot of the same cluster; checking every
    App row here, scoped the same way, stops it being offered twice.
    """
    hosts = {h.id: h for h in db.query(Host).all()}
    by_node = {(cluster_scope(h), h.node_name): h
               for h in hosts.values() if h.node_name}
    tracked: dict[tuple, set[int]] = {}
    for a in db.query(App).all():
        h = hosts.get(a.host_id)
        if h is not None:
            tracked.setdefault(cluster_scope(h), set()).add(a.ctid)
    seen: dict[tuple, dict] = {}
    for host_id, snap in sorted(request.app.state.poller.snapshots.items()):
        h = hosts.get(host_id)
        if h is None:
            continue
        scope = cluster_scope(h)
        for d in snap.discovered:
            key = (scope, d["ctid"])
            if d["ctid"] in tracked.get(scope, ()) or key in seen:
                continue
            owner = by_node.get((scope, d.get("node")), h)
            seen[key] = {"host_id": owner.id, "host_name": owner.name, **d}
    return sorted(seen.values(), key=lambda r: (r["ctid"], r["host_id"]))


class AdoptItem(BaseModel):
    host_id: int
    ctid: int
    name: str
    catalog_slug: str | None = None


class AdoptIn(BaseModel):
    items: list[AdoptItem]


class UpdateIn(BaseModel):
    consent: bool = False


@router.post("/adopt", dependencies=[Depends(_adopt),
                                     Depends(require_entitlement("apps.adopt"))])
def adopt_apps(body: AdoptIn, request: Request, db=Depends(get_db),
               user: User = Depends(_adopt)):
    """Bulk-adopt pre-existing/discovered CTs as tracked apps.

    One commit for the whole batch: a mid-batch ux_apps_host_ctid conflict
    rolls back everything flushed so far, so nothing partially lands, and one
    audit row covers the batch.

    An adopted app takes its category and web port from the catalog entry its
    slug names, like install does. Without them the grid has no group to file
    the app under and nothing knows which port its web UI answers on. AdoptIn
    carries neither field, so no caller value is overwritten, and an absent or
    unrecognised slug adopts exactly as before.
    """
    slugs = {i.catalog_slug for i in body.items if i.catalog_slug}
    entries = {e.slug: e for e in db.query(CatalogEntry)
               .filter(CatalogEntry.slug.in_(slugs))} if slugs else {}
    adopted = []
    for item in body.items:
        slug = f"{item.catalog_slug or 'adopted'}-{item.host_id}-{item.ctid}"
        entry = entries.get(item.catalog_slug)
        row = App(host_id=item.host_id, ctid=item.ctid, name=item.name, slug=slug,
                  # No web_protocol, same reason as install: left NULL so the
                  # app is asked which scheme it speaks rather than told.
                  catalog_slug=item.catalog_slug, web_path="/",
                  category=entry.category if entry else None,
                  web_port=entry.port if entry else None,
                  # The tile this app wears until it is given a logo. Assigned
                  # HERE rather than left to the frontend so the colour is
                  # stable: a name-derived colour would change under a rename,
                  # and a render-time random one would change on every reload.
                  icon_initials=monogram(item.name),
                  icon_colors=pick_colors(),
                  adopted=True)
        db.add(row)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, f"CT {item.ctid} on host {item.host_id} is already adopted")
        adopted.append(row.id)
    db.commit()
    # One audit row covers the whole batch, so there is no single target to
    # point at. The names make the row answerable without opening the params
    # blob, which the audit screen never shows. Capped at five: a forty-name
    # string pushes every other column off the screen, and `app_ids` still
    # holds the full set.
    names = [i.name or f"CT {i.ctid}" for i in body.items]
    listed = ", ".join(names[:5])
    if len(names) > 5:
        listed += f" and {len(names) - 5} more"
    write_audit(db, actor_type="user", actor_id=user.id, action="apps.adopt",
                target_name=listed,
                params={"count": len(adopted), "app_ids": adopted},
                ip=request.client.host if request.client else None)
    return {"adopted": adopted}


# Literal segment, registered ahead of `GET /{app_id}` and the lifecycle
# wildcard: `{app_id}` would otherwise try to parse "update-all" as an int
# and 422.
@router.post("/update-all", status_code=202,
             dependencies=[Depends(_update),
                          Depends(require_entitlement("store.update_all"))])
def update_all_apps(body: UpdateIn, request: Request, db=Depends(get_db),
                    user: User = Depends(_update)):
    """One `app.update` job per stale app.

    No new queue machinery: JobBackend.MAX_CONCURRENT already runs four at a
    time and queues the rest, and each job carries its own status, transcript
    and result.

    `skipped` is not decoration: a bare "0 jobs started" is indistinguishable
    from a broken endpoint, so every app that got no job says why.

    Mirrors POST /{app_id}/update's skip order exactly, so bulk and single-app
    runs never disagree about why an app was skipped:

    1. Edited script first: an edited row's `upstream_ref` is NULL, so checking
       "no pinned script" first would misreport it as having no upstream at
       all, and enqueueing anyway would spray a guaranteed-`JobFailed` job.
    2. No catalog entry / no upstream_sha / no pinned script.
    3. Already on the catalog's current commit.
    """
    if not body.consent:
        raise HTTPException(400, "root-consent required: this runs community "
                                 "scripts as root on your nodes")
    jobs, skipped = [], []
    for a in db.query(App).order_by(App.id).all():
        _, entry, latest = _update_state(db, a.id)
        if latest is not None and latest.source == "edited":
            skipped.append({
                "app_id": a.id, "name": a.name,
                "reason": (f"{a.name}'s saved script was edited locally; "
                          f"updating would discard those edits. POST "
                          f"/api/v1/apps/{a.id}/script/revert restores the "
                          f"upstream script."),
            })
            continue
        from_ref = latest.upstream_ref if latest else None
        if entry is None or not entry.upstream_sha or from_ref is None:
            skipped.append({
                "app_id": a.id, "name": a.name,
                "reason": "no upstream script is pinned for this app; "
                         "refresh the catalog first",
            })
            continue
        if from_ref == entry.upstream_sha:
            skipped.append({"app_id": a.id, "name": a.name,
                            "reason": f"{a.name} is already up to date"})
            continue
        jobs.append(enqueue_and_audit(request, db, user, kind="app.update",
                                      target_type="app", target_id=a.id,
                                      params={"app_id": a.id})["job"])
    return {"jobs": jobs, "skipped": skipped}


@router.get("/{app_id}")
def app_detail(request: Request, app_id: int, db=Depends(get_db),
               user: User = Depends(_read_scoped)):
    a = db.get(App, app_id)
    if a is None:
        raise HTTPException(404, "app not found")
    host = db.get(Host, a.host_id)
    entry = (db.query(CatalogEntry).filter_by(slug=a.catalog_slug).one_or_none()
             if a.catalog_slug else None)
    return _app_out(a, host, request.app.state.poller.snapshots, entry,
                    busy_guests(db, utcnow()),
                    request.app.state.settings.data_dir)


LOG_LINES = 300

# systemd containers answer with journalctl; an Alpine one has no journal and
# logs to /var/log/messages through busybox syslogd. Asked in that order, with
# a sentence rather than silence for a container that keeps neither.
LOG_COMMAND = (
    f"if command -v journalctl >/dev/null 2>&1; then "
    f"journalctl --no-pager --no-hostname -n {LOG_LINES}; "
    f"elif [ -f /var/log/messages ]; then tail -n {LOG_LINES} /var/log/messages; "
    f"elif [ -f /var/log/syslog ]; then tail -n {LOG_LINES} /var/log/syslog; "
    f"else echo 'this container keeps no journal and no syslog'; fi"
)


@router.get("/{app_id}/logs", dependencies=[Depends(_read)])
async def app_logs(app_id: int, request: Request, db=Depends(get_db),
                   user: User = Depends(_read_scoped)):
    """The container's own log tail, read the way detect_ports reads its
    sockets: `pct exec` over the host's SSH, because the answer only exists
    inside the guest and no PVE API route exposes it."""
    a = db.get(App, app_id)
    if a is None:
        raise HTTPException(404, "app not found")
    host = db.get(Host, a.host_id)
    if host is None:
        raise HTTPException(404, "host not found")
    executor = SSHExecutor(connect_factory=request.app.state.ssh_connect_factory)
    lines: list[dict] = []

    def on_new_fingerprint(fp: str) -> None:
        with request.app.state.sessionmaker() as fdb:
            h = fdb.get(Host, a.host_id)
            if h is not None:
                h.ssh_host_key_fingerprint = fp
                fdb.commit()

    command = f"pct exec {int(a.ctid)} -- sh -c {shlex.quote(LOG_COMMAND)}"
    try:
        status = await executor.run_for_host(
            request.app.state.sessionmaker, request.app.state.secretstore,
            a.host_id, host.address, command,
            pinned_fingerprint=host.ssh_host_key_fingerprint,
            on_new_fingerprint=on_new_fingerprint,
            on_line=lambda stream, line: lines.append(
                {"stream": stream, "message": line}),
            timeout_s=request.app.state.settings.pve_task_timeout_s)
    except LookupError as e:
        raise HTTPException(409, f"reading a container's logs needs SSH access to "
                                 f"{host.name}, which is not set up: {e}") from e
    if status != 0 and not lines:
        raise HTTPException(502, f"could not read {a.name}'s logs (exit {status}). "
                                 f"The container may be stopped.")
    return lines


@router.get("/{app_id}/ports", dependencies=[Depends(_read)])
async def detect_ports(app_id: int, request: Request, db=Depends(get_db),
                       user: User = Depends(_read_scoped)):
    """What this container is listening on, ranked, as a GUESS.

    For a hand-adopted app the catalog knows nothing, so `web_port` is empty,
    and Proxmox cannot answer either: `pct config` describes the NIC and no API
    route exposes sockets. The only place the answer exists is inside the
    container.

    A GET that runs a command, unusual and deliberate: it changes nothing and
    never writes web_port. The caller picks from the candidates, because a
    container can serve two UIs and this ranking is a heuristic, not a fact.
    `accurate: false` is in the response so a client cannot present it as one.

    User-triggered only, never the poller: one command per guest is exactly
    what the O(nodes) poll budget forbids.
    """
    a = db.get(App, app_id)
    if a is None:
        raise HTTPException(404, "app not found")
    host = db.get(Host, a.host_id)
    if host is None:
        raise HTTPException(404, "host not found")
    executor = SSHExecutor(connect_factory=request.app.state.ssh_connect_factory)
    lines: list[str] = []

    def on_new_fingerprint(fp: str) -> None:
        with request.app.state.sessionmaker() as fdb:
            h = fdb.get(Host, a.host_id)
            if h is not None:
                h.ssh_host_key_fingerprint = fp
                fdb.commit()

    try:
        status = await executor.run_for_host(
            request.app.state.sessionmaker, request.app.state.secretstore,
            a.host_id, host.address, detect_command(a.ctid),
            pinned_fingerprint=host.ssh_host_key_fingerprint,
            on_new_fingerprint=on_new_fingerprint,
            on_line=lambda stream, line: lines.append(line) if stream == "stdout" else None,
            timeout_s=request.app.state.settings.pve_task_timeout_s)
    except LookupError as e:
        # executor/keys.py raises this when the host carries no ssh_key. A 409
        # naming the missing thing, matching how a missing API token reads.
        raise HTTPException(409, f"looking inside a container needs SSH access to "
                                 f"{host.name}, which is not set up: {e}") from e
    if status != 0:
        raise HTTPException(502, f"could not read the container's listening ports "
                                 f"(exit {status}). It may be stopped.")
    return {"ports": rank_ports("\n".join(lines)),
            "accurate": False}


def _diff_vs_upstream(db, app_row: App, pinned_content: str) -> str | None:
    """Diff the pinned app_scripts row against the *current*
    catalog_entries.raw.install_script for this app's slug, not just against
    the app's own prior version: a catalog refresh can move upstream forward
    with the pinned content untouched, and that drift has to surface too."""
    if not app_row.catalog_slug:
        return None
    entry = db.query(CatalogEntry).filter_by(slug=app_row.catalog_slug).one_or_none()
    if entry is None or not entry.raw:
        return None
    upstream = pinned_payload_script(entry)
    if upstream is None or upstream == pinned_content:
        return None
    diff = difflib.unified_diff(
        upstream.splitlines(keepends=True), pinned_content.splitlines(keepends=True),
        fromfile="upstream", tofile="pinned")
    return "".join(diff)


# Registered BEFORE the lifecycle wildcard further down: Starlette matches
# path templates in registration order, and `/{app_id}/{action}` would
# otherwise swallow these.
@router.get("/{app_id}/script", dependencies=[Depends(_script_read),
                                              Depends(require_entitlement("apps.script_edit"))])
def get_app_script(app_id: int, db=Depends(get_db)):
    latest = (db.query(AppScript).filter_by(app_id=app_id)
             .order_by(AppScript.version.desc()).first())
    if latest is None:
        raise HTTPException(404, "no pinned script for this app")
    app_row = db.get(App, app_id)
    return {"version": latest.version, "content": latest.content, "source": latest.source,
           "diff_vs_upstream": _diff_vs_upstream(db, app_row, latest.content)}


class ScriptIn(BaseModel):
    content: str


@router.put("/{app_id}/script", dependencies=[Depends(_script),
                                              Depends(require_entitlement("apps.script_edit"))])
def put_app_script(app_id: int, body: ScriptIn, request: Request, db=Depends(get_db),
                   user: User = Depends(_script)):
    # Validate before writing, like every sibling route here: an unknown
    # app_id otherwise 500s on the AppScript FK violation at commit time.
    if db.get(App, app_id) is None:
        raise HTTPException(404, "app not found")
    content = body.content
    latest = (db.query(AppScript).filter_by(app_id=app_id)
             .order_by(AppScript.version.desc()).first())
    next_version = (latest.version + 1) if latest else 1
    row = AppScript(app_id=app_id, version=next_version, content=content,
                    content_sha256=hashlib.sha256(content.encode()).hexdigest(),
                    source="edited", created_by=user.id)
    db.add(row)
    db.commit()
    write_audit(db, actor_type="user", actor_id=user.id, action="apps.script_edit",
                target_type="app", target_id=app_id, params={"version": row.version},
                ip=request.client.host if request.client else None)
    return {"version": row.version, "content": row.content, "source": row.source}


@router.get("/{app_id}/script/versions",
            dependencies=[Depends(_script_read),
                         Depends(require_entitlement("apps.script_edit"))])
def list_app_script_versions(app_id: int, db=Depends(get_db)):
    rows = (db.query(AppScript).filter_by(app_id=app_id)
           .order_by(AppScript.version.desc()).all())
    return [{"version": r.version, "source": r.source, "created_at": to_iso(r.created_at)}
           for r in rows]


@router.post("/{app_id}/script/revert",
             dependencies=[Depends(_script),
                          Depends(require_entitlement("apps.script_edit"))])
def revert_app_script(app_id: int, request: Request, db=Depends(get_db),
                      user: User = Depends(_script)):
    """Pin a NEW version to the catalog's CURRENT install_script, sourced
    "upstream", so pinned_ref reads the catalog sha again.

    Without this an app is stuck: put_app_script always writes
    `source="edited"` and only the install/update handlers ever write
    "upstream", so once a script is edited _resolve_update's guard blocks
    `app.update` forever, even if the operator pastes the exact upstream text
    back.

    Never mutates the edited row: the version history is the record.
    """
    a = db.get(App, app_id)
    if a is None:
        raise HTTPException(404, "app not found")
    if not a.catalog_slug:
        raise HTTPException(409, f"{a.name} was adopted, not installed from the "
                                 f"catalog; there is no upstream script to revert to")
    entry = db.query(CatalogEntry).filter_by(slug=a.catalog_slug).one_or_none()
    if entry is None:
        raise HTTPException(409, f"catalog entry {a.catalog_slug} not found; "
                                 f"refresh the catalog first")
    if not entry.upstream_sha:
        raise HTTPException(409, f"{a.catalog_slug} has no pinned upstream commit; "
                                 f"refresh the catalog before reverting")
    content = pinned_payload_script(entry)
    if not content:
        raise HTTPException(409, f"{a.catalog_slug}'s catalog entry has no "
                                 f"pinned script to revert to")
    latest = (db.query(AppScript).filter_by(app_id=app_id)
             .order_by(AppScript.version.desc()).first())
    next_version = (latest.version + 1) if latest else 1
    row = AppScript(app_id=app_id, version=next_version, content=content,
                    content_sha256=hashlib.sha256(content.encode()).hexdigest(),
                    source="upstream", upstream_ref=entry.upstream_sha,
                    created_by=user.id)
    db.add(row)
    # Pins to the catalog's CURRENT sha, so nothing is pending afterwards:
    # mirrors run_update's own reset rather than reporting an update against a
    # script just reverted TO that commit. A single-row assignment, not
    # mark_updates_available(db), which recomputes the whole table.
    a.update_available = None
    db.commit()
    write_audit(db, actor_type="user", actor_id=user.id, action="apps.script_revert",
                target_type="app", target_id=app_id, params={"version": row.version},
                ip=request.client.host if request.client else None)
    return {"version": row.version, "content": row.content, "source": row.source}


def _update_state(db, app_id: int) -> tuple[App, CatalogEntry | None, AppScript | None]:
    """The app, its catalog entry (if any), and its NEWEST AppScript row: the
    single query both GET and POST /update need. Returning the row itself, not
    just `.upstream_ref`, lets both callers see `.source` too, because
    `put_app_script` leaves `upstream_ref` NULL on an edited row and that NULL
    alone cannot tell "edited" from "no script pinned at all".
    """
    a = db.get(App, app_id)
    if a is None:
        raise HTTPException(404, "app not found")
    entry = (db.query(CatalogEntry).filter_by(slug=a.catalog_slug).one_or_none()
             if a.catalog_slug else None)
    latest = (db.query(AppScript).filter_by(app_id=app_id)
              .order_by(AppScript.version.desc()).first())
    return a, entry, latest


@router.get("/{app_id}/update",
            dependencies=[Depends(_update_scoped),
                          Depends(require_entitlement("store.updates"))])
def get_app_update(app_id: int, db=Depends(get_db)):
    """What an update would do: which commit to which, and the script diff.

    The diff is the SAME `_diff_vs_upstream` the Config tab renders, so the two
    can never disagree about what is about to run.

    Unlike GET /script, which always shows drift, this surfaces a diff only
    when there is an update TO show: the honest answer to "what would POST do"
    when the app is already on the catalog's commit is "nothing", not a diff
    sourced from unrelated content drift.

    An edited newest script reports no update at all, never a diff: POST
    refuses it regardless of catalog state, so a diff here would advertise an
    action POST is about to reject.
    """
    a, entry, latest = _update_state(db, app_id)
    to_ref = entry.upstream_sha if entry else None
    script_source = latest.source if latest else None
    if script_source == "edited":
        return {"update_available": None, "from_ref": None, "to_ref": to_ref,
                "diff_vs_upstream": None, "script_source": script_source}
    from_ref = latest.upstream_ref if latest else None
    diff = (_diff_vs_upstream(db, a, latest.content)
            if latest and to_ref is not None and from_ref != to_ref else None)
    return {
        "update_available": a.update_available,
        "from_ref": from_ref,
        "to_ref": to_ref,
        "diff_vs_upstream": diff,
        "script_source": script_source,
    }


@router.post("/{app_id}/update", status_code=202,
             dependencies=[Depends(_update_scoped),
                           Depends(require_entitlement("store.update"))])
def update_app(app_id: int, body: UpdateIn, request: Request, db=Depends(get_db),
               user: User = Depends(_update_scoped)):
    """Root-consent gated, exactly like install: this re-runs a community
    script as root on the node, so the operator has to say so out loud. Unlike
    install, which is admin-only, this is granted to operator: a lower bar,
    deliberately accepted."""
    if not body.consent:
        raise HTTPException(400, "root-consent required: this runs a community "
                                 "script as root on the node")
    a, entry, latest = _update_state(db, app_id)
    if latest is not None and latest.source == "edited":
        # Distinct from the "nothing pinned" 409 below: refreshing the catalog
        # does nothing for an edited app, so don't tell the operator to do it.
        raise HTTPException(409, f"{a.name}'s saved script was edited locally; "
                                 f"updating would replace it with the upstream "
                                 f"script and discard those edits. POST "
                                 f"/api/v1/apps/{app_id}/script/revert will "
                                 f"restore the upstream script if you want to "
                                 f"proceed with the update.")
    from_ref = latest.upstream_ref if latest else None
    if entry is None or not entry.upstream_sha or from_ref is None:
        raise HTTPException(409, "no upstream script is pinned for this app; "
                                 "refresh the catalog first")
    if from_ref == entry.upstream_sha:
        raise HTTPException(409, f"{a.name} is already up to date")
    return enqueue_and_audit(request, db, user, kind="app.update",
                             target_type="app", target_id=app_id,
                             params={"app_id": app_id})


def _app_and_host(db, app_id: int):
    a = db.get(App, app_id)
    if a is None:
        raise HTTPException(404, "app not found")
    host = db.get(Host, a.host_id)
    if host is None:
        raise HTTPException(404, "host not found")
    return a, host


# Above the lifecycle wildcard, per that route's own WARNING further down.
@router.get("/{app_id}/network",
            dependencies=[Depends(_read_scoped),
                          Depends(require_entitlement("network.guest_config"))])
def app_network(request: Request, app_id: int, db=Depends(get_db),
                user: User = Depends(_read_scoped)):
    a, host = _app_and_host(db, app_id)
    return guest_nics(request, db, host, "lxc", a.ctid, a)


# Above the lifecycle wildcard, same as /{app_id}/network directly above:
# registered after it, "firewall" matches as an ACTION and never gets here.
@router.get("/{app_id}/firewall/rules",
            dependencies=[Depends(_fw_read),
                          Depends(require_entitlement("firewall.view"))])
def app_fw_rules(request: Request, app_id: int, db=Depends(get_db),
                 user: User = Depends(_fw_read)):
    a, host = _app_and_host(db, app_id)
    return fwapi.guest_rules(request, db, host, "lxc", a.ctid, a)


@router.post("/{app_id}/firewall/rules", status_code=201,
             dependencies=[Depends(_fw_guest),
                           Depends(require_entitlement("firewall.rules"))])
def app_fw_rule_create(request: Request, app_id: int, body: RuleIn,
                       db=Depends(get_db), user: User = Depends(_fw_guest)):
    a, host = _app_and_host(db, app_id)
    return fwapi.guest_rule_create(request, db, user, host, "lxc", a.ctid, a, body)


@router.put("/{app_id}/firewall/rules/{pos}",
            dependencies=[Depends(_fw_guest),
                          Depends(require_entitlement("firewall.rules"))])
def app_fw_rule_update(request: Request, app_id: int, pos: RulePos, body: RulePatch,
                       db=Depends(get_db), user: User = Depends(_fw_guest)):
    a, host = _app_and_host(db, app_id)
    return fwapi.guest_rule_update(request, db, user, host, "lxc", a.ctid, a,
                                   pos, body)


@router.put("/{app_id}/firewall/rules/{pos}/move",
            dependencies=[Depends(_fw_guest),
                          Depends(require_entitlement("firewall.rules"))])
def app_fw_rule_move(request: Request, app_id: int, pos: RulePos, body: MoveIn,
                     db=Depends(get_db), user: User = Depends(_fw_guest)):
    a, host = _app_and_host(db, app_id)
    return fwapi.guest_rule_move(request, db, user, host, "lxc", a.ctid, a, pos,
                                 body)


@router.delete("/{app_id}/firewall/rules/{pos}",
               dependencies=[Depends(_fw_guest),
                             Depends(require_entitlement("firewall.rules"))])
def app_fw_rule_delete(request: Request, app_id: int, pos: RulePos,
                       digest: str | None = None, db=Depends(get_db),
                       user: User = Depends(_fw_guest)):
    a, host = _app_and_host(db, app_id)
    return fwapi.guest_rule_delete(request, db, user, host, "lxc", a.ctid, a,
                                   pos, digest)


@router.get("/{app_id}/firewall/options",
            dependencies=[Depends(_fw_read),
                          Depends(require_entitlement("firewall.view"))])
def app_fw_options(request: Request, app_id: int, db=Depends(get_db),
                   user: User = Depends(_fw_read)):
    a, host = _app_and_host(db, app_id)
    return fwapi.guest_options(request, db, host, "lxc", a.ctid, a)


@router.put("/{app_id}/firewall/options",
            dependencies=[Depends(_fw_guest),
                          Depends(require_entitlement("firewall.options"))])
def app_fw_options_update(request: Request, app_id: int, body: OptionsIn,
                          db=Depends(get_db), user: User = Depends(_fw_guest)):
    a, host = _app_and_host(db, app_id)
    return fwapi.guest_options_update(request, db, user, host, "lxc", a.ctid, a,
                                      body)


@router.get("/{app_id}/firewall/aliases",
            dependencies=[Depends(_fw_read),
                          Depends(require_entitlement("firewall.view"))])
def app_fw_aliases(request: Request, app_id: int, db=Depends(get_db),
                   user: User = Depends(_fw_read)):
    a, host = _app_and_host(db, app_id)
    return fwapi.guest_aliases(request, db, host, "lxc", a.ctid, a)


@router.post("/{app_id}/firewall/aliases", status_code=201,
             dependencies=[Depends(_fw_guest),
                           Depends(require_entitlement("firewall.objects"))])
def app_fw_alias_create(request: Request, app_id: int, body: AliasIn,
                        db=Depends(get_db), user: User = Depends(_fw_guest)):
    a, host = _app_and_host(db, app_id)
    return fwapi.guest_alias_create(request, db, user, host, "lxc", a.ctid, a, body)


@router.put("/{app_id}/firewall/aliases/{name}",
            dependencies=[Depends(_fw_guest),
                          Depends(require_entitlement("firewall.objects"))])
def app_fw_alias_update(request: Request, app_id: int, name: ObjectName,
                        body: AliasPatch, db=Depends(get_db),
                        user: User = Depends(_fw_guest)):
    a, host = _app_and_host(db, app_id)
    return fwapi.guest_alias_update(request, db, user, host, "lxc", a.ctid, a,
                                    name, body)


@router.delete("/{app_id}/firewall/aliases/{name}",
               dependencies=[Depends(_fw_guest),
                             Depends(require_entitlement("firewall.objects"))])
def app_fw_alias_delete(request: Request, app_id: int, name: ObjectName,
                        digest: str | None = None, db=Depends(get_db),
                        user: User = Depends(_fw_guest)):
    a, host = _app_and_host(db, app_id)
    return fwapi.guest_alias_delete(request, db, user, host, "lxc", a.ctid, a,
                                    name, digest)


@router.get("/{app_id}/firewall/ipsets",
            dependencies=[Depends(_fw_read),
                          Depends(require_entitlement("firewall.view"))])
def app_fw_ipsets(request: Request, app_id: int, db=Depends(get_db),
                  user: User = Depends(_fw_read)):
    a, host = _app_and_host(db, app_id)
    return fwapi.guest_ipsets(request, db, host, "lxc", a.ctid, a)


@router.post("/{app_id}/firewall/ipsets", status_code=201,
             dependencies=[Depends(_fw_guest),
                           Depends(require_entitlement("firewall.objects"))])
def app_fw_ipset_create(request: Request, app_id: int, body: IpSetIn,
                        db=Depends(get_db), user: User = Depends(_fw_guest)):
    a, host = _app_and_host(db, app_id)
    return fwapi.guest_ipset_create(request, db, user, host, "lxc", a.ctid, a, body)


@router.delete("/{app_id}/firewall/ipsets/{name}",
               dependencies=[Depends(_fw_guest),
                             Depends(require_entitlement("firewall.objects"))])
def app_fw_ipset_delete(request: Request, app_id: int, name: ObjectName,
                        force: bool = False, digest: str | None = None,
                        db=Depends(get_db), user: User = Depends(_fw_guest)):
    a, host = _app_and_host(db, app_id)
    return fwapi.guest_ipset_delete(request, db, user, host, "lxc", a.ctid, a,
                                    name, force, digest)


@router.get("/{app_id}/firewall/ipsets/{name}/members",
            dependencies=[Depends(_fw_read),
                          Depends(require_entitlement("firewall.view"))])
def app_fw_ipset_members(request: Request, app_id: int, name: ObjectName,
                         db=Depends(get_db), user: User = Depends(_fw_read)):
    a, host = _app_and_host(db, app_id)
    return fwapi.guest_ipset_members(request, db, host, "lxc", a.ctid, a, name)


@router.post("/{app_id}/firewall/ipsets/{name}/members", status_code=201,
             dependencies=[Depends(_fw_guest),
                           Depends(require_entitlement("firewall.objects"))])
def app_fw_ipset_member_add(request: Request, app_id: int, name: ObjectName,
                            body: MemberIn, db=Depends(get_db),
                            user: User = Depends(_fw_guest)):
    a, host = _app_and_host(db, app_id)
    return fwapi.guest_ipset_member_add(request, db, user, host, "lxc", a.ctid,
                                        a, name, body)


# {cidr:path}: a CIDR contains a slash and a plain path parameter stops at the
# first one, so 10.0.0.0/8 would never match this route.
@router.put("/{app_id}/firewall/ipsets/{name}/members/{cidr:path}",
            dependencies=[Depends(_fw_guest),
                          Depends(require_entitlement("firewall.objects"))])
def app_fw_ipset_member_update(request: Request, app_id: int, name: ObjectName,
                               cidr: str, body: MemberPatch,
                               db=Depends(get_db),
                               user: User = Depends(_fw_guest)):
    a, host = _app_and_host(db, app_id)
    return fwapi.guest_ipset_member_update(request, db, user, host, "lxc",
                                           a.ctid, a, name, cidr, body)


@router.delete("/{app_id}/firewall/ipsets/{name}/members/{cidr:path}",
               dependencies=[Depends(_fw_guest),
                             Depends(require_entitlement("firewall.objects"))])
def app_fw_ipset_member_delete(request: Request, app_id: int, name: ObjectName,
                               cidr: str, digest: str | None = None,
                               db=Depends(get_db),
                               user: User = Depends(_fw_guest)):
    a, host = _app_and_host(db, app_id)
    return fwapi.guest_ipset_member_delete(request, db, user, host, "lxc",
                                           a.ctid, a, name, cidr, digest)


@router.get("/{app_id}/firewall/refs",
            dependencies=[Depends(_fw_read),
                          Depends(require_entitlement("firewall.view"))])
def app_fw_refs(request: Request, app_id: int, type: str | None = None,
                db=Depends(get_db), user: User = Depends(_fw_read)):
    a, host = _app_and_host(db, app_id)
    return fwapi.guest_refs(request, db, host, "lxc", a.ctid, a, ref_type=type)


@router.get("/{app_id}/firewall/log",
            dependencies=[Depends(_fw_read),
                          Depends(require_entitlement("firewall.log"))])
def app_fw_log(request: Request, app_id: int, start: int = 0, limit: int = 500,
               since: int | None = None, until: int | None = None,
               db=Depends(get_db), user: User = Depends(_fw_read)):
    a, host = _app_and_host(db, app_id)
    return fwapi.guest_log(request, db, host, "lxc", a.ctid, a, start=start,
                           limit=limit, since=since, until=until)


@router.get("/{app_id}/web-url",
            dependencies=[Depends(_read_scoped),
                          Depends(require_entitlement("network.guest_config"))])
def app_web_url(request: Request, app_id: int, db=Depends(get_db),
                user: User = Depends(_read_scoped)):
    """The whole URL to point a tab at, built here rather than in the browser.

    The address is read live off the guest's own NIC config, because DHCP or a
    manual re-IP moves it and a value cached at install would point at the old
    one. The scheme is asked of the app itself (services/webui.py), which a
    page on Proxploy's own origin cannot do: a cross-origin probe of a
    self-signed https app fails opaquely, so the browser cannot tell "speaks
    https" from "is not there".

    Port and path follow the same precedence the scheme does: what the operator
    set, then what the install script printed, then the catalog. The operator's
    value is never written over, and the catalog is last because it describes
    the app in general rather than this container.

    Every failure is a 409 naming what is missing, never a URL built from a
    default: sending someone to a page that cannot load and calling that
    success is the bug this endpoint exists to end.
    """
    a, host = _app_and_host(db, app_id)
    entry = (db.query(CatalogEntry).filter_by(slug=a.catalog_slug).one_or_none()
             if a.catalog_slug else None)
    _, installed_port, installed_path = installed_parts(a.installed_url)
    port = a.web_port or installed_port or (entry.port if entry else None)
    if port is None:
        raise HTTPException(409, f"Proxploy does not know which port {a.name}'s "
                                 f"web interface answers on. Set the web port "
                                 f"in Reconfigure and try again.")
    # "/" is not an operator's answer, it is the column's own placeholder, so
    # a real path the installer printed is preferred over it. Anything else in
    # web_path was typed by a person and wins.
    path = a.web_path if a.web_path not in (None, "", "/") else (installed_path or "/")
    # `addresses`, not the config's `ip`: a container on DHCP has the literal
    # word `dhcp` there, so reading the config rejected every DHCP guest.
    address = next((str(v).split("/")[0]
                    for nic in guest_nics(request, db, host, "lxc", a.ctid, a)
                    for v in (nic.get("addresses") or [])), None)
    if not address:
        raise HTTPException(409, f"Proxploy could not find an address for "
                                 f"{a.name}. Start the container if it is "
                                 f"stopped, then try again.")
    protocol, decided_by = scheme_for(a, address, port)
    if protocol is None:
        raise HTTPException(409, f"{a.name} did not answer at {address}:{port}, "
                                 f"so Proxploy cannot tell whether it uses http "
                                 f"or https. It will not guess and send you to a "
                                 f"page that fails to load. Start {a.name} if it "
                                 f"is not running, or set the protocol in "
                                 f"Reconfigure.")
    return {"url": f"{protocol}://{address}:{port}{path}",
            "protocol": protocol, "protocol_decided_by": decided_by}


@router.put("/{app_id}/network/{iface}",
            dependencies=[Depends(_configure),
                          Depends(require_entitlement("network.guest_config"))])
def app_network_update(request: Request, app_id: int, iface: str, body: NicIn,
                       db=Depends(get_db), user: User = Depends(_configure)):
    a, host = _app_and_host(db, app_id)
    return set_guest_nic(request, db, user, target_type="app", target_id=a.id,
                         host=host, kind="lxc", vmid=a.ctid, iface=iface, body=body,
                         row=a)


class MigratePreflightIn(BaseModel):
    target_host_id: int
    # So the dialog can preview the operator's chosen pool, including its
    # capacity, before committing to it.
    storage: str | None = None


# Three literal segments, so this cannot structurally collide with the
# 2-segment /{app_id}/{action} template, but it is registered above the
# lifecycle wildcard anyway: one place operators look for every non-lifecycle
# app route, and no surprises if that wildcard's shape ever widens.
@router.post("/{app_id}/migrate/preflight",
             dependencies=[Depends(_migrate),
                          Depends(require_entitlement("migrate.preflight"))])
def migrate_preflight(request: Request, app_id: int, body: MigratePreflightIn,
                      db=Depends(get_db), user: User = Depends(_migrate)):
    a = db.get(App, app_id)
    if a is None:
        raise HTTPException(404, "app not found")
    target = db.get(Host, body.target_host_id)
    # A missing target_host_id and an unreachable one are the same
    # caller-facing problem ("not a usable migration target"), so both collapse
    # to one 409 rather than a 404/409 split the frontend must special-case.
    if (target is None or body.target_host_id == a.host_id
            or target.status != "connected"):
        raise HTTPException(409, "target host is unknown, is the app's current "
                                 "host, or is not connected")
    try:
        return migrate_service.preflight(request.app, db, a, body.target_host_id,
                                         body.storage)
    except ProxmoxError as e:
        raise HTTPException(502, str(e))


class MigrateIn(BaseModel):
    target_host_id: int
    confirm: str | None = None
    # Where the guest's disk should land on the target. None takes preflight's
    # default, the first pool that can hold a rootfs. A name that cannot hold
    # one is a preflight blocker, never a silent swap.
    storage: str | None = None


@router.post("/{app_id}/migrate", status_code=202,
             dependencies=[Depends(_migrate),
                          Depends(require_entitlement("migrate.cross_host"))])
def migrate_app_route(request: Request, app_id: int, body: MigrateIn,
                      db=Depends(get_db), user: User = Depends(_migrate)):
    """Params handed to the job are ONLY app_id/target_host_id: strategy,
    target ctid and storage all come from a FRESH preflight the handler runs
    itself, because host connectivity, storage and capacity can change between
    this request and the job actually running."""
    a = db.get(App, app_id)
    if a is None:
        raise HTTPException(404, "app not found")
    target = db.get(Host, body.target_host_id)
    if (target is None or body.target_host_id == a.host_id
            or target.status != "connected"):
        raise HTTPException(409, "target host is unknown, is the app's current "
                                 "host, or is not connected")
    try:
        pf = migrate_service.preflight(request.app, db, a, body.target_host_id,
                                       body.storage)
    except ProxmoxError as e:
        raise HTTPException(502, str(e))
    if pf["blockers"]:
        raise HTTPException(409, {"error": "migration_blocked",
                                  "blockers": pf["blockers"]})
    ip = request.client.host if request.client else None
    if is_self(db, "app", a.id):
        if (body.confirm or "") != a.name:
            write_audit(db, actor_type="user", actor_id=user.id,
                        action="app.migrate", target_type="app", target_id=a.id,
                        result="denied", ip=ip)
            raise HTTPException(409, {
                "error": "self_target", "confirm_phrase": a.name,
                "detail": (f"{a.name} is the container Proxploy itself runs in. "
                           f"Migrating it can strand its own recovery path. "
                           f"Type the name to confirm."),
            })
    # Resolve every token this job will spend BEFORE queueing it. Without this
    # a host missing its lifecycle or backup token accepted the migration and
    # discovered the gap inside the handler, which for a transfer means AFTER
    # the source guest has been stopped. No network call happens here:
    # client_for_host raises CapabilityNotConfigured on a missing credential
    # alone. The strategy decides which tokens are needed, which is why this
    # sits after the preflight rather than in a dependency.
    needed = ("lifecycle",) if pf["strategy"] == migrate_service.STRATEGY_CLUSTER \
        else ("lifecycle", "backup")
    for host in (db.get(Host, a.host_id), target):
        if host is None:
            continue
        for capability in needed:
            client_for_host(request.app, db, host, capability=capability)
    result = enqueue_and_audit(request, db, user, kind="migrate.app",
                               target_type="app", target_id=app_id,
                               params={"app_id": app_id,
                                       "target_host_id": body.target_host_id,
                                       "storage": body.storage},
                               action="app.migrate")
    return {**result, "preflight": pf}


class UninstallIn(BaseModel):
    # The app's own name, typed back. Required for every uninstall that
    # destroys a container, not only for Proxploy's own CT: stop is reversible
    # and destroy is not, so the guard belongs on the operation.
    confirm: str | None = None
    # Forget the app without touching PVE. The inverse of adopt: the CT keeps
    # running and Proxploy stops tracking it. No confirmation needed because
    # nothing is destroyed and re-adopting restores the row.
    keep_ct: bool = False


class ReconfigureIn(BaseModel):
    # PVE-side resources. None means "leave alone"; this is a PATCH.
    cores: int | None = None
    memory_mb: int | None = None
    swap_mb: int | None = None
    # Proxploy-side presentation, no PVE call involved.
    name: str | None = None
    web_port: int | None = None
    web_protocol: str | None = None
    web_path: str | None = None
    # The tile an app wears when the catalog has no icon for it, which is every
    # app adopted by hand: `icon_url` is served from the CATALOG entry, so an
    # app with no catalog slug can never have one.
    icon_initials: str | None = Field(default=None, max_length=3)
    icon_colors: dict | None = None

    @field_validator("icon_colors")
    @classmethod
    def _colors_are_hex(cls, v):
        # The frontend interpolates these into a `style` attribute, so an
        # unvalidated dict is a CSS injection: `{"dark": "red;background:url(
        # //evil/x)"}` would have been stored and rendered verbatim. The
        # column is free-form JSON and this schema types it as `dict`, so the
        # shape is enforced here or nowhere.
        if v is not None and not valid_colors(v):
            raise ValueError('icon_colors must be {"dark": "#RRGGBB", '
                             '"light": "#RRGGBB"}')
        return v


@router.delete("/{app_id}", dependencies=[Depends(_remove),
                                          Depends(require_entitlement("apps.uninstall"))])
def uninstall_app(request: Request, app_id: int, body: UninstallIn = Body(default=UninstallIn()),
                  db=Depends(get_db), user: User = Depends(_remove)):
    """Remove an app, either by destroying its CT or by forgetting it. One app
    is exactly one LXC container, so "uninstall" is "destroy that container";
    `keep_ct` is the inverse of adopt, for the operator who wants Proxploy out
    of the way without losing the workload.
    """
    a = db.get(App, app_id)
    if a is None:
        raise HTTPException(404, "app not found")
    ip = request.client.host if request.client else None

    if body.keep_ct:
        write_audit(db, actor_type="user", actor_id=user.id, action="app.forget",
                    target_type="app", target_id=a.id,
                    params={"ctid": a.ctid, "host_id": a.host_id}, ip=ip)
        db.delete(a)
        db.commit()
        request.app.state.bus.publish("resource", {"type": "app", "id": app_id,
                                                   "change": "removed"})
        return {"removed": True, "ct_kept": True}

    if (body.confirm or "") != a.name:
        # Deliberately the same 409 shape the self-target guard uses, so one
        # frontend confirmation dialog serves both.
        write_audit(db, actor_type="user", actor_id=user.id, action="app.uninstall",
                    target_type="app", target_id=a.id, result="denied", ip=ip)
        raise HTTPException(409, {
            "error": "confirm_required", "confirm_phrase": a.name,
            "detail": (f"Uninstalling {a.name} destroys CT {a.ctid} and its disk. "
                       f"This cannot be undone. Type the name to confirm, or "
                       f"pass keep_ct to forget the app and leave the container "
                       f"running."),
        })

    result = enqueue_and_audit(request, db, user, kind="app.uninstall",
                              target_type="app", target_id=app_id,
                              params={"target_id": app_id},
                              action="app.uninstall")
    return result


@router.patch("/{app_id}", dependencies=[Depends(_configure),
                                         Depends(require_entitlement("apps.reconfigure"))])
def reconfigure_app(request: Request, app_id: int,
                    body: ReconfigureIn = Body(default=ReconfigureIn()),
                    db=Depends(get_db), user: User = Depends(_configure)):
    """Resize a CT and/or edit how Proxploy presents the app.

    Resource changes go straight to PVE rather than through a job: an lxc
    config write is synchronous there, so there is no task to track.

    Disk size is deliberately not here. Growing a CT's root volume is a
    different PVE endpoint and is one-way, since PVE cannot shrink, so it is
    its own feature with its own confirmation.

    cores/memory/swap are lifecycle privileges, so the client below asks for
    "lifecycle" explicitly rather than taking whatever `client_for_host`
    resolves by default.
    """
    a = db.get(App, app_id)
    if a is None:
        raise HTTPException(404, "app not found")

    pve_config = {}
    if body.cores is not None:
        if body.cores < 1:
            raise HTTPException(422, "cores must be at least 1")
        pve_config["cores"] = body.cores
    if body.memory_mb is not None:
        if body.memory_mb < 16:
            raise HTTPException(422, "memory_mb must be at least 16")
        pve_config["memory"] = body.memory_mb
    if body.swap_mb is not None:
        if body.swap_mb < 0:
            raise HTTPException(422, "swap_mb cannot be negative")
        pve_config["swap"] = body.swap_mb

    if pve_config:
        host = db.get(Host, a.host_id)
        if host is None:
            raise HTTPException(409, "app has no host")
        from proxploy.services.hostclient import client_for_host
        try:
            client = client_for_host(request.app, db, host, capability="lifecycle")
            client.guest_config_update("lxc", host.node_name or "", a.ctid, pve_config)
        except ProxmoxError as e:
            raise HTTPException(502, {"error": "pve_error", "detail": str(e)}) from e

    if body.web_protocol is not None:
        # Only two values open in a browser, and a third would be stored as
        # fact and then built into a URL that cannot load. Blank is allowed and
        # clears it, putting the app back to being asked which scheme it speaks.
        body.web_protocol = body.web_protocol.strip().lower() or None
        if body.web_protocol not in (None, "http", "https"):
            raise HTTPException(422, "Protocol must be http or https, or left "
                                     "blank to let Proxploy ask the app.")

    changed = dict(pve_config)
    for field in ("name", "web_port", "web_protocol", "web_path",
                  "icon_initials", "icon_colors"):
        value = getattr(body, field)
        # web_protocol is the one field a None can mean "clear this" for, so
        # it is applied when the caller sent the key at all rather than when
        # the value is non-null.
        if value is not None or (field == "web_protocol"
                                 and "web_protocol" in body.model_fields_set):
            setattr(a, field, value)
            changed[field] = value

    if not changed:
        raise HTTPException(422, "nothing to change")

    write_audit(db, actor_type="user", actor_id=user.id,
                action="app.reconfigure", target_type="app", target_id=a.id,
                params={"changed": sorted(changed)},
                ip=request.client.host if request.client else None)
    db.commit()
    request.app.state.bus.publish("resource", {"type": "app", "id": app_id,
                                               "change": "reconfigured"})
    return {"id": a.id, "changed": changed}


class LifecycleIn(BaseModel):
    confirm: str | None = None


def enqueue_lifecycle(request: Request, db, user: User, *, target_type: str,
                      target, action: str, name: str, confirm: str | None):
    """Shared by the apps and VMs routes, one guardrail, one audit shape.

    A destructive action against the CT Proxploy itself runs in is refused
    unless the caller types the name back.
    """
    ip = request.client.host if request.client else None
    if action in DESTRUCTIVE and is_self(db, target_type, target.id):
        if (confirm or "") != name:
            write_audit(db, actor_type="user", actor_id=user.id,
                        action=job_kind(target_type, action),
                        target_type=target_type, target_id=target.id,
                        result="denied", ip=ip)
            raise HTTPException(409, {
                "error": "self_target", "confirm_phrase": name,
                "detail": (f"{name} is the container Proxploy itself runs in. "
                           f"A {action} here can strand its own recovery path. "
                           f"Type the name to confirm."),
            })
    job = request.app.state.jobs.enqueue(
        db, kind=job_kind(target_type, action), target_type=target_type,
        target_id=target.id, params={"target_id": target.id, "action": action},
        requested_by=user.id)
    write_audit(db, actor_type="user", actor_id=user.id,
                action=job_kind(target_type, action), target_type=target_type,
                target_id=target.id, params={"action": action},
                job_id=job.id, ip=ip)
    return job


# WARNING: this wildcard is registered last and Starlette matches in
# registration order, so it will silently swallow any future two-segment
# sibling under /apps/{id}/..., e.g. /apps/{id}/update and /apps/{id}/migrate
# above. Register such routes with their literal action segments BEFORE this
# one, or they hit this handler and 422.
@router.post("/{app_id}/{action}", status_code=202,
             dependencies=[Depends(_lifecycle),
                          Depends(require_entitlement("apps.lifecycle"))])
def app_lifecycle(request: Request, app_id: int, action: str,
                  body: LifecycleIn = Body(default=LifecycleIn()),
                  db=Depends(get_db),
                  user: User = Depends(_lifecycle)):
    if action not in APP_ACTIONS:
        raise HTTPException(422, f"action must be one of {', '.join(APP_ACTIONS)}")
    a = db.get(App, app_id)
    if a is None:
        raise HTTPException(404, "app not found")
    job = enqueue_lifecycle(request, db, user, target_type="app", target=a,
                            action=action, name=a.name, confirm=body.confirm)
    return {"job": job_out(job)}


# --- custom app icons -------------------------------------------------------
# Guarded by app:configure, the same permission that already renames an app and
# sets its tile letters: an icon is presentation, and splitting it into its own
# permission would make the Set-up dialog need two.

@router.put("/{app_id}/icon", dependencies=[Depends(_configure)])
async def upload_icon(app_id: int, request: Request,
                      file: UploadFile = File(...), db=Depends(get_db),
                      user: User = Depends(_configure)):
    """Replace this app's icon with an uploaded image.

    PUT and not POST: an app has exactly one icon and uploading twice must
    leave one icon, not two. The whole file is read into memory rather than
    spooled to disk the way storage.py does, because storage.py is streaming
    multi-gigabyte ISOs onward to PVE and this is capped at 8 MB and has to be
    fully decoded anyway to be validated at all.
    """
    a = db.get(App, app_id)
    if a is None:
        raise HTTPException(404, "app not found")

    raw = await file.read()
    try:
        app_icons.store(request.app.state.settings.data_dir, app_id, raw)
    except app_icons.BadImage as e:
        # 422, not 400: the request is well-formed, its content is not.
        raise HTTPException(422, str(e)) from e

    write_audit(db, actor_type="user", actor_id=user.id, action="app.icon_set",
                target_type="app", target_id=a.id,
                params={"bytes": len(raw), "filename": file.filename},
                ip=request.client.host if request.client else None)
    db.commit()
    request.app.state.bus.publish("resource", {"type": "app", "id": app_id,
                                               "change": "reconfigured"})
    return {"icon_url": app_icons.custom_icon_url(
        request.app.state.settings.data_dir, app_id)}


@router.delete("/{app_id}/icon", dependencies=[Depends(_configure)])
def delete_icon(app_id: int, request: Request, db=Depends(get_db),
                user: User = Depends(_configure)):
    """Drop the uploaded icon; the app falls back to its catalog logo if it has
    one, and to its monogram tile otherwise."""
    a = db.get(App, app_id)
    if a is None:
        raise HTTPException(404, "app not found")
    removed = app_icons.remove(request.app.state.settings.data_dir, app_id)
    if removed:
        write_audit(db, actor_type="user", actor_id=user.id,
                    action="app.icon_cleared", target_type="app", target_id=a.id,
                    ip=request.client.host if request.client else None)
        db.commit()
        request.app.state.bus.publish("resource", {"type": "app", "id": app_id,
                                                   "change": "reconfigured"})
    return {"removed": removed}


@router.get("/{app_id}/icon", dependencies=[Depends(_read_scoped)])
def get_icon(app_id: int, request: Request):
    """Serve the uploaded icon.

    No DB lookup: the file either exists or it does not, and _read_scoped has
    already decided this caller may look at this app. The `v` query parameter
    the serializer appends is not read here — it exists only to give the URL a
    new identity when the file changes, so a cached copy is not reused.
    """
    path = app_icons.icon_path(request.app.state.settings.data_dir, app_id)
    if not path.is_file():
        raise HTTPException(404, "no custom icon for this app")
    return FileResponse(path, media_type="image/webp",
                        headers={"Cache-Control": "public, max-age=86400"})
