"""Firewall rules, options and objects at cluster, node, guest and security
group scope.

Live passthrough, exactly as api/network.py's bridge reads are: no model, no
cache, no migration, and nothing in the poller. Firewall rules are
configuration rather than telemetry, and reading them per guest on a schedule
would break the O(nodes) call budget in doc 02 section 3. Rules load when a
page asks for them.

These are NOT jobs. Every firewall write returns null rather than a UPID
(measured on pve-manager 9.2.11, 2026-08-21), so there is no PVE task to
follow. Same call shape as api/network.py::set_guest_nic.

Spec: docs/superpowers/specs/2026-08-21-firewall-design.md
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from proxploy.api.deps import (authorize, get_db, require_entitlement,
                               scope_host)
from proxploy.models import Host, User
from proxploy.services import firewall as fw
from proxploy.services.audit import write_audit
from proxploy.services.proxmox import ProxmoxError

router = APIRouter(prefix="/firewall", tags=["firewall"])

# Singleton first in dependencies=[...] and reused as the parameter dep, so
# auth runs before the entitlement gate and FastAPI collapses the two
# (deps.py idiom; test_route_auth_invariant.py enforces it).
_read = authorize("firewall", "read", scope_of=scope_host())
_manage = authorize("firewall", "manage", scope_of=scope_host())


def _host_or_404(db, host_id: int) -> Host:
    host = db.get(Host, host_id)
    if host is None:
        raise HTTPException(404, "That host is not enrolled.")
    return host


def pve_error(e: ProxmoxError) -> HTTPException:
    """A 502 means Proxploy could not complete a call to Proxmox, never that
    the rule was rejected: PVE's own refusals arrive as text inside this."""
    return HTTPException(502, str(e))


class RuleIn(BaseModel):
    """One firewall rule, in PVE's own vocabulary.

    `icmp-type` is aliased rather than renamed. It is not a valid Python
    identifier, so it cannot be a field name or a keyword argument, and any
    snake_case translation on the way through drops the field silently.
    Everything here dumps with by_alias=True for that one reason.

    `enable` is an integer, not a boolean: PVE's schema says
    "<integer> (0 - N)". Sending true would be serialised as "True".
    """
    model_config = {"populate_by_name": True}

    type: str                       # in, out, forward, group
    action: str                     # ACCEPT, DROP, REJECT, or a group name
    enable: int | None = None
    macro: str | None = None
    iface: str | None = None
    source: str | None = None
    dest: str | None = None
    sport: str | None = None
    dport: str | None = None
    proto: str | None = None
    log: str | None = None
    icmp_type: str | None = Field(default=None, alias="icmp-type")
    comment: str | None = None
    digest: str | None = None


class RulePatch(BaseModel):
    """Every field optional. Only fields PRESENT in the body are applied, so
    the handler dumps with exclude_unset=True: absent means "leave alone"."""
    model_config = {"populate_by_name": True}

    type: str | None = None
    action: str | None = None
    enable: int | None = None
    macro: str | None = None
    iface: str | None = None
    source: str | None = None
    dest: str | None = None
    sport: str | None = None
    dport: str | None = None
    proto: str | None = None
    log: str | None = None
    icmp_type: str | None = Field(default=None, alias="icmp-type")
    comment: str | None = None
    digest: str | None = None
    delete: str | None = None       # PVE's own "unset these keys" parameter


class MoveIn(BaseModel):
    moveto: int
    digest: str | None = None


def rule_params(model: BaseModel, *, partial: bool = False) -> dict:
    """PVE-shaped keys, hyphen intact, Nones dropped by the client layer."""
    return model.model_dump(by_alias=True, exclude_unset=partial,
                            exclude_none=True)


# ---------------------------------------------------------------- rules

def _rules_read(request: Request, db, host: Host, loc: dict, scope: str) -> dict:
    try:
        rules = fw.readers(request.app, db, host).firewall_rules(loc)
    except ProxmoxError as e:
        raise pve_error(e)
    # PVE returns the digest on each rule row rather than on the collection.
    # Surfacing the first one gives the client something to send back on a
    # write without it having to know that.
    digest = rules[0].get("digest") if rules else None
    return {"scope": scope, "rules": rules, "digest": digest}


def _rules_write(request: Request, db, user: User, host: Host, loc: dict, *,
                 action: str, label: str, params: dict, call) -> None:
    ip = request.client.host if request.client else None
    try:
        call(fw.writers(request.app, db, host))
    except ProxmoxError as e:
        write_audit(db, actor_type="user", actor_id=user.id, action=action,
                    target_type="host", target_id=host.id, target_name=label,
                    params=params, result="error", ip=ip)
        raise pve_error(e)
    write_audit(db, actor_type="user", actor_id=user.id, action=action,
                target_type="host", target_id=host.id, target_name=label,
                params=params, ip=ip)


@router.get("/cluster/{host_id}/rules",
            dependencies=[Depends(_read),
                          Depends(require_entitlement("firewall.view"))])
def cluster_rules(request: Request, host_id: int, db=Depends(get_db),
                  user: User = Depends(_read)):
    host = _host_or_404(db, host_id)
    return _rules_read(request, db, host, fw.cluster_loc(), "cluster")


@router.post("/cluster/{host_id}/rules", status_code=201,
             dependencies=[Depends(_manage),
                           Depends(require_entitlement("firewall.rules"))])
def cluster_rule_create(request: Request, host_id: int, body: RuleIn,
                        db=Depends(get_db), user: User = Depends(_manage)):
    host = _host_or_404(db, host_id)
    params = rule_params(body)
    _rules_write(request, db, user, host, fw.cluster_loc(),
                 action="firewall.rule_create",
                 label=f"cluster firewall on {host.name}", params=params,
                 call=lambda c: c.firewall_rule_create(fw.cluster_loc(), params))
    return {"created": True}


@router.put("/cluster/{host_id}/rules/{pos}",
            dependencies=[Depends(_manage),
                          Depends(require_entitlement("firewall.rules"))])
def cluster_rule_update(request: Request, host_id: int, pos: int,
                        body: RulePatch, db=Depends(get_db),
                        user: User = Depends(_manage)):
    host = _host_or_404(db, host_id)
    params = rule_params(body, partial=True)
    _rules_write(request, db, user, host, fw.cluster_loc(),
                 action="firewall.rule_update",
                 label=f"rule {pos} in the cluster firewall on {host.name}",
                 params=params,
                 call=lambda c: c.firewall_rule_update(fw.cluster_loc(), pos, params))
    return {"updated": True}


@router.put("/cluster/{host_id}/rules/{pos}/move",
            dependencies=[Depends(_manage),
                          Depends(require_entitlement("firewall.rules"))])
def cluster_rule_move(request: Request, host_id: int, pos: int, body: MoveIn,
                      db=Depends(get_db), user: User = Depends(_manage)):
    host = _host_or_404(db, host_id)
    params = {"moveto": body.moveto, "digest": body.digest}
    _rules_write(request, db, user, host, fw.cluster_loc(),
                 action="firewall.rule_move",
                 label=f"rule {pos} in the cluster firewall on {host.name}",
                 params={"moveto": body.moveto},
                 call=lambda c: c.firewall_rule_move(fw.cluster_loc(), pos,
                                                     body.moveto, body.digest))
    return {"moved": True, "pos": body.moveto}


@router.delete("/cluster/{host_id}/rules/{pos}",
               dependencies=[Depends(_manage),
                             Depends(require_entitlement("firewall.rules"))])
def cluster_rule_delete(request: Request, host_id: int, pos: int,
                        digest: str | None = None, db=Depends(get_db),
                        user: User = Depends(_manage)):
    host = _host_or_404(db, host_id)
    _rules_write(request, db, user, host, fw.cluster_loc(),
                 action="firewall.rule_delete",
                 label=f"rule {pos} in the cluster firewall on {host.name}",
                 params={"pos": pos},
                 call=lambda c: c.firewall_rule_delete(fw.cluster_loc(), pos, digest))
    return {"deleted": True}


# ------------------------------------------------------- security group rules
#
# A security group IS a rule list (PVE documents GET on the group as "List
# rules"), so these are the cluster handlers above pointed at a different
# location, not a second implementation.

@router.get("/cluster/{host_id}/groups/{group}/rules",
            dependencies=[Depends(_read),
                          Depends(require_entitlement("firewall.view"))])
def group_rules(request: Request, host_id: int, group: str, db=Depends(get_db),
                user: User = Depends(_read)):
    host = _host_or_404(db, host_id)
    return _rules_read(request, db, host, fw.group_loc(group), "group")


@router.post("/cluster/{host_id}/groups/{group}/rules", status_code=201,
             dependencies=[Depends(_manage),
                           Depends(require_entitlement("firewall.rules"))])
def group_rule_create(request: Request, host_id: int, group: str, body: RuleIn,
                      db=Depends(get_db), user: User = Depends(_manage)):
    host = _host_or_404(db, host_id)
    params = rule_params(body)
    _rules_write(request, db, user, host, fw.group_loc(group),
                 action="firewall.rule_create",
                 label=f"security group {group} on {host.name}", params=params,
                 call=lambda c: c.firewall_rule_create(fw.group_loc(group), params))
    return {"created": True}


@router.put("/cluster/{host_id}/groups/{group}/rules/{pos}",
            dependencies=[Depends(_manage),
                          Depends(require_entitlement("firewall.rules"))])
def group_rule_update(request: Request, host_id: int, group: str, pos: int,
                      body: RulePatch, db=Depends(get_db),
                      user: User = Depends(_manage)):
    host = _host_or_404(db, host_id)
    params = rule_params(body, partial=True)
    _rules_write(request, db, user, host, fw.group_loc(group),
                 action="firewall.rule_update",
                 label=f"rule {pos} in security group {group} on {host.name}",
                 params=params,
                 call=lambda c: c.firewall_rule_update(fw.group_loc(group), pos,
                                                       params))
    return {"updated": True}


@router.put("/cluster/{host_id}/groups/{group}/rules/{pos}/move",
            dependencies=[Depends(_manage),
                          Depends(require_entitlement("firewall.rules"))])
def group_rule_move(request: Request, host_id: int, group: str, pos: int,
                    body: MoveIn, db=Depends(get_db),
                    user: User = Depends(_manage)):
    host = _host_or_404(db, host_id)
    _rules_write(request, db, user, host, fw.group_loc(group),
                 action="firewall.rule_move",
                 label=f"rule {pos} in security group {group} on {host.name}",
                 params={"moveto": body.moveto},
                 call=lambda c: c.firewall_rule_move(fw.group_loc(group), pos,
                                                     body.moveto, body.digest))
    return {"moved": True, "pos": body.moveto}


@router.delete("/cluster/{host_id}/groups/{group}/rules/{pos}",
               dependencies=[Depends(_manage),
                             Depends(require_entitlement("firewall.rules"))])
def group_rule_delete(request: Request, host_id: int, group: str, pos: int,
                      digest: str | None = None, db=Depends(get_db),
                      user: User = Depends(_manage)):
    host = _host_or_404(db, host_id)
    _rules_write(request, db, user, host, fw.group_loc(group),
                 action="firewall.rule_delete",
                 label=f"rule {pos} in security group {group} on {host.name}",
                 params={"pos": pos},
                 call=lambda c: c.firewall_rule_delete(fw.group_loc(group), pos,
                                                       digest))
    return {"deleted": True}


# ----------------------------------------------------------------- node rules

@router.get("/node/{host_id}/{node}/rules",
            dependencies=[Depends(_read),
                          Depends(require_entitlement("firewall.view"))])
def node_rules(request: Request, host_id: int, node: str, db=Depends(get_db),
               user: User = Depends(_read)):
    host = _host_or_404(db, host_id)
    return _rules_read(request, db, host, fw.node_loc(node), "node")


@router.post("/node/{host_id}/{node}/rules", status_code=201,
             dependencies=[Depends(_manage),
                           Depends(require_entitlement("firewall.rules"))])
def node_rule_create(request: Request, host_id: int, node: str, body: RuleIn,
                     db=Depends(get_db), user: User = Depends(_manage)):
    host = _host_or_404(db, host_id)
    params = rule_params(body)
    _rules_write(request, db, user, host, fw.node_loc(node),
                 action="firewall.rule_create",
                 label=f"firewall on {node}", params=params,
                 call=lambda c: c.firewall_rule_create(fw.node_loc(node), params))
    return {"created": True}


@router.put("/node/{host_id}/{node}/rules/{pos}",
            dependencies=[Depends(_manage),
                          Depends(require_entitlement("firewall.rules"))])
def node_rule_update(request: Request, host_id: int, node: str, pos: int,
                     body: RulePatch, db=Depends(get_db),
                     user: User = Depends(_manage)):
    host = _host_or_404(db, host_id)
    params = rule_params(body, partial=True)
    _rules_write(request, db, user, host, fw.node_loc(node),
                 action="firewall.rule_update",
                 label=f"rule {pos} in the firewall on {node}", params=params,
                 call=lambda c: c.firewall_rule_update(fw.node_loc(node), pos,
                                                       params))
    return {"updated": True}


@router.put("/node/{host_id}/{node}/rules/{pos}/move",
            dependencies=[Depends(_manage),
                          Depends(require_entitlement("firewall.rules"))])
def node_rule_move(request: Request, host_id: int, node: str, pos: int,
                   body: MoveIn, db=Depends(get_db),
                   user: User = Depends(_manage)):
    host = _host_or_404(db, host_id)
    _rules_write(request, db, user, host, fw.node_loc(node),
                 action="firewall.rule_move",
                 label=f"rule {pos} in the firewall on {node}",
                 params={"moveto": body.moveto},
                 call=lambda c: c.firewall_rule_move(fw.node_loc(node), pos,
                                                     body.moveto, body.digest))
    return {"moved": True, "pos": body.moveto}


@router.delete("/node/{host_id}/{node}/rules/{pos}",
               dependencies=[Depends(_manage),
                             Depends(require_entitlement("firewall.rules"))])
def node_rule_delete(request: Request, host_id: int, node: str, pos: int,
                     digest: str | None = None, db=Depends(get_db),
                     user: User = Depends(_manage)):
    host = _host_or_404(db, host_id)
    _rules_write(request, db, user, host, fw.node_loc(node),
                 action="firewall.rule_delete",
                 label=f"rule {pos} in the firewall on {node}",
                 params={"pos": pos},
                 call=lambda c: c.firewall_rule_delete(fw.node_loc(node), pos,
                                                       digest))
    return {"deleted": True}
